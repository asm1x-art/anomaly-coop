#include "stdafx.h"
#include "coop_props.h"
#include "coop_net.h"
#include "coop_puppet.h"
#include "coop_world.h"
#include "Level.h"
#include "PhysicsShellHolder.h"
#include "PhysicObject.h"
#include "inventory_item.h"
#include "BreakableObject.h"
#include "PHSynchronize.h"
#include "../xrPhysics/PhysicsShell.h"
#include "ai_space.h"
#include "alife_simulator.h"
#include "alife_object_registry.h"
#include "xrServer_Objects_ALife.h"
#include "xrServer_Objects_ALife_Items.h"
#include "level_graph.h"
#include "game_level_cross_table.h"
#include "game_graph.h"

namespace coop
{
	namespace
	{
		const u8 MAX_POSES = 64; // physics elements a thing may have to be sent (a door has two, a crate one)

		struct SSettings
		{
			float move = 0.10f;   // m an element moved from where the world has it, to be told
			float turn = 5.f;     // degrees it turned
			u32 check_ms = 500;   // how often things are looked at
			u32 min_gap_ms = 1000; // the least time between two rests of one thing sent
		};

		const SSettings& settings()
		{
			static SSettings s;
			static bool read = false;
			if (!read)
			{
				read = true;
				LPCSTR S = "coop_physics";
				s.move = READ_IF_EXISTS(pSettings, r_float, S, "rest_min_move", s.move);
				s.turn = READ_IF_EXISTS(pSettings, r_float, S, "rest_min_turn", s.turn);
				s.check_ms = READ_IF_EXISTS(pSettings, r_u32, S, "rest_check_ms", s.check_ms);
				s.min_gap_ms = READ_IF_EXISTS(pSettings, r_u32, S, "rest_min_gap_ms", s.min_gap_ms);
			}
			return s;
		}

		struct SPose
		{
			Fvector position;
			Fquaternion rotation;
		};
		typedef xr_vector<SPose> Poses;

		// where a thing lies: its object's place and its physics elements
		struct SRest
		{
			Fvector position;
			Fvector angle;
			Poses poses;
		};

		struct SProp
		{
			Poses agreed;     // where the world has it
			bool known = false; // lay still here once since it came online
			bool awake = false;
			bool settling = false; // put where the world has it: its next rest is where it settled, not sent
			u32 sent = 0;
			u32 seen = 0;     // the scan that last saw it online
		};

		xr_map<u16, SProp> g_props;    // things online here
		xr_set<u16> g_moved;           // their next rest goes, even the first
		xr_map<u16, SRest> g_pending;  // the world's place of items offline here, for when they come online
		xr_set<u16> g_theirs;          // releases another game sends
		const void* g_level = nullptr;
		const void* g_world = nullptr;
	}

	static xr_set<u16> g_by_logic;
	void set_by_logic(u16 id, bool on)
	{
		if (on)
			g_by_logic.insert(id);
		else
			g_by_logic.erase(id);
	}
	static bool is_by_logic(u16 id) { return g_by_logic.count(id) > 0; }

	void release_theirs(u16 id) { g_theirs.insert(id); }
	bool is_release_theirs(u16 id) { return g_theirs.erase(id) > 0; }
	void note_moved(u16 id) { g_moved.insert(id); }

	static CALifeSimulator& alife_rw()
	{
		return const_cast<CALifeSimulator&>(ai().alife());
	}

	// a thing whose place we keep the same: a physic object (a door too) or an item, on the ground, with physics
	static CPhysicsShellHolder* prop_of(CObject* object)
	{
		CPhysicsShellHolder* holder = smart_cast<CPhysicsShellHolder*>(object);
		if (!holder || holder->getDestroy() || holder->H_Parent())
			return nullptr;
		if (!smart_cast<CPhysicObject*>(object) && !smart_cast<CInventoryItem*>(object))
			return nullptr; // creatures and bodies (eBodyRest), vehicles, glass, the actor
		CPhysicsShell* shell = holder->PPhysicsShell();
		if (!shell || !shell->isActive() || !holder->PHGetSyncItemsNumber() || holder->PHGetSyncItemsNumber() > MAX_POSES)
			return nullptr;
		return holder;
	}

