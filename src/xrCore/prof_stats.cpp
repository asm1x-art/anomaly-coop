#include "stdafx.h"
#pragma hdrstop

#include "prof_stats.h"
#include <mutex>
#include <algorithm>
#include <map>

namespace prof_stats
{
	volatile bool on = false;

	static std::mutex g_lock;
	static slot* g_slots = nullptr;
	static DWORD g_main_thread = 0;

	static u64 g_end = 0, g_begin = 0, g_last_frame = 0;
	static u32 g_frames = 0;
	static xr_vector<u64> g_frame_times;
	static u64 g_worst = 0;
	static xr_vector<std::pair<const char*, u64>> g_worst_marks;
	static bool g_pending = false;
	static float g_seconds = 0;

	slot* register_slot(const char* function, const char* name)
	{
		slot* s = new slot();
		if (name && name[0])
		{
			const size_t n = xr_strlen(function) + xr_strlen(name) + 3;
			char* buf = (char*)malloc(n);
			xr_sprintf(buf, n, "%s: %s", function, name);
			s->name = buf;
		}
		else
			s->name = function;
		std::lock_guard<std::mutex> l(g_lock);
		s->next = g_slots;
		g_slots = s;
		return s;
	}

	slot* named(const char* group, const char* name)
	{
		static std::mutex lock;
		static std::map<std::pair<const void*, const void*>, slot*> slots;
		std::lock_guard<std::mutex> l(lock);
		slot*& s = slots[std::make_pair((const void*)group, (const void*)name)];
		if (!s)
		{
			if (!strncmp(name, "class ", 6))
				name += 6;
			s = register_slot(group, name);
		}
		return s;
	}

	static void bump_max(std::atomic<u64>& m, u64 t)
	{
		u64 cur = m.load(std::memory_order_relaxed);
		while (t > cur && !m.compare_exchange_weak(cur, t, std::memory_order_relaxed)) {}
	}

	void add(slot* s, u64 t)
	{
		if (GetCurrentThreadId() == g_main_thread)
		{
			s->main_t.fetch_add(t, std::memory_order_relaxed);
			s->main_calls.fetch_add(1, std::memory_order_relaxed);
			s->frame_t.fetch_add(t, std::memory_order_relaxed);
			bump_max(s->main_max, t);
		}
		else
		{
			s->other_t.fetch_add(t, std::memory_order_relaxed);
			s->other_calls.fetch_add(1, std::memory_order_relaxed);
			bump_max(s->other_max, t);
		}
	}

	void start(float seconds)
	{
		g_seconds = seconds;
		g_pending = true; // begins at the next frame, on the main thread
	}

	static double ms(u64 t) { return double(t) * 1000.0 / double(CPU::qpc_freq); }

	static void reset_all()
	{
		std::lock_guard<std::mutex> l(g_lock);
		for (slot* s = g_slots; s; s = s->next)
			s->main_t = s->main_calls = s->main_max = s->other_t = s->other_calls = s->other_max = s->frame_t = 0;
	}

	static double pct(xr_vector<u64>& v, double p)
	{
		if (v.empty())
			return 0.0;
		size_t i = size_t(p * double(v.size()));
		if (i >= v.size())
			i = v.size() - 1;
		return ms(v[i]);
	}

	static void report()
	{
		const double frames = g_frames ? double(g_frames) : 1.0;
		double total_ms = ms(g_last_frame - g_begin);
		if (total_ms <= 0)
			total_ms = 1;
		std::sort(g_frame_times.begin(), g_frame_times.end());
		Msg("* [prof] %u frames in %.1f s: %.1f fps, frame avg %.2f ms, median %.2f, 99%% %.2f, worst %.2f ms", g_frames,
			total_ms / 1000.0, frames * 1000.0 / total_ms, total_ms / frames, pct(g_frame_times, 0.5),
			pct(g_frame_times, 0.99), ms(g_worst));

		xr_vector<slot*> list;
		{
			std::lock_guard<std::mutex> l(g_lock);
			for (slot* s = g_slots; s; s = s->next)
				if (s->main_calls || s->other_calls)
					list.push_back(s);
		}
		std::sort(list.begin(), list.end(), [](slot* a, slot* b) { return a->main_t > b->main_t; });
		Msg("* [prof] main thread: ms per frame (a mark includes the marks inside it) | calls per frame | longest call ms");
		u32 shown = 0;
		for (slot* s : list)
		{
			if (!s->main_calls || shown++ >= 60)
				break;
			Msg("* [prof]   %8.3f | %8.1f | %7.2f  %s", ms(s->main_t) / frames, double(s->main_calls) / frames,
				ms(s->main_max), s->name);
		}
		std::sort(list.begin(), list.end(), [](slot* a, slot* b) { return a->other_t > b->other_t; });
		Msg("* [prof] other threads: ms per frame | calls per frame | longest call ms");
		shown = 0;
		for (slot* s : list)
		{
			if (!s->other_calls || shown++ >= 25)
				break;
			Msg("* [prof]   %8.3f | %8.1f | %7.2f  %s", ms(s->other_t) / frames, double(s->other_calls) / frames,
				ms(s->other_max), s->name);
		}
		Msg("* [prof] the slowest frame (%.2f ms), main thread marks:", ms(g_worst));
		shown = 0;
		for (auto& m : g_worst_marks)
		{
			if (shown++ >= 25)
				break;
			Msg("* [prof]   %8.3f  %s", ms(m.second), m.first);
		}
	}

	void frame()
	{
		const u64 now = CPU::QPC();
		if (g_pending)
		{
			g_pending = false;
			g_main_thread = GetCurrentThreadId();
			reset_all();
			g_frames = 0;
			g_frame_times.clear();
			g_worst = 0;
			g_worst_marks.clear();
			g_begin = g_last_frame = now;
			g_end = now + u64(double(g_seconds) * double(CPU::qpc_freq));
			on = true;
			Msg("* [prof] collecting for %.0f s", g_seconds);
			return;
		}
		if (!on)
			return;

		// the frame that just ended
		const u64 ft = now - g_last_frame;
		g_last_frame = now;
		g_frames++;
		g_frame_times.push_back(ft);
		const bool worst = ft > g_worst;
		if (worst)
		{
			g_worst = ft;
			g_worst_marks.clear();
		}
		{
			std::lock_guard<std::mutex> l(g_lock);
			for (slot* s = g_slots; s; s = s->next)
			{
				const u64 t = s->frame_t.exchange(0, std::memory_order_relaxed);
				if (worst && t)
					g_worst_marks.emplace_back(s->name, t);
			}
		}
		if (worst)
			std::sort(g_worst_marks.begin(), g_worst_marks.end(),
				[](const std::pair<const char*, u64>& a, const std::pair<const char*, u64>& b) { return a.second > b.second; });

		if (now >= g_end)
		{
			on = false;
			report();
		}
	}
}
