#include "pch_script.h"
#include "coop_net.h"
#include "coop_world.h"
#include "coop_save.h"
#include "coop_combat.h"
#include "coop_puppet.h"
#include "coop_progress.h"
#include "coop_facts.h"
#include "ai_space.h"
#include "script_engine.h"

using namespace luabind;

namespace coop
{
	// coop.peers() -> { { id, name, level, position = vector, yaw, age = ms since last update }, ... }
	static ::luabind::object script_peers()
	{
		::luabind::object result = ::luabind::newtable(ai().script_engine().lua());
		int i = 1;
		for (const auto& [id, peer] : peers())
		{
			::luabind::object t = ::luabind::newtable(ai().script_engine().lua());
			t["id"] = id;
			t["name"] = peer.name.c_str();
			t["level"] = peer.level.c_str();
			t["position"] = peer.position;
			t["yaw"] = peer.yaw;
			t["age"] = Device.dwTimeContinual - peer.last_update;
			t["stand_in"] = stand_in_of(id); // the object NPCs here see for that player, 0 for none
			t["item"] = peer.has_look && peer.look.item.size() ? peer.look.item.c_str() : ""; // what they hold, "" for nothing
			result[i++] = t;
		}
		return result;
	}

	static bool script_is_authority(LPCSTR level_name)
	{
		return is_authority(level_name);
	}

	// coop.send_event(name, payload): handed to _G.coop_on_event(name, sender_name, payload) on the others
	static void script_send_event(LPCSTR name, LPCSTR payload)
	{
		NET_Packet P;
		P.w_begin(M_SCRIPT_EVENT);
		P.w_stringZ(name);
		P.w_stringZ(payload ? payload : "");
		send(P);
	}

	// coop.connect(host, port, name, seed): as coop_connect, for the options page; name "" = the OS user
	static bool script_connect(LPCSTR host, u16 port, LPCSTR name, LPCSTR seed)
	{
		set_world_seed(seed);
		if (!name || !xr_strlen(name))
			name = xr_strlen(Core.UserName) ? Core.UserName : "stalker";
		return connect(host, port, name);
	}

	static LPCSTR script_my_name() { return my_name().c_str(); }

	// coop.group() -> { leader, member... } of our group, {} when we're in none
	static ::luabind::object script_group()
	{
		::luabind::object result = ::luabind::newtable(ai().script_engine().lua());
		if (const xr_vector<xr_string>* group = group_of(my_name()))
			for (u32 i = 0; i < group->size(); ++i)
				result[i + 1] = (*group)[i].c_str();
		return result;
	}

	static void script_group_invite(u32 peer, bool pda) { group_request(eGroupInvite, peer, "", pda); }
	static void script_group_answer(u32 inviter, bool accept) { group_request(accept ? eGroupAccept : eGroupDecline, inviter); }
	static void script_group_leave() { group_request(eGroupLeave, 0); }
	static void script_group_kick(LPCSTR name) { group_request(eGroupKick, 0, name); }

	static u32 script_stand_in_peer(u16 object) { return peer_of_stand_in(object); }
	static LPCSTR script_settings() { return world_settings().c_str(); }

	void script_register(lua_State* L)
	{
		module(L, "coop")
		[
			def("connect", &script_connect),
			def("disconnect", &disconnect),
			def("connected", &is_connected),
			def("link_up", &is_link_up),            // connecting or connected
			def("my_name", &script_my_name),
			def("settings", &script_settings),     // "key=value" lines from the server, "" before they come
			def("world_status", &world_status),    // see coop_save.h
			def("world_creator", &world_creator),
			def("claim_world", &claim_world),
			def("set_save_meta", &set_save_meta),    // (name, reason, who) of the save Lua is about to make
			def("request_save", &request_save),      // (name): the master saves the world
			def("request_saves", &request_saves),    // the list comes to _G.coop_on_saves
			def("propose_rollback", &propose_rollback), // (revision): everyone votes
			def("answer_rollback", &answer_rollback),
			def("propose_pause", &propose_pause),    // (pause): everyone in the world votes
			def("world_paused", &world_paused),
			def("join_world", &join_world),
			def("give_item", &give_item),              // (item id, peer id) to another player: trading
			def("character_community", &character_community),

			def("my_id", &my_id),
			def("ping", &ping_ms),                   // ms to the server and back
			def("refused", &refusal),               // why the server turned us away: "full", "version", ""
			def("peers", &script_peers),
			def("is_sim_master", &is_sim_master),
			def("is_authority", &script_is_authority),
			def("report_fact", &report_fact),          // (key, value) a change in our game; "" gone (coop_facts.h)
			def("fact", &fact),                        // (key) as the server has it, "" none
			def("facts_ready", &facts_ready),          // the actor's first update: facts onto the world, ours count
			def("progress_lua", &progress_lua_file),   // our progress's Lua part to take while loading, "" none
			def("progress_fresh", &progress_fresh),    // a new character: the save's personal Lua state goes
			def("remote_death", &is_dying_remotely), // (id) another game's death of it is being applied here
			def("grudge", &has_grudge_id),          // (npc id, id of our actor or a stand-in): its squad was shot by that player
			def("begin_shared", &begin_shared_spawns),
			def("end_shared", &end_shared_spawns),
			def("send_event", &script_send_event),

			def("group", &script_group),
			def("group_invite", &script_group_invite),   // (peer id, from the PDA)
			def("group_answer", &script_group_answer),   // (inviter id, accept)
			def("group_leave", &script_group_leave),
			def("group_kick", &script_group_kick),       // (name), the leader only

			def("set_downed", &set_downed),              // our player lies wounded (coop_death.script)
			def("fell", &on_player_fell),               // our player fell: squads that turned on them calm down
			def("downed", &is_downed),                   // (peer id) a player lying wounded
			def("stand_in_peer", &script_stand_in_peer)  // (object id) whose stand-in it is, 0 for none
		];
	}
}