	static void poses_of(CPhysicsShellHolder* holder, Poses& poses)
	{
		const u16 count = holder->PHGetSyncItemsNumber();
		poses.resize(count);
		for (u16 i = 0; i < count; ++i)
		{
			SPHNetState state;
			holder->PHGetSyncItem(i)->get_State(state);
			poses[i].position = state.position;
			poses[i].rotation = state.quaternion;
		}
	}

	static bool moved(const Poses& now, const Poses& was)
	{
		if (now.size() != was.size())
			return true;
		const SSettings& s = settings();
		const float cos_half = _cos(deg2rad(s.turn) * 0.5f);
		for (u32 i = 0; i < now.size(); ++i)
		{
			if (now[i].position.distance_to(was[i].position) > s.move)
				return true;
			const Fquaternion& a = now[i].rotation;
			const Fquaternion& b = was[i].rotation;
			if (_abs(a.x * b.x + a.y * b.y + a.z * b.z + a.w * b.w) < cos_half)
				return true;
		}
		return false;
	}

	static void write_rest(NET_Packet& P, CPhysicsShellHolder* holder, const Poses& poses)
	{
		Fvector angle;
		holder->XFORM().getXYZ(angle);
		P.w_vec3(holder->Position());
		P.w_vec3(angle);
		P.w_u8(u8(poses.size()));
		for (const SPose& pose : poses)
		{
			P.w_vec3(pose.position);
			P.w_float(pose.rotation.x);
			P.w_float(pose.rotation.y);
			P.w_float(pose.rotation.z);
			P.w_float(pose.rotation.w);
		}
	}

	static void read_rest(NET_Packet& P, SRest& rest)
	{
		P.r_vec3(rest.position);
		P.r_vec3(rest.angle);
		rest.poses.resize(P.r_u8());
		for (SPose& pose : rest.poses)
		{
			P.r_vec3(pose.position);
			pose.rotation.x = P.r_float();
			pose.rotation.y = P.r_float();
			pose.rotation.z = P.r_float();
			pose.rotation.w = P.r_float();
		}
	}

	static void send_rest(u16 id, const shared_str& section, bool word, CPhysicsShellHolder* holder, const Poses& poses)
	{
		NET_Packet P;
		P.w_begin(M_ACTOR_ACTION);
		P.w_u8(ePropRest);
		P.w_u8(word ? 1 : 0); // the level's authority's: the world's word
		P.w_u16(id);
		P.w_stringZ(section);
		write_rest(P, holder, poses);
		send(P);
		if (debug_mode)
			Msg("[coop dbg] %s (id=%u) lies still at [%.2f %.2f %.2f]: sent%s", section.c_str(), id, holder->Position().x,
			    holder->Position().y, holder->Position().z, word ? ", the world's" : ", for the level's authority");
	}

	// the thing online here where the world has it; it wakes, and settles there
	static bool put_online(CPhysicsShellHolder* holder, const Poses& poses)
	{
		if (poses.size() != holder->PHGetSyncItemsNumber())
			return false;
		for (u16 i = 0; i < poses.size(); ++i)
		{
			SPHNetState state;
			holder->PHGetSyncItem(i)->get_State(state);
			state.position = state.previous_position = poses[i].position;
			state.quaternion = state.previous_quaternion = poses[i].rotation;
			state.linear_vel.set(0.f, 0.f, 0.f);
			state.angular_vel.set(0.f, 0.f, 0.f);
			state.force.set(0.f, 0.f, 0.f);
			state.torque.set(0.f, 0.f, 0.f);
			state.enabled = true;
			holder->PHGetSyncItem(i)->set_State(state);
		}
		SProp& prop = g_props[holder->ID()];
		prop.agreed = poses;
		prop.known = true;
		prop.awake = true;
		prop.settling = true; // a thing that can't lie still there doesn't go back and forth between the games
		return true;
	}

