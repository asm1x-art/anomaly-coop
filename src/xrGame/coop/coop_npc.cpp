#include "stdafx.h"
#include "coop_npc.h"
#include "coop_net.h"
#include "coop_puppet.h"
#include "coop_combat.h"
#include "coop_world.h"
#include "Level.h"
#include "ai/stalker/ai_stalker.h"
#include "ai/monsters/basemonster/base_monster.h"
#include "stalker_movement_manager_smart_cover.h"
#include "sight_manager.h"
#include "sound_player.h"
#include "CharacterPhysicsSupport.h"
#include "PHMovementControl.h"
#include "Inventory.h"
#include "inventory_item.h"
#include "WeaponMagazined.h"
#include "ai_space.h"
#include "alife_simulator.h"
#include "alife_object_registry.h"
#include "level_graph.h"
#include "game_level_cross_table.h"
#include "xrServer_Objects_ALife_Monsters.h"
#include "../Include/xrRender/KinematicsAnimated.h"

namespace coop
{
	static const u32 SEND_INTERVAL_MS = 100;
	static const u32 FRESH_MS = 500;        // a state older than this: the authority no longer has that NPC online
	static const u32 BRING_RETRY_MS = 3000; // how often an NPC the authority has and we don't is moved to it
	static const u32 MAX_PER_PACKET = 100;
	static const u32 MAX_PARTS = 4;         // bone partitions streamed (stalkers have legs, torso, head)
	static const u32 NO_MOTION = u32(-1);
	static const u16 NO_ITEM = u16(-1);
	static const float SNAP_DISTANCE = 5.f;
	static const float FOLLOW_RATE = 12.f;

	struct SNpcState
	{
		Fvector position;
		float heading;     // the model's: XFORM is rotateY(heading)
		SRotation body;    // movement().m_body.current
		SRotation head;    // a stalker's movement().m_head.current
		float health;      // so whoever runs the level next has it as wounded as it is
		bool aims;         // a stalker: how its spine, shoulders and head turn to its target (sight manager)
		bool sight_enabled;
		Fquaternion aim[3]; // spine, shoulder, head
		u32 motions[MAX_PARTS]; // MotionID::val of the strongest blend per partition: the same model everywhere
		float times[MAX_PARTS];  // how far into it, s: a monster plays one motion again and again from its start
		u16 active_item;
		u32 received;      // Device.dwTimeContinual
	};

	struct SNpcPuppet
	{
		bool placed = false;
		Fvector position;
		float heading;
		Fquaternion aim[3];
		u32 replays = 0; // motions (re)started since the last coop_debug line
		u32 drives = 0;  // frames it was driven since then
	};

	static xr_map<u16, SNpcState> g_states;  // from the authority of our level, by NPC id
	static xr_map<u16, SNpcPuppet> g_puppets;
	static xr_set<u16> g_hidden;             // ours, not online in the authority's game
	static xr_map<u16, u32> g_brought;       // id -> when we last moved it to where the authority has it
	static bool g_puppet_level = false;      // puppet_level() as last seen, to notice it end
	static u32 g_last_send = 0;
	static bool g_remote_sound = false;      // playing a sound the authority sent
	static u32 g_last_stream = 0;            // when the authority's states last came

	static CALifeSimulator& alife_rw()
	{
		return const_cast<CALifeSimulator&>(ai().alife());
	}

	static bool others_on_our_level()
	{
		const shared_str& level = Level().name();
		for (const auto& [id, peer] : peers())
			if (peer.level == level)
				return true;
		return false;
	}

	// the NPCs a game shows the authority's: stalkers and mutants, not players' stand-ins
	static CCustomMonster* as_npc(CObject* object)
	{
		CCustomMonster* npc = smart_cast<CCustomMonster*>(object);
		return npc && !is_proxy(npc) && (smart_cast<CAI_Stalker*>(npc) || smart_cast<CBaseMonster*>(npc)) ? npc : nullptr;
	}

	static bool fresh(const SNpcState& state)
	{
		return Device.dwTimeContinual - state.received < FRESH_MS;
	}

	// another player runs our level: its NPCs are puppets here. Known from the level's first update on
	// (where the players are came while we were in the menu), so none of ours ever starts thinking.
	static bool puppet_level()
	{
		return is_connected() && g_pGameLevel && !is_authority(Level().name()) && others_on_our_level();
	}

