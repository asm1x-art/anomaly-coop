#include "stdafx.h"
#include "coop_combat.h"
#include "coop_net.h"
#include "coop_npc.h"
#include "coop_puppet.h"
#include "coop_world.h"
#include "coop_save.h"
#include "Level.h"
#include "Level_Bullet_Manager.h"
#include "Actor.h"
#include "Hit.h"
#include "CustomMonster.h"
#include "ai/stalker/ai_stalker.h"
#include "memory_manager.h"
#include "enemy_manager.h"
#include "CharacterPhysicsSupport.h"
#include "PHMovementControl.h"
#include "InventoryOwner.h"
#include "Inventory.h"
#include "inventory_item.h"
#include "Weapon.h"
#include "WeaponAmmo.h"
#include "character_community.h"
#include "relation_registry.h"
#include "ai_space.h"
#include "script_engine.h"
#include "level_graph.h"
#include "alife_simulator.h"
#include "alife_object_registry.h"
#include "xrServer_Objects.h"
#include "xrServer_Objects_ALife_Monsters.h"
#include "../Include/xrRender/Kinematics.h"
#include "../Include/xrRender/KinematicsAnimated.h"

namespace coop
{
	static LPCSTR PROXY_SECTION = "coop_proxy"; // gamedata/configs/mod_system_coop.ltx
	static const u32 SPAWN_RETRY_MS = 3000;
	static const u16 NO_OBJECT = u16(-1);
	static const u16 NO_MOTION = u16(-1);
	static const float SNAP_DISTANCE = 5.f;
	static const float FOLLOW_RATE = 12.f;

	enum EHitKind : u8
	{
		eHitNpc,    // u32 NPC id, SHit: our player hit an NPC another game runs
		eHitPlayer, // u32 peer id, SHit: a player's stand-in was hit here
		eGrudge,    // u32 squad (or squadless NPC) id, u32 peer id: it holds a grudge against that player
		eFallen,    // u32 the sender's peer id: their player fell (lying wounded, back at the save point)
	};

	struct SProxy
	{
		u16 object = NO_OBJECT;
		u32 spawned = 0;
		shared_str community;
		bool placed = false;
		Fvector position;
		float heading = 0.f;
		u16 legs = NO_MOTION, torso = NO_MOTION, head = NO_MOTION; // the player's motions it plays
		u8 torso_seq = 0;
		bool named = false; // shows the player's name when looked at
	};

	struct SActorHit
	{
		u16 key;           // its grudge key, taken before a death takes it out of its squad
		bool was_hostile;
		bool accidental;   // in a shared fight, as vanilla's danger scheme has it
	};

	static xr_map<u32, SProxy> g_proxies; // peer id -> its stand-in here
	static u32 g_last_orphan_check = 0;
	static xr_set<std::pair<u16, u32>> g_grudges; // (squad id, or a squadless NPC's own; peer id)
	static xr_map<u32, shared_str> g_grudged_on;  // player -> the level they were on then: leaving it, all is forgiven
	static xr_map<u16, SActorHit> g_actor_hits;   // NPC id: our actor hit it lately

	// _G.<name>(args...) when Lua has it
	template <typename... Args>
	static void call_lua(LPCSTR name, Args... args)
	{
		::luabind::functor<void> handler;
		if (ai().script_engine().functor(name, handler))
			handler(args...);
	}

	bool is_proxy(const CObject* object)
	{
		return object && !xr_strcmp(object->cNameSect(), PROXY_SECTION);
	}

	static u32 peer_of_proxy(u16 object)
	{
		for (const auto& [peer, proxy] : g_proxies)
			if (proxy.object == object)
				return peer;
		return u32(-1);
	}

	u32 peer_of_stand_in(u16 object)
	{
		const u32 peer = peer_of_proxy(object);
		return peer == u32(-1) ? 0 : peer;
	}

	bool stand_in_luminocity(const CObject* object, float& luminocity)
	{
		if (!is_proxy(object))
			return false;
		auto it = peers().find(peer_of_proxy(object->ID()));
		luminocity = it != peers().end() && it->second.has_look ? it->second.look.luminocity / 255.f : 1.f;
		return true;
	}

	u16 stand_in_of(u32 peer)
	{
		auto it = g_proxies.find(peer);
		return it != g_proxies.end() && it->second.object != NO_OBJECT ? it->second.object : 0;
	}

