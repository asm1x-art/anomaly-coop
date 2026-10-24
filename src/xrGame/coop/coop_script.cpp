#include "pch_script.h"
#include "coop_net.h"
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

	void script_register(lua_State* L)
	{
		module(L, "coop")
		[
			def("connected", &is_connected),
			def("my_id", &my_id),
			def("peers", &script_peers)
		];
	}
}