	bool is_npc_puppet(const CCustomMonster* npc)
	{
		if (is_proxy(npc))
			return true; // a stand-in never thinks
		return npc->g_Alive() && as_npc(const_cast<CCustomMonster*>(npc)) && puppet_level();
	}

	// the other players on our level while we are its authority, as of this frame (update_npc_sync)
	static xr_vector<Fvector> g_others_here;

	float distance_to_others(const CCustomMonster* npc)
	{
		float distance = flt_max;
		if (is_connected())
			for (const Fvector& position : g_others_here)
				distance = _min(distance, position.distance_to(npc->Position()));
		return distance;
	}

	float distance_to_players(const Fvector& actor_position, const Fvector& position)
	{
		float distance = actor_position.distance_to(position);
		if (is_connected() && g_pGameLevel)
		{
			const shared_str& level = Level().name();
			for (const auto& [id, peer] : peers())
				if (peer.level == level)
					distance = _min(distance, peer.position.distance_to(position));
		}
		return distance;
	}

	// a motion id from the authority's game is ours only while both run the same world with the same models
	static bool has_motion(IKinematicsAnimated* K, MotionID motion)
	{
		if (motion.slot >= K->LL_MotionsSlotCount())
			return false;
		shared_motions& slot = const_cast<shared_motions&>(K->LL_MotionsSlot(motion.slot));
		return motion.idx < slot.motion_defs()->size();
	}

	static bool fading(const CBlend* blend)
	{
		return blend->blend_state() == CBlend::eFalloff;
	}

	// the blend that plays a motion on a partition, if one does. Something else may have replaced the one we
	// started: its own animation manager while it was no puppet for a moment.
	static CBlend* playing(IKinematicsAnimated* K, u16 part, MotionID motion)
	{
		for (u32 i = 0, n = K->LL_PartBlendsCount(part); i < n; ++i)
		{
			CBlend* blend = K->LL_PartBlend(part, i);
			if (blend && blend->channel == 0 && blend->motionID.val == motion.val && !fading(blend))
				return blend;
		}
		return nullptr;
	}

	static const float MOTION_DRIFT = 0.2f; // s a puppet's motion may be off the authority's before it's set right

	// The puppet's motion where the authority's is, now: it began at authority_time when the state was sent,
	// age seconds ago. A monster plays a motion that stops at its end again from the start, the same motion;
	// and an attack shows when the authority's does.
	static void keep_time(CBlend& blend, float authority_time, float age)
	{
		if (blend.timeTotal <= 0.f)
			return;
		float expected = authority_time + age * blend.speed;
		expected = blend.stop_at_end ? _min(expected, blend.timeTotal) : fmodf(expected, blend.timeTotal);
		float off = _abs(blend.timeCurrent - expected);
		if (!blend.stop_at_end)
			off = _min(off, blend.timeTotal - off); // a loop: the short way round
		if (off <= MOTION_DRIFT)
			return;
		blend.timeCurrent = expected;
		if (expected < blend.timeTotal)
			blend.playing = TRUE;
	}