	static CGameObject* proxy_of_peer(u32 peer)
	{
		auto it = g_proxies.find(peer);
		if (it == g_proxies.end() || it->second.object == NO_OBJECT)
			return nullptr;
		return smart_cast<CGameObject*>(Level().Objects.net_Find(it->second.object));
	}

	static void proxy_name(u32 peer, string64& name)
	{
		xr_sprintf(name, "coop_proxy_%u", peer);
	}

	static void spawn_proxy(u32 peer_id, const SPeer& peer)
	{
		// a player stands where NPCs never walk as often as not (inside, up on things): the nearest vertex then
		u32 level_vertex = ai().level_graph().vertex_id(peer.position);
		if (!ai().level_graph().valid_vertex_id(level_vertex))
			level_vertex = ai().level_graph().vertex(u32(-1), peer.position);
		CSE_Abstract* abstract = Level().spawn_item(PROXY_SECTION, peer.position, level_vertex, 0xffff, true);
		string64 name;
		proxy_name(peer_id, name);
		abstract->set_name_replace(name);
		NET_Packet P;
		abstract->Spawn_Write(P, TRUE);
		Level().Send(P, net_flags(TRUE));
		F_entity_Destroy(abstract);
		Msg("[coop] stand-in for '%s' spawned", peer.name.c_str());
	}

	static u16 find_proxy_object(u32 peer)
	{
		string64 name;
		proxy_name(peer, name);
		for (u32 i = 0, n = Level().Objects.o_count(); i < n; ++i)
		{
			CObject* object = Level().Objects.o_get_by_iterator(i);
			if (is_proxy(object) && !xr_strcmp(object->cName(), name) && !object->getDestroy())
				return object->ID();
		}
		return NO_OBJECT;
	}

	// the stand-in is of the player's faction: "actor_dolg" plays as "dolg"
	static void set_community(CObject* object, const shared_str& actor_community)
	{
		LPCSTR name = *actor_community;
		if (!name)
			return;
		if (!strncmp(name, "actor_", 6))
			name += 6;
		CHARACTER_COMMUNITY community;
		community.set(name);
		CInventoryOwner* owner = smart_cast<CInventoryOwner*>(object);
		CEntity* entity = smart_cast<CEntity*>(object);
		if (community.index() < 0 || !owner || !entity)
			return;
		owner->SetCommunity(community.index());
		entity->ChangeTeam(community.team(), 0, 0);
	}

	// stand-ins of players gone (a reconnect gives a new id) stay on the level, frozen and unseen: remove them
	static void remove_orphans()
	{
		if (Device.dwTimeContinual - g_last_orphan_check < SPAWN_RETRY_MS)
			return;
		g_last_orphan_check = Device.dwTimeContinual;
		for (u32 i = 0, n = Level().Objects.o_count(); i < n; ++i)
		{
			CGameObject* object = smart_cast<CGameObject*>(Level().Objects.o_get_by_iterator(i));
			if (!is_proxy(object) || object->getDestroy())
				continue;
			u32 peer = u32(-1);
			sscanf(*object->cName(), "coop_proxy_%u", &peer);
			if (!peers().count(peer))
				object->DestroyObject();
		}
	}

	//------------------------------------------------------------------------------------------------
	// Grudges

	// who holds one: the squad, as an actor's attack sets the whole group against him
	static u16 grudge_key(u16 npc)
	{
		const CSE_ALifeMonsterAbstract* monster = ai().get_alife() ?
			smart_cast<const CSE_ALifeMonsterAbstract*>(ai().alife().objects().object(npc, true)) : nullptr;
		return monster && monster->m_group_id != NO_OBJECT ? monster->m_group_id : npc;
	}

	static shared_str level_of_player(u32 peer)
	{
		if (peer == my_id())
			return g_pGameLevel ? Level().name() : shared_str();
		auto it = peers().find(peer);
		return it != peers().end() ? it->second.level : shared_str();
	}

	// f(id) for each member of a squad, or the one NPC
	template <typename F>
	static void for_members(u16 key, F f)
	{
		CSE_ALifeOnlineOfflineGroup* squad = ai().get_alife() ?
			smart_cast<CSE_ALifeOnlineOfflineGroup*>(ai().alife().objects().object(key, true)) : nullptr;
		if (!squad)
			return f(key);
		for (const auto& member : squad->squad_members())
			f(member.first);
	}

