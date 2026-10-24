#include "pch_script.h"
#include "coop_net.h"
#include "coop_world.h"
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

	void script_register(lua_State* L)
	{
		module(L, "coop")
		[
			def("connected", &is_connected),
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