	static shared_str level_of(CSE_ALifeDynamicObject* object)
	{
		const CGameGraph& graph = ai().game_graph();
		if (!graph.valid_vertex_id(object->m_tGraphID))
			return shared_str();
		return graph.header().level(graph.vertex(object->m_tGraphID)->level_id()).name();
	}

	// offline here: its server entity; the world's save keeps it so (the host)
	static void put_offline(CSE_ALifeDynamicObject* object, const SRest& rest)
	{
		CSE_ALifeObjectPhysic* physic = smart_cast<CSE_ALifeObjectPhysic*>(object);
		if (physic)
		{
			// as CPHSkeleton::SaveNetState keeps a thing going offline: its elements, put back when it comes online
			physic->saved_bones.bones.clear();
			for (const SPose& pose : rest.poses)
			{
				SPHNetState state;
				ZeroMemory(&state, sizeof(state));
				state.position = state.previous_position = pose.position;
				state.quaternion = state.previous_quaternion = pose.rotation;
				state.enabled = false;
				physic->saved_bones.bones.push_back(state);
			}
			physic->_flags.set(CSE_PHSkeleton::flSavedData, TRUE);
		}
		else
			g_pending[object->ID] = rest; // an item: what it saved of itself going offline here would put it back

		object->o_Angle = rest.angle;
		if (g_pGameLevel && level_of(object) == Level().name() && ai().get_level_graph())
		{
			const u32 vertex = ai().level_graph().vertex_id(rest.position);
			if (ai().level_graph().valid_vertex_id(vertex))
			{
				alife_rw().teleport_object(object->ID, ai().cross_table().vertex(vertex).game_vertex_id(), vertex, rest.position);
				return;
			}
		}
		object->o_Position = rest.position;
	}

	void apply_prop_rest(u32 sender, NET_Packet& P)
	{
		const bool word = P.r_u8() != 0;
		const u16 id = P.r_u16();
		shared_str section;
		P.r_stringZ(section);
		SRest rest;
		read_rest(P, rest);
		if (!world_ready() || rest.poses.empty())
			return;

		CSE_ALifeDynamicObject* object = ai().alife().objects().object(id, true);
		if (!object || object->s_name != section || object->ID_Parent != u16(-1) ||
		    (!smart_cast<CSE_ALifeObjectPhysic*>(object) && !smart_cast<CSE_ALifeInventoryItem*>(object)))
			return;
		CPhysicsShellHolder* holder = object->m_bOnline ? prop_of(Level().Objects.net_Find(id)) : nullptr;
		if (object->m_bOnline && !holder)
			return; // online here but not a thing we keep (yet made, or carried)
		const bool moving = holder && holder->PPhysicsShell()->isEnabled();

		if (!word)
		{
			// another game's rest: the level's authority takes it, while its copy lies still, and gives it as the world's
			if (moving || !is_authority(level_of(object)))
				return;
			if (holder)
			{
				if (!put_online(holder, rest.poses))
					return;
			}
			else
				put_offline(object, rest);
			NET_Packet W;
			W.w_begin(M_ACTOR_ACTION);
			W.w_u8(ePropRest);
			W.w_u8(1);
			W.w_u16(id);
			W.w_stringZ(section);
			W.w_vec3(rest.position);
			W.w_vec3(rest.angle);
			W.w_u8(u8(rest.poses.size()));
			for (const SPose& pose : rest.poses)
			{
				W.w_vec3(pose.position);
				W.w_float(pose.rotation.x);
				W.w_float(pose.rotation.y);
				W.w_float(pose.rotation.z);
				W.w_float(pose.rotation.w);
			}
			send(W);
			if (debug_mode)
				Msg("[coop dbg] %s (id=%u): '%s' put it at [%.2f %.2f %.2f], the world's now", section.c_str(), id,
				    *player_name(sender) ? player_name(sender) : "?", rest.position.x, rest.position.y, rest.position.z);
			return;
		}

		// the world's word; a copy moving here (ours being pushed, carried) gives its own rest when it lies still
		if (moving)
			return;
		if (holder)
			put_online(holder, rest.poses);
		else
			put_offline(object, rest);
		if (debug_mode)
			Msg("[coop dbg] %s (id=%u) put where the world has it", section.c_str(), id);
	}

