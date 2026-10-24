#include "pch_script.h"
#include "coop_net.h"
#include "coop_world.h"
#include "coop_save.h"
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
			def("join_world", &join_world),
			def("character_community", &character_community),

			def("my_id", &my_id),
			def("peers", &script_peers),
			def("is_sim_master", &is_sim_master),
			def("is_authority", &script_is_authority),
			def("begin_shared", &begin_shared_spawns),
			def("end_shared", &end_shared_spawns),
			def("send_event", &script_send_event)
		];
	}
}
