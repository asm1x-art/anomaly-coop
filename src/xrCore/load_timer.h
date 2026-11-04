#pragma once

// Level load timing: a scope's wall time written to the log as "* [load] <name>: <n> ms" when it ends.
//   LOAD_TIMER("render: visuals");
struct load_timer
{
	const char* name;
	CTimer timer;

	explicit load_timer(const char* _name) : name(_name) { timer.Start(); }
	~load_timer() { Msg("* [load] %s: %u ms", name, timer.GetElapsed_ms()); }
};

#define LOAD_TIMER_CAT2(a, b) a##b
#define LOAD_TIMER_CAT(a, b) LOAD_TIMER_CAT2(a, b)
#define LOAD_TIMER(name) load_timer LOAD_TIMER_CAT(_load_timer_, __LINE__)(name)