	void update_props()
	{
		static u32 last = 0;
		static u32 scan = 0;
		if (!is_connected() || !world_ready())
			return;
		if (g_world != ai().get_alife())
		{
			g_world = ai().get_alife();
			g_pending.clear();
			g_theirs.clear();
			g_moved.clear();
			g_by_logic.clear();
		}
		if (g_level != g_pGameLevel)
		{
			g_level = g_pGameLevel;
			g_props.clear();
		}
		const SSettings& s = settings();
		if (Device.dwTimeContinual - last < s.check_ms)
			return;
		last = Device.dwTimeContinual;
		++scan;
		const bool word = is_authority(Level().name());

		for (u32 i = 0, n = Level().Objects.o_count(); i < n; ++i)
		{
			CPhysicsShellHolder* holder = prop_of(Level().Objects.o_get_by_iterator(i));
			if (!holder)
				continue;
			const u16 id = holder->ID();
			if (is_local_object(id) || is_by_logic(id))
				continue;
			CSE_ALifeDynamicObject* object = ai().alife().objects().object(id, true);
			if (!object)
				continue;
			SProp& prop = g_props[id];
			prop.seen = scan;

			auto pending = g_pending.find(id);
			if (pending != g_pending.end())
			{
				put_online(holder, pending->second.poses); // the world's place, which came while it was offline here
				g_pending.erase(pending);
				continue;
			}
			if (holder->PPhysicsShell()->isEnabled())
			{
				prop.awake = true;
				continue;
			}
			if (!prop.known)
			{
				// its first rest since it came online here: as the world's, unless we moved it
				poses_of(holder, prop.agreed);
				prop.known = true;
				prop.awake = false;
				if (g_moved.erase(id))
				{
					prop.sent = Device.dwTimeContinual;
					send_rest(id, holder->cNameSect(), word, holder, prop.agreed);
				}
				continue;
			}
			if (!prop.awake)
				continue;
			Poses now;
			poses_of(holder, now);
			if (prop.settling)
			{
				prop.settling = false;
				prop.awake = false;
				prop.agreed = now;
				continue;
			}
			const bool ours = g_moved.count(id) > 0;
			if (!ours && !moved(now, prop.agreed))
			{
				prop.awake = false;
				continue;
			}
			if (Device.dwTimeContinual - prop.sent < s.min_gap_ms)
				continue; // again on the next look
			prop.awake = false;
			g_moved.erase(id);
			prop.agreed = now;
			prop.sent = Device.dwTimeContinual;
			send_rest(id, holder->cNameSect(), word, holder, now);
		}
		for (auto it = g_props.begin(); it != g_props.end();)
			it = it->second.seen != scan ? g_props.erase(it) : std::next(it);
		// things gone from the world meanwhile (used up, destroyed)
		for (xr_set<u16>* ids : {&g_moved, &g_theirs})
			for (auto it = ids->begin(); it != ids->end();)
				it = ai().alife().objects().object(*it, true) ? std::next(it) : ids->erase(it);
	}

	void on_glass_broken(CBreakableObject& glass)
	{
		if (!is_connected() || !world_ready() || is_local_object(glass.ID()))
			return;
		NET_Packet P;
		P.w_begin(M_ACTOR_ACTION);
		P.w_u8(eGlassBreak);
		P.w_u16(glass.ID());
		P.w_stringZ(glass.cNameSect());
		send(P);
		if (debug_mode)
			Msg("[coop dbg] glass %s (id=%u) broken here: sent", glass.cName().c_str(), glass.ID());
	}

	void apply_glass_break(NET_Packet& P)
	{
		const u16 id = P.r_u16();
		shared_str section;
		P.r_stringZ(section);
		if (!world_ready())
			return;
		CBreakableObject* glass = smart_cast<CBreakableObject*>(Level().Objects.net_Find(id));
		if (!glass || glass->getDestroy() || glass->cNameSect() != section)
			return; // offline here: its release comes
		release_theirs(id);
		glass->CoopBreak();
	}
}