	bool drive_npc_puppet(CCustomMonster* npc, Fvector& position, float& model_yaw, SRotation& torso)
	{
		if (is_proxy(npc))
			return drive_proxy(npc, position, model_yaw, torso);
		if (!is_npc_puppet(npc))
			return false;

		auto it = g_states.find(npc->ID());
		if (it == g_states.end() || !fresh(it->second))
		{
			// nothing from the authority (yet): it stands as it is, thinking nothing
			if (IKinematicsAnimated* K = smart_cast<IKinematicsAnimated*>(npc->Visual()))
				K->UpdateTracks();
			position = npc->Position();
			const Fmatrix& X = npc->XFORM();
			model_yaw = atan2f(X.k.x, X.k.z);
			torso.yaw = model_yaw;
			torso.pitch = torso.roll = 0.f;
			return true;
		}
		const SNpcState& state = it->second;
		SNpcPuppet& puppet = g_puppets[npc->ID()];
		++puppet.drives;

		if (!puppet.placed || puppet.position.distance_to(state.position) > SNAP_DISTANCE)
		{
			puppet.position = state.position;
			puppet.heading = state.heading;
			for (u32 i = 0; i < 3; ++i)
				puppet.aim[i] = state.aim[i];
			puppet.placed = true;
		}
		const float k = _min(1.f, Device.fTimeDelta * FOLLOW_RATE);
		puppet.position.lerp(puppet.position, state.position, k);
		puppet.heading = angle_lerp(puppet.heading, state.heading, k);

		position = puppet.position;
		model_yaw = puppet.heading;
		torso.yaw = puppet.heading;
		torso.pitch = torso.roll = 0.f;
		npc->XFORM().rotateY(puppet.heading);
		npc->XFORM().translate_over(puppet.position);
		// the character capsule follows, or the player bumps into where it was
		if (CCharacterPhysicsSupport* physics = npc->character_physics_support())
			if (CPHMovementControl* control = physics->movement())
				control->SetPosition(puppet.position);

		npc->movement().m_body.current = npc->movement().m_body.target = state.body;
		npc->SetfHealth(state.health);
		if (CAI_Stalker* stalker = smart_cast<CAI_Stalker*>(npc))
		{
			stalker->movement().m_head.target = state.head; // its sight manager turns the head there
			if (state.aims)
			{
				// its bone callbacks turn spine, shoulders and head by these, as its own aiming would
				Fmatrix aim[3];
				for (u32 i = 0; i < 3; ++i)
				{
					puppet.aim[i].slerp(puppet.aim[i], state.aim[i], k);
					aim[i].rotation(puppet.aim[i]);
				}
				stalker->sight().coop_set_rotations(aim[0], aim[1], aim[2]);
				stalker->sight().enable(state.sight_enabled);
			}

			// its own trigger finger is off (no object handler): a burst it had started must end here,
			// the authority's shots come as eNpcShot
			if (CWeaponMagazined* weapon = smart_cast<CWeaponMagazined*>(stalker->inventory().ActiveItem()))
				if (weapon->GetState() == CWeapon::eFire || weapon->GetState() == CWeapon::eFire2)
					weapon->FireEnd();

			CInventoryItem* active = stalker->inventory().ActiveItem();
			const u16 active_id = active ? active->object().ID() : NO_ITEM;
			if (active_id != state.active_item)
			{
				CInventoryItem* item = state.active_item != NO_ITEM ?
					smart_cast<CInventoryItem*>(Level().Objects.net_Find(state.active_item)) : nullptr;
				if (!item)
					stalker->inventory().Activate(NO_ACTIVE_SLOT);
				else if (item->object().H_Parent() == stalker && item->CurrSlot() != NO_ACTIVE_SLOT)
					stalker->inventory().Activate(item->CurrSlot());
			}
		}

		if (IKinematicsAnimated* K = smart_cast<IKinematicsAnimated*>(npc->Visual()))
		{
			const u16 parts = u16(_min(u32(K->partitions().count()), MAX_PARTS));
			for (u16 part = 0; part < parts; ++part)
			{
				if (state.motions[part] == NO_MOTION)
					continue;
				MotionID motion;
				motion.val = state.motions[part];
				if (!has_motion(K, motion))
					continue;
				CBlend* blend = playing(K, part, motion);
				if (!blend)
				{
					// speed given: through IKinematicsAnimated it defaults to 0 (CKinematicsAnimated's to 1), and a
					// motion at speed 0 stands still on its first frame
					blend = K->PlayCycle(part, motion, TRUE, nullptr, nullptr, 0, 1.f);
					++puppet.replays;
				}
				if (blend)
					keep_time(*blend, state.times[part], float(Device.dwTimeContinual - state.received) / 1000.f);
			}
			// the NPC's own animation manager, which moves its motions on, is off
			K->UpdateTracks();
		}
		return true;
	}

	//------------------------------------------------------------------------------------------------
	// The authority's side

	// The motion a partition plays, for the puppets: channel 0 only (hit reactions, character_hit_animations,
	// go on top in other channels); one fading out loses to one coming in, the one the puppet is to play.
	static CBlend* sent_blend(IKinematicsAnimated* K, u32 part)
	{
		CBlend* strongest = nullptr;
		for (u32 i = 0, n = K->LL_PartBlendsCount(part); i < n; ++i)
		{
			CBlend* blend = K->LL_PartBlend(part, i);
			if (!blend || blend->channel != 0)
				continue;
			if (!strongest || (fading(strongest) && !fading(blend)) ||
			    (fading(strongest) == fading(blend) && blend->blendAmount > strongest->blendAmount))
				strongest = blend;
		}
		return strongest;
	}

