#pragma once
#include <atomic>

// Frame profile summary in the log (console: prof_stats <seconds>). Every PROF_EVENT / START_PROFILE mark also counts
// its time here while a collection runs; the summary gives each mark's ms per frame on the main thread and on the
// others, its calls per frame, its longest call, and the marks of the slowest frame. Off, a mark costs one flag check.
namespace prof_stats
{
	struct slot
	{
		const char* name;
		std::atomic<u64> main_t{ 0 }, main_calls{ 0 }, main_max{ 0 }, other_t{ 0 }, other_calls{ 0 }, other_max{ 0 };
		std::atomic<u64> frame_t{ 0 }; // main thread, this frame (for the slowest frame)
		slot* next = nullptr;
	};

	XRCORE_API extern volatile bool on;
	XRCORE_API slot* register_slot(const char* function, const char* name);
	XRCORE_API void add(slot* s, u64 t);
	// a mark named at run time (by the class of an object, say): one slot per (group, name) pair of stable strings
	XRCORE_API slot* named(const char* group, const char* name);

	// console: start a collection of `seconds`; the summary goes to the log when it ends
	XRCORE_API void start(float seconds);
	// the main thread, once per frame (CRenderDevice::on_idle)
	XRCORE_API void frame();

	struct scope
	{
		slot* s;
		u64 t0;
		IC scope(slot* _s) : s(on ? _s : nullptr), t0(s ? CPU::QPC() : 0) {}
		IC ~scope() { if (s) add(s, CPU::QPC() - t0); }
	};
}

// time a call under a run-time name while a collection runs: PROF_STAT_NAMED("shedule", typeid(*o).name(), o->shedule_Update(dt));
#define PROF_STAT_NAMED(group, name, call) \
	do { if (prof_stats::on) { prof_stats::scope _prof_named_scope(prof_stats::named(group, name)); call; } else { call; } } while (0)

#define PROF_STAT_CAT2(a, b) a##b
#define PROF_STAT_CAT(a, b) PROF_STAT_CAT2(a, b)
// PROF_STAT_SCOPE() names the mark by the function, PROF_STAT_SCOPE("x") by "function: x"
#define PROF_STAT_SCOPE(...) \
	static prof_stats::slot* PROF_STAT_CAT(_prof_slot_, __LINE__) = prof_stats::register_slot(__FUNCTION__, "" __VA_ARGS__); \
	prof_stats::scope PROF_STAT_CAT(_prof_scope_, __LINE__)(PROF_STAT_CAT(_prof_slot_, __LINE__))