	static void add_grudge(u16 key, u32 peer, bool ours)
	{
		if (!g_grudges.insert({key, peer}).second)
			return;
		if (!g_grudged_on.count(peer))
			g_grudged_on[peer] = level_of_player(peer);
		if (ours)
		{
			NET_Packet P;
			P.w_begin(M_COOP_HIT);
			P.w_u8(eGrudge);
			P.w_u32(key);
			P.w_u32(peer);
			send(P);
		}
		const CSE_Abstract* holder = ai().get_alife() ? ai().alife().objects().object(key, true) : nullptr;
		auto player = peers().find(peer);
		Msg("[coop] %s (id=%u) holds a grudge against %s", holder ? holder->name_replace() : "?", key,
		    peer == my_id() ? "us" : player != peers().end() ? player->second.name.c_str() : "a player gone");
	}

	// The squads that stand up for a stalker who was hit: the others of its faction in its camp (the smart
	// terrain it belongs to) and, within the rules' witness_radius, those near it.
	static void stand_up_for(u16 npc, xr_set<u16>& squads)
	{
		CAI_Stalker* victim = smart_cast<CAI_Stalker*>(Level().Objects.net_Find(npc));
		if (!victim || !ai().get_alife())
			return;
		auto camp_of = [](u16 id)
		{
			const CSE_ALifeMonsterAbstract* se = smart_cast<const CSE_ALifeMonsterAbstract*>(ai().alife().objects().object(id, true));
			return se ? se->m_smart_terrain_id : NO_OBJECT;
		};
		const u16 camp = camp_of(npc);
		const float radius = world_rule("witness_radius", 100.f);
		const int faction = victim->CharacterInfo().Community().index();
		for (u32 i = 0, n = Level().Objects.o_count(); i < n; ++i)
		{
			CAI_Stalker* other = smart_cast<CAI_Stalker*>(Level().Objects.o_get_by_iterator(i));
			if (!other || other == victim || !other->g_Alive() || is_proxy(other) ||
			    other->CharacterInfo().Community().index() != faction)
				continue;
			if ((camp != NO_OBJECT && camp_of(other->ID()) == camp) ||
			    (radius > 0.f && other->Position().distance_to(victim->Position()) <= radius))
				squads.insert(grudge_key(other->ID()));
		}
	}

	// A squad turns on the player who hit one of it, and on the player's group, and so do the squads that
	// stand up for it. A squad that wasn't hostile tells the stalker network who it was, unless nobody of it
	// lives to (coop_sync.script).
	static void turn_on(u16 npc, u16 key, u32 peer, bool was_hostile)
	{
		const bool fresh = !g_grudges.count({key, peer});
		xr_set<u16> squads;
		squads.insert(key);
		stand_up_for(npc, squads);
		for (u16 squad : squads)
		{
			add_grudge(squad, peer, true);
			for (const auto& [id, other] : peers())
				if (id != peer && same_group(peer, id))
					add_grudge(squad, id, true);
			if (peer != my_id() && same_group(peer, my_id()))
				add_grudge(squad, my_id(), true);
		}
		const xr_string* name = peer == my_id() ? &my_name() : nullptr;
		auto it = peers().find(peer);
		if (it != peers().end())
			name = &it->second.name;
		if (fresh && !was_hostile && name)
			call_lua("_G.coop_on_squad_attacked", npc, peer, name->c_str());
	}

	// what vanilla's hit by our own actor left (RELATION_REGISTRY::Action, xr_combat_ignore) goes too
	static void calm(u16 key)
	{
		const u16 actor = g_actor ? g_actor->ID() : 0;
		for_members(key, [actor](u16 npc)
		{
			if (RELATION_REGISTRY().GetGoodwill(npc, actor) < 0)
				RELATION_REGISTRY().SetGoodwill(npc, actor, 0);
		});
		call_lua("_G.coop_on_calm", key);
	}

	// a player gone from the level where squads turned on them, or from the game: they calm down
	static void forget_player(u32 peer)
	{
		u32 forgotten = 0;
		for (auto it = g_grudges.begin(); it != g_grudges.end();)
		{
			if (it->second != peer)
			{
				++it;
				continue;
			}
			if (peer == my_id())
				calm(it->first);
			it = g_grudges.erase(it);
			++forgotten;
		}
		g_grudged_on.erase(peer);
		if (forgotten)
			Msg("[coop] %u grudge(s) against %s forgotten: gone from that level", forgotten,
			    peer == my_id() ? "us" : "a player");
	}