	static u32 sent_motion(IKinematicsAnimated* K, u32 part)
	{
		const CBlend* blend = sent_blend(K, part);
		return blend ? blend->motionID.val : NO_MOTION;
	}

	static void write_state(NET_Packet& P, CCustomMonster* npc)
	{
		P.w_u16(npc->ID());
		P.w_vec3(npc->Position());
		const Fmatrix& X = npc->XFORM();
		P.w_float(atan2f(X.k.x, X.k.z));
		const SRotation& body = npc->movement().m_body.current;
		P.w_float(body.yaw);
		P.w_float(body.pitch);
		CAI_Stalker* stalker = smart_cast<CAI_Stalker*>(npc);
		const SRotation& head = stalker ? stalker->movement().m_head.current : body;
		P.w_float(head.yaw);
		P.w_float(head.pitch);
		P.w_float(npc->GetfHealth());
		P.w_u8(stalker ? 1 : 0);
		if (stalker)
		{
			P.w_u8(stalker->sight().enabled() ? 1 : 0);
			const Fmatrix* aim[] = {&stalker->sight().current_spine_rotation(),
			                        &stalker->sight().current_shoulder_rotation(),
			                        &stalker->sight().current_head_rotation()};
			for (const Fmatrix* m : aim)
			{
				Fquaternion q;
				q.set(*m);
				P.w_float(q.x);
				P.w_float(q.y);
				P.w_float(q.z);
				P.w_float(q.w);
			}
		}

		IKinematicsAnimated* K = smart_cast<IKinematicsAnimated*>(npc->Visual());
		const u32 parts = K ? _min(u32(K->partitions().count()), MAX_PARTS) : 0;
		P.w_u8(u8(parts));
		for (u32 part = 0; part < parts; ++part)
		{
			const CBlend* blend = sent_blend(K, part);
			P.w_u32(blend ? blend->motionID.val : NO_MOTION);
			P.w_float(blend ? blend->timeCurrent : 0.f);
		}

		CInventoryItem* active = stalker ? stalker->inventory().ActiveItem() : nullptr;
		P.w_u16(active ? active->object().ID() : NO_ITEM);
	}

	static void send_states()
	{
		if (Device.dwTimeContinual - g_last_send < SEND_INTERVAL_MS)
			return;
		g_last_send = Device.dwTimeContinual;

		xr_vector<CCustomMonster*> npcs;
		for (u32 i = 0, n = Level().Objects.o_count(); i < n; ++i)
		{
			CCustomMonster* npc = as_npc(Level().Objects.o_get_by_iterator(i));
			if (npc && npc->g_Alive() && !npc->getDestroy())
				npcs.push_back(npc);
		}

		for (u32 first = 0; first < npcs.size(); first += MAX_PER_PACKET)
		{
			const u32 count = _min(MAX_PER_PACKET, u32(npcs.size()) - first);
			NET_Packet P;
			P.w_begin(M_NPC_STATES);
			P.w_stringZ(Level().name());
			P.w_u16(u16(count));
			for (u32 i = 0; i < count; ++i)
				write_state(P, npcs[first + i]);
			send(P);
		}
	}

	void on_npc_shot(const CWeapon& weapon)
	{
		const CAI_Stalker* stalker = smart_cast<const CAI_Stalker*>(weapon.H_Parent());
		if (!stalker || !is_connected() || !g_pGameLevel || !is_authority(Level().name()))
			return;
		NET_Packet P;
		P.w_begin(M_ACTOR_ACTION);
		P.w_u8(eNpcShot);
		P.w_u16(stalker->ID());
		send(P);
	}

	//------------------------------------------------------------------------------------------------
	// Everybody else's side

