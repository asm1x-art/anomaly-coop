#pragma once

// The world's clock (coop-server/src/clock.js): every game in the shared world runs the server's game time.
// The server keeps it; this game sets the A-Life clock (CALifeTimeManager) to it every frame, counting on from
// the last M_TIME by its own real-time timer, which runs through pauses and loading screens. Small differences
// back in time are never applied: the clock waits for the world to catch up. Weather, surges and psi storms
// follow the sim master's game in Lua (coop_time.script). Settings: [coop_time] in mod_system_coop.ltx.

class NET_Packet;

namespace coop
{
	void on_time(NET_Packet& P); // M_TIME
	void update_time();          // per frame
	void reset_time();           // disconnected

	// engine hooks. level.change_game_time (sleep...): true to let the jump happen here; it then moves the whole
	// world's clock (jumps = alone: only while nobody else is in the world)
	bool allow_time_jump(u32 ms);
	// game_sv_Single::SetGameTimeFactor (level.set_time_factor, the time_factor command): true to let it happen
	// here; in the world only the sim master's game sets the factor, for everyone
	bool allow_time_factor(float factor);

	// Lua: the world's game time now as this game counts it (ms since the start of the calendar), 0 without one
	double clock_ms();
}
