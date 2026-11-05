// The world's clock: one game time for every game in the world (src/xrGame/coop/coop_time.cpp).
// Game time is in ms, as the engine keeps it (ALife::_TIME_ID). It runs at `factor` game ms per real ms while the
// world runs (someone is in it and it isn't paused) and stands still otherwise. `epoch` grows with every jump of
// the time (a game skipping hours, a rollback), so a game that jumped itself knows which news are older.
// Kept in data/clock.json ({ game, factor, epoch } or nothing before the first game told it).
export function createClock({ load, save, now = () => performance.now() }) {
  let state = load(); // { game, factor, epoch } | null
  let at = now();     // real ms when state.game was the time
  let running = false;

  const current = () => (state ? state.game + (running ? state.factor * (now() - at) : 0) : 0);
  // the time now becomes the new starting point
  const rebase = () => {
    if (state) state.game = current();
    at = now();
  };
  const persist = () => save(state ? { game: Math.floor(current()), factor: state.factor, epoch: state.epoch } : null);

  return {
    isSet: () => state !== null,
    now: () => Math.floor(current()),
    factor: () => state?.factor ?? 0,
    epoch: () => state?.epoch ?? 0,
    running: () => running && state !== null,
    // true when it changed
    setRunning(on) {
      if (on === running) return false;
      rebase();
      running = on;
      persist();
      return true;
    },
    // the first game in a world with no clock gives its own time; later ones change nothing
    init(game, factor) {
      if (state || !(game > 0) || !(factor > 0)) return false;
      state = { game, factor, epoch: 1 };
      at = now();
      persist();
      return true;
    },
    jump(ms) {
      if (!state || !(ms > 0)) return false;
      rebase();
      state.game += ms;
      state.epoch++;
      persist();
      return true;
    },
    setFactor(factor) {
      if (!state || !(factor > 0) || factor === state.factor) return false;
      rebase();
      state.factor = factor;
      persist();
      return true;
    },
    // back to a save's time (a rollback)
    set(game) {
      if (!state || !(game > 0)) return false;
      state.game = game;
      at = now();
      state.epoch++;
      persist();
      return true;
    },
    clear() {
      state = null;
      persist();
    },
    persist,
  };
}