	void on_npc_states(u32 sender, NET_Packet& P)
	{
		shared_str level;
		P.r_stringZ(level);
		// only the authority of a level sends; we may have been it a moment ago
		if (!g_pGameLevel || level != Level().name() || is_authority(level))
			return;

		g_last_stream = Device.dwTimeContinual;
		const u16 count = P.r_u16();
		for (u16 i = 0; i < count; ++i)
		{
			const u16 id = P.r_u16();
			SNpcState& state = g_states[id];
			P.r_vec3(state.position);
			state.heading = P.r_float();
			state.body.yaw = P.r_float();
			state.body.pitch = P.r_float();
			state.body.roll = 0.f;
			state.head.yaw = P.r_float();
			state.head.pitch = P.r_float();
			state.head.roll = 0.f;
			state.health = P.r_float();
			state.aims = !!P.r_u8();
			if (state.aims)
			{
				state.sight_enabled = !!P.r_u8();
				for (Fquaternion& q : state.aim)
				{
					q.x = P.r_float();
					q.y = P.r_float();
					q.z = P.r_float();
					q.w = P.r_float();
				}
			}
			const u8 parts = P.r_u8();
			for (u32 part = 0; part < MAX_PARTS; ++part)
			{
				state.motions[part] = part < parts ? P.r_u32() : NO_MOTION;
				state.times[part] = part < parts ? P.r_float() : 0.f;
			}
			state.active_item = P.r_u16();
			state.received = Device.dwTimeContinual;
		}
	}

	static void set_hidden(CCustomMonster* npc, bool hidden)
	{
		if (hidden == !!g_hidden.count(npc->ID()))
			return;
		if (hidden)
			g_hidden.insert(npc->ID());
		else
			g_hidden.erase(npc->ID());
		npc->setVisible(!hidden);
		npc->setEnabled(!hidden); // bullets pass
	}

	// The authority has it online and we don't: it is somewhere else in our A-Life (squads move apart
	// offline in each game). Its squad goes where the authority has it; our A-Life brings it online.
	static void bring_online(u16 id, const SNpcState& state)
	{
		u32& last = g_brought[id];
		if (last && Device.dwTimeContinual - last < BRING_RETRY_MS)
			return;
		last = Device.dwTimeContinual;

		CSE_ALifeDynamicObject* object = ai().alife().objects().object(id, true);
		CSE_ALifeMonsterAbstract* monster = smart_cast<CSE_ALifeMonsterAbstract*>(object);
		if (!monster || object->m_bOnline || !monster->g_Alive())
			return; // not a creature we have, or dead here (a death not heard of?)

		u32 level_vertex = ai().level_graph().vertex_id(state.position);
		if (!ai().level_graph().valid_vertex_id(level_vertex))
			level_vertex = ai().level_graph().vertex(u32(-1), state.position); // off the AI grid: the nearest
		const GameGraph::_GRAPH_ID game_vertex = ai().cross_table().vertex(level_vertex).game_vertex_id();

		CSE_ALifeOnlineOfflineGroup* squad = monster->m_group_id != ALife::_OBJECT_ID(-1) ?
			smart_cast<CSE_ALifeOnlineOfflineGroup*>(ai().alife().objects().object(monster->m_group_id, true)) : nullptr;
		if (squad)
		{
			if (squad->m_bOnline)
				return; // the squad is here, this member not (yet)
			alife_rw().teleport_object(squad->ID, game_vertex, level_vertex, state.position);
			for (const auto& member : squad->squad_members())
				alife_rw().teleport_object(member.first, game_vertex, level_vertex, state.position);
		}
		else
			alife_rw().teleport_object(id, game_vertex, level_vertex, state.position);
		Msg("[coop] %s (id=%u) is online for the level's authority: moved here", object->name_replace(), id);
	}

	static void mirror_authority()
	{
		static u32 last = 0; // a walk over every object on the level: not every frame
		if (Device.dwTimeContinual - last < SEND_INTERVAL_MS)
			return;
		last = Device.dwTimeContinual;
		const bool stream = Device.dwTimeContinual - g_last_stream < FRESH_MS;
		for (u32 i = 0, n = Level().Objects.o_count(); i < n; ++i)
		{
			CCustomMonster* npc = as_npc(Level().Objects.o_get_by_iterator(i));
			if (!npc)
				continue;
			if (!npc->g_Alive())
			{
				set_hidden(npc, false); // the authority sends no state of the dead: a body is seen where it fell
				continue;
			}
			auto it = g_states.find(npc->ID());
			// ours and not online for the authority: not in its world right now
			set_hidden(npc, stream && (it == g_states.end() || !fresh(it->second)));
		}

		for (const auto& [id, state] : g_states)
			if (fresh(state) && !Level().Objects.net_Find(id))
				bring_online(id, state);
	}