	// A player fell: the squads that turned on them got even and calm down, towards the player's group as
	// well. The faction's goodwill stays as the attack left it.
	static void settle_with(u32 peer)
	{
		xr_set<u16> squads;
		for (const auto& [key, against] : g_grudges)
			if (against == peer)
				squads.insert(key);
		u32 settled = 0;
		for (auto it = g_grudges.begin(); it != g_grudges.end();)
		{
			if (!squads.count(it->first))
			{
				++it;
				continue;
			}
			if (it->second == my_id())
				calm(it->first);
			it = g_grudges.erase(it);
			++settled;
		}
		if (settled)
			Msg("[coop] %u grudge(s) of %u squad(s) settled: %s fell", settled, u32(squads.size()),
			    peer == my_id() ? "we" : "the player they turned on");
	}

	void on_player_fell()
	{
		settle_with(my_id());
		NET_Packet P;
		P.w_begin(M_COOP_HIT);
		P.w_u8(eFallen);
		P.w_u32(my_id());
		send(P);
	}

	static void forget_gone_players()
	{
		xr_vector<u32> gone;
		for (const auto& [peer, level] : g_grudged_on)
			if ((peer != my_id() && !peers().count(peer)) || level_of_player(peer) != level)
				gone.push_back(peer);
		for (u32 peer : gone)
			forget_player(peer);
	}

	bool has_grudge_id(u16 npc, u16 other)
	{
		if (g_grudges.empty())
			return false;
		const u32 peer = g_actor && other == g_actor->ID() ? my_id() : peer_of_proxy(other);
		return peer != u32(-1) && g_grudges.count({grudge_key(npc), peer});
	}

	bool has_grudge(const CEntityAlive* npc, const CEntityAlive* other)
	{
		return !g_grudges.empty() && other && has_grudge_id(npc->ID(), other->ID());
	}

	// RELATION_REGISTRY::Action: an actor's hit on one fighting someone hostile to the actor as well
	// (its "danger" goodwill) barely counts; the same for a player's stand-in
	static bool accidental(CEntityAlive* npc, const CInventoryOwner* attacker)
	{
		CAI_Stalker* stalker = smart_cast<CAI_Stalker*>(npc);
		const CEntityAlive* enemy = stalker ? stalker->memory().enemy().selected() : nullptr;
		const CInventoryOwner* enemy_owner = smart_cast<const CInventoryOwner*>(enemy);
		return enemy && enemy_owner && attacker && enemy->human_being() &&
			RELATION_REGISTRY().GetRelationType(enemy_owner, attacker) == ALife::eRelationTypeEnemy;
	}

	// our actor's hits on NPCs this game runs, as hits through a stand-in are (on_coop_hit): a grudge
	// for every game, unless by accident
	static void judge_actor_hits()
	{
		for (const auto& [id, hit] : g_actor_hits)
			if (!hit.accidental)
				turn_on(id, hit.key, my_id(), hit.was_hostile);
		g_actor_hits.clear();
	}

	//------------------------------------------------------------------------------------------------
	// Stand-ins

	void update_combat()
	{
		if (!world_ready() || !is_connected())
			return;
		judge_actor_hits();
		forget_gone_players();

		const shared_str& level = Level().name();
		remove_orphans();

		for (auto it = g_proxies.begin(); it != g_proxies.end();)
		{
			auto peer = peers().find(it->first);
			if (peer == peers().end() || peer->second.level != level || !peer->second.has_look ||
			    (peer->second.look.flags & SLook::eDead)) // a dead player's stand-in would draw fire forever
			{
				if (CGameObject* object = proxy_of_peer(it->first))
					object->DestroyObject();
				it = g_proxies.erase(it);
			}
			else
				++it;
		}

		for (const auto& [id, peer] : peers())
		{
			if (peer.level != level || !peer.has_look || (peer.look.flags & SLook::eDead))
				continue;
			SProxy& proxy = g_proxies[id];
			CObject* object = proxy.object != NO_OBJECT ? Level().Objects.net_Find(proxy.object) : nullptr;
			if (!object)
			{
				proxy.object = find_proxy_object(id); // spawning takes a frame or two
				if (proxy.object != NO_OBJECT)
					Msg("[coop] stand-in for '%s' is object %u", peer.name.c_str(), proxy.object);
				if (proxy.object == NO_OBJECT && Device.dwTimeContinual - proxy.spawned > SPAWN_RETRY_MS)
				{
					proxy.spawned = Device.dwTimeContinual;
					proxy.placed = false;
					proxy.community = nullptr;
					proxy.legs = proxy.torso = proxy.head = NO_MOTION;
					proxy.named = false;
					spawn_proxy(id, peer);
				}
				continue;
			}
			if (object->getVisible())
				object->setVisible(FALSE); // the puppet shows the player
			if (peer.look.community != proxy.community)
			{
				proxy.community = peer.look.community;
				set_community(object, proxy.community);
			}
			if (!proxy.named)
				if (CInventoryOwner* owner = smart_cast<CInventoryOwner*>(object))
				{
					owner->ChangeName(peer.name.c_str());
					proxy.named = true;
				}
		}
	}

