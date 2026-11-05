#include "stdafx.h"
#include "coop_time.h"
#include "coop_net.h"
#include "coop_save.h"
#include "coop_world.h"
#include "ai_space.h"
#include "alife_simulator.h"
#include "alife_time_manager.h"
#include "script_engine.h"
#include "date_time.h"
#include "Level.h"
#include "Actor.h"

#include <chrono>
#include <mutex>

namespace coop
{
	enum : u8
	{
		eTimeRunning = 1, // TIME_FLAG (coop-server/src/protocol.js)
		eTimeSet = 2,
	};
	enum : u8
	{
		eTimeSetInit, // TIME_SET kinds
		eTimeSetJump,
		eTimeSetFactor,
	};

	// [coop_time] in mod_system_coop.ltx, read once
	struct STimeSettings
	{
		enum EJumps { eAlone, eAll, eNever } jumps = eAlone;
		float drift_tolerance_ms = 250.f; // real ms: the server's time moves ours only when this far off
		float max_hold_s = 120.f;         // game s: ours ahead by less waits for the world, by more goes back
		float reselect_weather_s = 600.f; // game s: a step this big re-picks the weather (_G.coop_on_time_jump)
		u32 hold_ms = 3000;               // real ms: after our own jump or factor, older news wait at most this long
		u32 debug_log_ms = 10000;         // coop_debug: how often the clock is logged
	};

	static const STimeSettings& settings()
	{
		static STimeSettings s;
		static bool read = false;
		if (!read && pSettings)
		{
			read = true;
			LPCSTR SECTION = "coop_time";
			if (pSettings->section_exist(SECTION))
			{
				LPCSTR jumps = READ_IF_EXISTS(pSettings, r_string, SECTION, "jumps", "alone");
				s.jumps = !xr_strcmp(jumps, "all") ? STimeSettings::eAll :
				          !xr_strcmp(jumps, "never") ? STimeSettings::eNever : STimeSettings::eAlone;
				s.drift_tolerance_ms = READ_IF_EXISTS(pSettings, r_float, SECTION, "drift_tolerance_ms", s.drift_tolerance_ms);
				s.max_hold_s = READ_IF_EXISTS(pSettings, r_float, SECTION, "max_hold_s", s.max_hold_s);
				s.reselect_weather_s = READ_IF_EXISTS(pSettings, r_float, SECTION, "reselect_weather_s", s.reselect_weather_s);
				s.hold_ms = READ_IF_EXISTS(pSettings, r_u32, SECTION, "hold_ms", s.hold_ms);
				s.debug_log_ms = READ_IF_EXISTS(pSettings, r_u32, SECTION, "debug_log_s", s.debug_log_ms / 1000) * 1000;
			}
		}
		return s;
	}

	// real time that runs through pauses and loading screens, ms
	static double real_ms()
	{
		using namespace std::chrono;
		return duration<double, std::milli>(steady_clock::now().time_since_epoch()).count();
	}

	static u64 wall_ms() // the PC's clock, to compare two games' logs
	{
		using namespace std::chrono;
		return u64(duration_cast<milliseconds>(system_clock::now().time_since_epoch()).count());
	}

	// the server's clock as we count it: anchor_game at anchor_real, on at factor while running
	static bool g_known = false;   // a TIME came
	static bool g_set = false;     // the server has a clock
	static bool g_running = false;
	static double g_anchor_game = 0, g_anchor_real = 0;
	static float g_factor = 1.f;
	static u32 g_epoch = 0;
	// after our own jump (or the master's factor) the news sent before it reached the server are stale
	static u32 g_hold_epoch = 0;
	static float g_hold_factor = 0.f;
	static double g_hold_until = 0;
	static u64 g_applied = 0;      // what we set last; 0: not yet in this level
	static u32 g_last_init = 0, g_last_log = 0;

	static double target_at(double real)
	{
		return g_anchor_game + (g_running ? double(g_factor) * (real - g_anchor_real) : 0.);
	}

	static double target()
	{
		return target_at(real_ms());
	}

	// the newest M_TIME from the socket's thread
	static std::mutex g_inbox_lock;
	static xr_vector<u8> g_inbox;
	static double g_inbox_at = 0;
	static bool g_inbox_new = false;

	void receive_time(const u8* data, u32 size)
	{
		std::lock_guard<std::mutex> lock(g_inbox_lock);
		g_inbox.assign(data, data + size);
		g_inbox_at = real_ms();
		g_inbox_new = true;
	}

	static CALifeTimeManager* time_manager()
	{
		if (!ai().get_alife() || !ai().alife().initialized())
			return nullptr;
		return &const_cast<CALifeSimulator&>(ai().alife()).time_manager();
	}

	static LPCSTR day_time(u64 t, string64& buf)
	{
		u32 year, month, day, hours, mins, secs, ms;
		split_time(t, year, month, day, hours, mins, secs, ms);
		xr_sprintf(buf, "%02u.%02u %02u:%02u:%02u", day, month, hours, mins, secs);
		return buf;
	}

	// received: real_ms() when it came
	static void on_time(NET_Packet& P, double received)
	{
		u16 type;
		P.r_begin(type);
		const u64 game = P.r_u64();
		const float factor = P.r_float();
		const u8 flags = P.r_u8();
		const u32 epoch = P.r_u32();
		g_known = true;

		if (!(flags & eTimeSet))
		{
			g_set = false;
			return;
		}
		// our own jump or factor isn't in this one yet
		if (received < g_hold_until)
		{
			if (epoch <= g_hold_epoch && (g_hold_factor == 0.f || !fsimilar(factor, g_hold_factor)))
				return;
			g_hold_until = 0;
		}
		const bool running = (flags & eTimeRunning) != 0;
		// it left the server half a round trip before it came
		const double game_then = double(game) + (running ? double(factor) * ping_ms() / 2. : 0.);
		const bool changed = !g_set || running != g_running || !fsimilar(factor, g_factor) || epoch != g_epoch;
		const double off = game_then - target_at(received);
		if (changed || _abs(off) > settings().drift_tolerance_ms * factor)
		{
			if (debug_mode && g_set)
				Msg("[coop dbg] clock: server time taken, %+.0f game ms off%s", off, changed ? " (changed)" : "");
			g_anchor_game = game_then;
			g_anchor_real = received;
		}
		g_set = true;
		g_running = running;
		g_factor = factor;
		g_epoch = epoch;
	}