	static void show_all()
	{
		for (u16 id : g_hidden)
			if (CObject* object = g_pGameLevel ? Level().Objects.net_Find(id) : nullptr)
			{
				object->setVisible(TRUE);
				object->setEnabled(TRUE);
			}
		g_hidden.clear();
	}

	// coop_debug 1: once a second, the NPC nearest to our actor as this game has it - a puppet or ours,
	// how old the authority's last state of it is, the motions it sends or sent, how many motions the puppet
	// (re)started meanwhile and the blends on its model (part:motion, a coming in / f fading out, amount)
	static void debug_nearest_npc()
	{
		static u32 last = 0;
		if (!debug_mode || !g_actor || Device.dwTimeContinual - last < 1000)
			return;
		last = Device.dwTimeContinual;
		CCustomMonster* nearest = nullptr;
		float best = 30.f;
		for (u32 i = 0, n = Level().Objects.o_count(); i < n; ++i)
		{
			CCustomMonster* npc = as_npc(Level().Objects.o_get_by_iterator(i));
			const float distance = npc && npc->g_Alive() ? npc->Position().distance_to(g_actor->Position()) : best;
			if (distance < best)
			{
				best = distance;
				nearest = npc;
			}
		}
		IKinematicsAnimated* K = nearest ? smart_cast<IKinematicsAnimated*>(nearest->Visual()) : nullptr;
		if (!K)
			return;
		const bool puppet = is_npc_puppet(nearest);
		u32 motions[MAX_PARTS];
		xr_string blends;
		for (u32 part = 0; part < MAX_PARTS; ++part)
		{
			motions[part] = part < K->partitions().count() ? sent_motion(K, part) : NO_MOTION;
			for (u32 i = 0, n = part < K->partitions().count() ? K->LL_PartBlendsCount(part) : 0; i < n; ++i)
				if (const CBlend* blend = K->LL_PartBlend(part, i))
				{
					string128 one;
					xr_sprintf(one, "%u:%x/c%u%s%.2f t%.2f/%.2f x%.2f%s ", part, blend->motionID.val, blend->channel,
					           fading(blend) ? "f" : "a", blend->blendAmount, blend->timeCurrent, blend->timeTotal,
					           blend->speed, blend->playing ? "" : " stopped");
					blends += one;
				}
		}
		int age = -1;
		auto state = g_states.find(nearest->ID());
		if (puppet && state != g_states.end())
		{
			age = int(Device.dwTimeContinual - state->second.received);
			for (u32 part = 0; part < MAX_PARTS; ++part)
				motions[part] = state->second.motions[part];
		}
		auto it = g_puppets.find(nearest->ID());
		const u32 replays = it != g_puppets.end() ? it->second.replays : 0;
		const u32 drives = it != g_puppets.end() ? it->second.drives : 0;
		if (it != g_puppets.end())
			it->second.replays = it->second.drives = 0;
		Msg("[coop npc] %s (id=%u, %.0f m) %s, %.0f fps, %u driven, state %d ms old, motions %x %x %x %x, %u restarted | %s",
		    nearest->cName().c_str(), nearest->ID(), best, puppet ? "puppet" : "ours", 1.f / _max(Device.fTimeDelta, EPS_S),
		    drives, age, motions[0], motions[1], motions[2], motions[3], replays, blends.c_str());
	}

	void update_npc_sync()
	{
		g_others_here.clear();
		if (world_ready())
			debug_nearest_npc();
		const bool puppets = puppet_level();
		if (g_puppet_level && !puppets)
		{
			// our NPCs think for themselves again
			show_all();
			g_states.clear();
			g_puppets.clear();
		}
		g_puppet_level = puppets;

		if (!world_ready() || !is_connected())
			return;
		if (puppets)
			mirror_authority();
		else if (is_authority(Level().name()) && others_on_our_level())
		{
			for (const auto& [id, peer] : peers())
				if (peer.level == Level().name())
					g_others_here.push_back(peer.position);
			send_states();
		}
	}