	bool use_player(CInventoryOwner* person)
	{
		CGameObject* object = smart_cast<CGameObject*>(person);
		if (!is_proxy(object))
			return false;
		const u32 peer = peer_of_proxy(object->ID());
		auto it = peers().find(peer);
		if (it != peers().end())
			call_lua("_G.coop_on_use_player", peer, it->second.name.c_str());
		return true; // never a talk with a stand-in
	}

	// the player's model playing the player's motions, as its puppet does: NPCs aim at its bones and
	// bullets hit them, so a player crouching behind cover is crouching here too
	static void pose_proxy(CCustomMonster* npc, SProxy& proxy, const SLook& look)
	{
		CAI_Stalker* stalker = smart_cast<CAI_Stalker*>(npc);
		if (stalker && look.visual.size() && look.visual != npc->cNameVisual())
		{
			stalker->ChangeVisual(look.visual);
			proxy.legs = proxy.torso = proxy.head = NO_MOTION;
		}
		IKinematicsAnimated* K = smart_cast<IKinematicsAnimated*>(npc->Visual());
		if (!K)
			return;
		const xr_vector<shared_str>& names = puppet_motion_names();
		auto play = [&](u16 index)
		{
			const MotionID motion = index < names.size() ? K->ID_Cycle_Safe(names[index]) : MotionID();
			if (motion.valid())
				K->PlayCycle(motion);
		};
		if (look.legs != proxy.legs)
			play(proxy.legs = look.legs);
		if (look.torso != proxy.torso || look.torso_seq != proxy.torso_seq)
		{
			proxy.torso_seq = look.torso_seq;
			play(proxy.torso = look.torso);
		}
		if (look.head != proxy.head)
			play(proxy.head = look.head);
		K->UpdateTracks();
		// never drawn: its bones are worked out here, for those who aim at them
		IKinematics* bones = smart_cast<IKinematics*>(npc->Visual());
		bones->CalculateBones_Invalidate();
		bones->CalculateBones(TRUE);
	}

	bool drive_proxy(CCustomMonster* npc, Fvector& position, float& model_yaw, SRotation& torso)
	{
		const u32 peer_id = peer_of_proxy(npc->ID());
		auto peer = peers().find(peer_id);
		position = npc->Position();
		model_yaw = 0.f;
		torso.yaw = torso.pitch = torso.roll = 0.f;
		if (peer == peers().end())
			return true;

		SProxy& proxy = g_proxies[peer_id];
		const Fvector& target = peer->second.position;
		const float heading = peer->second.look.body_yaw;
		if (!proxy.placed || proxy.position.distance_to(target) > SNAP_DISTANCE)
		{
			proxy.position = target;
			proxy.heading = heading;
			proxy.placed = true;
		}
		const float k = _min(1.f, Device.fTimeDelta * FOLLOW_RATE);
		proxy.position.lerp(proxy.position, target, k);
		proxy.heading = angle_lerp(proxy.heading, heading, k);

		position = proxy.position;
		model_yaw = proxy.heading;
		torso.yaw = proxy.heading;
		npc->XFORM().rotateY(proxy.heading);
		npc->XFORM().translate_over(proxy.position);
		if (CCharacterPhysicsSupport* physics = npc->character_physics_support())
			if (CPHMovementControl* control = physics->movement())
				control->SetPosition(proxy.position);
		pose_proxy(npc, proxy, peer->second.look);
		return true;
	}

	//------------------------------------------------------------------------------------------------
	// Hits