	void reset_time()
	{
		{
			std::lock_guard<std::mutex> lock(g_inbox_lock);
			g_inbox_new = false;
		}
		g_known = g_set = g_running = false;
		g_epoch = g_hold_epoch = 0;
		g_hold_until = 0;
		g_applied = 0;
	}

	void update_time()
	{
		{
			xr_vector<u8> msg;
			double at = 0;
			{
				std::lock_guard<std::mutex> lock(g_inbox_lock);
				if (g_inbox_new)
				{
					msg.swap(g_inbox);
					at = g_inbox_at;
					g_inbox_new = false;
				}
			}
			if (!msg.empty())
			{
				NET_Packet P;
				P.construct(msg.data(), (u32)msg.size());
				on_time(P, at);
			}
		}

		CALifeTimeManager* tm = time_manager();
		if (!tm || !g_pGameLevel || !runs_shared_world() || !world_ready())
		{
			g_applied = 0; // a level loads: whatever it brings is the starting point
			return;
		}
		if (!g_set)
		{
			// a world with no clock yet: ours becomes it
			if (g_known && g_actor && Device.dwTimeContinual - g_last_init > 2000)
			{
				g_last_init = Device.dwTimeContinual;
				NET_Packet P;
				P.w_begin(M_TIME_SET);
				P.w_u8(eTimeSetInit);
				P.w_u64(tm->game_time());
				P.w_float(tm->time_factor());
				send(P);
				Msg("[coop] the world has no clock yet: ours goes, %llu x%.1f", tm->game_time(), tm->time_factor());
			}
			return;
		}

		const u64 local = tm->game_time();
		u64 want = u64(target());
		// never back by a little: wait for the world
		const u64 floor = g_applied ? g_applied : local;
		if (want < floor && double(floor - want) < settings().max_hold_s * 1000.)
			want = floor;
		const s64 step = s64(want) - s64(local);
		tm->set_game_time(want, g_factor);
		g_applied = want;

		if (_abs(double(step)) >= settings().reselect_weather_s * 1000.)
		{
			string64 a, b;
			Msg("[coop] clock: %s -> %s, the world's time", day_time(local, a), day_time(want, b));
			::luabind::functor<void> handler;
			if (ai().script_engine().functor("_G.coop_on_time_jump", handler))
				handler(double(step) / 1000.);
		}

		if (debug_mode && Device.dwTimeContinual - g_last_log >= settings().debug_log_ms)
		{
			g_last_log = Device.dwTimeContinual;
			string64 a;
			Msg("[coop dbg] clock: game %llu (%s) server %.0f (%+.0f ms) x%.2f %s epoch %u wall %llu", want,
			    day_time(want, a), target(), target() - double(want), g_factor, g_running ? "running" : "standing",
			    g_epoch, wall_ms());
		}
	}

	static u32 others_in_world()
	{
		u32 count = 0;
		for (const auto& [id, peer] : peers())
			if (Device.dwTimeContinual - peer.last_update < 3000) // their state comes 10 times a second in the world
				++count;
		return count;
	}

	bool allow_time_jump(u32 ms)
	{
		if (!is_connected() || !g_set || !runs_shared_world())
			return true;
		const STimeSettings& s = settings();
		const u32 others = others_in_world();
		if (s.jumps == STimeSettings::eNever || (s.jumps == STimeSettings::eAlone && others))
		{
			Msg("[coop] time doesn't jump %u game min: %u other player(s) in the world", ms / 60000, others);
			return false;
		}
		// ours now, the server's for everyone a moment later
		g_anchor_game += ms;
		if (g_applied)
			g_applied += ms;
		g_hold_epoch = g_epoch;
		g_hold_factor = 0.f;
		g_hold_until = real_ms() + s.hold_ms;
		NET_Packet P;
		P.w_begin(M_TIME_SET);
		P.w_u8(eTimeSetJump);
		P.w_u32(ms);
		send(P);
		Msg("[coop] time jumps %u game min for the whole world", ms / 60000);
		return true;
	}

	bool allow_time_factor(float factor)
	{
		if (!is_connected() || !g_set || !runs_shared_world())
			return true;
		if (!is_sim_master())
		{
			static float told = 0.f; // once per value: Anomaly asks every second while they differ
			if (debug_mode && !fsimilar(factor, g_factor) && !fsimilar(factor, told))
				Msg("[coop dbg] clock: time factor x%.1f not ours to set (the sim master's is x%.1f)", factor, g_factor);
			told = factor;
			return false;
		}
		if (fsimilar(factor, g_factor))
			return true;
		g_anchor_game = target();
		g_anchor_real = real_ms();
		g_factor = factor;
		g_hold_epoch = g_epoch;
		g_hold_factor = factor;
		g_hold_until = real_ms() + settings().hold_ms;
		NET_Packet P;
		P.w_begin(M_TIME_SET);
		P.w_u8(eTimeSetFactor);
		P.w_float(factor);
		send(P);
		Msg("[coop] time factor x%.1f for the whole world", factor);
		return true;
	}

	double clock_ms()
	{
		return g_set ? target() : 0.;
	}
}