	void play_npc_shot(u16 npc_id)
	{
		CAI_Stalker* stalker = g_pGameLevel ? smart_cast<CAI_Stalker*>(Level().Objects.net_Find(npc_id)) : nullptr;
		if (!stalker || !is_npc_puppet(stalker))
			return;
		if (CWeaponMagazined* weapon = smart_cast<CWeaponMagazined*>(stalker->inventory().ActiveItem()))
			weapon->coop_shot_fx();
	}

	void on_hit_motion(CEntityAlive& npc, const Fvector& dir, const Fvector& bone_position, u16 bone)
	{
		if (!is_connected() || !g_pGameLevel || !as_npc(&npc) || !is_authority(Level().name()) || !others_on_our_level())
			return;
		NET_Packet P;
		P.w_begin(M_ACTOR_ACTION);
		P.w_u8(eNpcHit);
		P.w_u16(npc.ID());
		P.w_vec3(dir);
		P.w_vec3(bone_position);
		P.w_u16(bone);
		send(P);
	}

	void play_npc_hit(NET_Packet& P)
	{
		const u16 id = P.r_u16();
		Fvector dir, bone_position;
		P.r_vec3(dir);
		P.r_vec3(bone_position);
		const u16 bone = P.r_u16();
		CCustomMonster* npc = g_pGameLevel ? smart_cast<CCustomMonster*>(Level().Objects.net_Find(id)) : nullptr;
		if (npc && is_npc_puppet(npc))
			if (CCharacterPhysicsSupport* physics = npc->character_physics_support())
				physics->play_hit_motion(dir, bone_position, bone);
	}

	// the level's NPCs as another game runs them: what they say comes from there, dying ones too
	static bool mirrored(const CObject* object)
	{
		return as_npc(const_cast<CObject*>(object)) && puppet_level();
	}

	bool mute_npc_sound(const CObject* object)
	{
		return !g_remote_sound && object && mirrored(object);
	}

	void on_npc_sound(CObject* object, u32 type, u32 index, u32 delay)
	{
		if (g_remote_sound || !is_connected() || !g_pGameLevel || !as_npc(object) || !is_authority(Level().name()) ||
		    !others_on_our_level())
			return;
		NET_Packet P;
		P.w_begin(M_ACTOR_ACTION);
		P.w_u8(eNpcSound);
		P.w_u16(object->ID());
		P.w_u32(type);
		P.w_u16(u16(index));
		P.w_u32(delay);
		send(P);
	}

	void play_npc_sound(NET_Packet& P)
	{
		const u16 id = P.r_u16();
		const u32 type = P.r_u32();
		const u16 index = P.r_u16();
		const u32 delay = P.r_u32();
		CCustomMonster* npc = g_pGameLevel ? smart_cast<CCustomMonster*>(Level().Objects.net_Find(id)) : nullptr;
		if (!npc || !mirrored(npc))
			return;
		g_remote_sound = true;
		npc->sound().play(type, delay, delay, 0, 0, index);
		g_remote_sound = false;
	}

	// a reload: drawing and holstering a puppet does itself, as its active item follows the stream
	void on_npc_weapon_state(const CWeapon& weapon, u32 state)
	{
		CObject* holder = const_cast<CObject*>(weapon.H_Parent());
		if (state != CWeapon::eReload || !holder || !is_connected() || !g_pGameLevel || !as_npc(holder) ||
		    !is_authority(Level().name()) || !others_on_our_level())
			return;
		NET_Packet P;
		P.w_begin(M_ACTOR_ACTION);
		P.w_u8(eNpcWeaponState);
		P.w_u16(holder->ID());
		P.w_u8(u8(state));
		send(P);
	}

	void play_npc_weapon_state(NET_Packet& P)
	{
		const u16 id = P.r_u16();
		const u8 state = P.r_u8();
		CAI_Stalker* stalker = g_pGameLevel ? smart_cast<CAI_Stalker*>(Level().Objects.net_Find(id)) : nullptr;
		if (!stalker || !is_npc_puppet(stalker))
			return;
		if (CWeaponMagazined* weapon = smart_cast<CWeaponMagazined*>(stalker->inventory().ActiveItem()))
			weapon->coop_state_sound(state);
	}

	void clear_npc_sync()
	{
		show_all();
		g_states.clear();
		g_puppets.clear();
		g_brought.clear();
		g_puppet_level = false;
	}
}