	static void send_hit(EHitKind kind, u32 target, SHit& hit)
	{
		NET_Packet P;
		P.w_begin(M_COOP_HIT);
		P.w_u8(kind);
		P.w_u32(target);
		hit.PACKET_TYPE = GE_HIT;
		hit.Write_Packet_Cont(P);
		send(P);
	}

	bool intercept_hit(CGameObject* target, SHit& hit)
	{
		if (!is_connected() || !g_pGameLevel)
			return false;
		CCustomMonster* npc = smart_cast<CCustomMonster*>(target);
		if (!npc)
			return false;

		if (is_proxy(npc))
		{
			// whoever hits a player's stand-in here hits that player; the stand-in takes nothing
			const u32 peer = peer_of_proxy(npc->ID());
			if (peer != u32(-1) && smart_cast<const CEntityAlive*>(hit.who) && hit.who != npc)
			{
				send_hit(eHitPlayer, peer, hit);
				Msg("[coop] %s hit the stand-in of peer %u (%.2f): sent", *hit.who->cName(), peer, hit.damage());
			}
			return true;
		}
		if (is_npc_puppet(npc))
		{
			// another game runs this NPC: our player's hit goes there, the rest is that game's business
			if (hit.who && hit.who == g_actor)
			{
				send_hit(eHitNpc, npc->ID(), hit);
				Msg("[coop] we hit %s (%.2f): sent to the level's authority", *npc->cName(), hit.damage());
			}
			return true;
		}
		if (hit.who && hit.who == g_actor && smart_cast<CAI_Stalker*>(npc) && npc->g_Alive() && !g_actor_hits.count(npc->ID()))
			g_actor_hits[npc->ID()] = {grudge_key(npc->ID()), npc->tfGetRelationType(g_actor) == ALife::eRelationTypeEnemy,
			                          accidental(npc, smart_cast<CInventoryOwner*>(g_actor))};
		return false;
	}

	void on_coop_hit(u32 sender, NET_Packet& P)
	{
		const u8 kind = P.r_u8();
		const u32 target = P.r_u32();
		if (kind == eGrudge)
		{
			add_grudge(u16(target), P.r_u32(), false);
			return;
		}
		if (kind == eFallen)
		{
			settle_with(target);
			return;
		}
		SHit hit;
		hit.PACKET_TYPE = GE_HIT;
		hit.Read_Packet_Cont(P);
		if (!world_ready())
			return;

		if (kind == eHitNpc)
		{
			if (!is_authority(Level().name()))
				return;
			CEntityAlive* npc = smart_cast<CEntityAlive*>(Level().Objects.net_Find(u16(target)));
			CGameObject* proxy = proxy_of_peer(sender);
			if (!npc || !npc->g_Alive() || !proxy)
			{
				Msg("! [coop] peer %u's hit on %u dropped: %s", sender, target,
				    !npc ? "no such NPC here" : !npc->g_Alive() ? "dead here" : "no stand-in of that peer yet");
				return;
			}
			hit.who = proxy;
			hit.whoID = proxy->ID();
			hit.weaponID = proxy->ID();
			// each answers for himself: the NPC's squad turns on the one who hit it, unless by accident
			CAI_Stalker* stalker = smart_cast<CAI_Stalker*>(npc);
			if (stalker && !accidental(npc, smart_cast<CInventoryOwner*>(proxy)))
				turn_on(npc->ID(), grudge_key(npc->ID()), sender,
				        stalker->tfGetRelationType(smart_cast<CEntityAlive*>(proxy)) == ALife::eRelationTypeEnemy);
			npc->Hit(&hit);
			Msg("[coop] peer %u hit %s (%.2f) through its stand-in", sender, *npc->cName(), hit.damage());
		}
		else if (kind == eHitPlayer)
		{
			if (target != my_id() || !g_actor || !g_actor->g_Alive())
				return;
			// our actor is id 0 everywhere: a player's own hit comes from its stand-in here
			CObject* who = hit.whoID == 0 ? proxy_of_peer(sender) : Level().Objects.net_Find(hit.whoID);
			if (!who)
			{
				Msg("! [coop] a hit from peer %u dropped: its attacker %u isn't here", sender, hit.whoID);
				return;
			}
			hit.who = who;
			g_actor->Hit(&hit);
			Msg("[coop] %s hit us (%.2f) in peer %u's game", *who->cName(), hit.damage(), sender);
		}
	}

	//------------------------------------------------------------------------------------------------
	// Bullets: a shot's bullets fly in the other games too, as blanks (no hits sent): the same bullets
	// from the same muzzle, each in its direction with its ricochet seed and the cartridge as loaded, so
	// tracers, ricochets and impacts are where they were; what they hit is up to the game they were fired in

	void on_fire_trace(const CWeapon& weapon, const Fvector& position, float speed, const CCartridge& cartridge,
	                   const xr_vector<SBlank>& bullets)
	{
		const CObject* shooter = weapon.H_Parent();
		if (!shooter || !is_connected() || !g_pGameLevel)
			return;
		u16 npc = NO_OBJECT; // our player's
		if (shooter != g_actor)
		{
			if (!smart_cast<const CAI_Stalker*>(shooter) || is_proxy(shooter) || !is_authority(Level().name()))
				return;
			npc = shooter->ID();
		}
		NET_Packet P;
		P.w_begin(M_ACTOR_ACTION);
		P.w_u8(eBullets);
		P.w_u16(npc);
		P.w_stringZ(weapon.cNameSect());
		P.w_stringZ(cartridge.m_ammoSect);
		P.w(&cartridge.param_s, sizeof(cartridge.param_s)); // the same build everywhere
		P.w_u8(cartridge.m_flags.get());
		P.w_vec3(position);
		P.w_float(speed);
		P.w_u8(u8(_min(u32(bullets.size()), u32(255))));
		for (u32 i = 0; i < bullets.size() && i < 255; ++i)
		{
			P.w_vec3(bullets[i].direction);
			P.w_s32(bullets[i].seed);
		}
		send(P);
	}

	void play_bullets(u32 sender, NET_Packet& P)
	{
		const u16 npc = P.r_u16();
		shared_str weapon, ammo;
		P.r_stringZ(weapon);
		P.r_stringZ(ammo);
		SCartridgeParam params;
		P.r(&params, sizeof(params));
		const u8 flags = P.r_u8();
		Fvector position;
		P.r_vec3(position);
		const float speed = P.r_float();
		xr_vector<SBlank> bullets(P.r_u8());
		for (SBlank& bullet : bullets)
		{
			P.r_vec3(bullet.direction);
			bullet.seed = P.r_s32();
		}
		if (!world_ready() || !pSettings->section_exist(weapon) || !pSettings->section_exist(ammo))
			return;
		LPCSTR section = *weapon;

		// the shooter here, whom its own bullets pass
		u16 shooter = NO_OBJECT, weapon_id = NO_OBJECT;
		if (npc == NO_OBJECT)
		{
			auto peer = peers().find(sender);
			if (peer == peers().end() || peer->second.level != Level().name())
				return;
			if (CGameObject* proxy = proxy_of_peer(sender))
				shooter = proxy->ID();
		}
		else
		{
			CAI_Stalker* stalker = smart_cast<CAI_Stalker*>(Level().Objects.net_Find(npc));
			if (!stalker || !is_npc_puppet(stalker))
				return;
			shooter = npc;
			if (CInventoryItem* item = stalker->inventory().ActiveItem())
				weapon_id = item->object().ID();
		}

		CCartridge cartridge;
		cartridge.Load(*ammo, 0);
		cartridge.param_s = params;
		cartridge.m_flags.assign(flags);
		// what CShootingObject::LoadFireParams reads
		string32 power;
		_GetItem(READ_IF_EXISTS(pSettings, r_string, section, "hit_power", "0"), 0, power);
		const float distance = READ_IF_EXISTS(pSettings, r_float, section, "fire_distance", 600.f);
		const float impulse = READ_IF_EXISTS(pSettings, r_float, section, "hit_impulse", 0.f);
		const float air_resistance = READ_IF_EXISTS(pSettings, r_float, section, "air_resistance_factor", 1.f);
		for (const SBlank& bullet : bullets)
			Level().BulletManager().AddBullet(position, bullet.direction, speed, float(atof(power)), impulse, shooter,
			                                  weapon_id, ALife::eHitTypeFireWound, distance, cartridge, air_resistance,
			                                  false, false, 0, bullet.seed);
	}

	// the objects stay: they go with the level, or as orphans once we are back (remove_orphans)
	void clear_proxies()
	{
		g_proxies.clear();
		g_actor_hits.clear();
	}

	void clear_grudges()
	{
		g_grudges.clear();
		g_grudged_on.clear();
	}
}
