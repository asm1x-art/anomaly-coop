// What the server decides for everyone. The world settings are the options of Anomaly's new game screen
// (gamedata/scripts/ui_mm_faction_select.script) that belong to the world rather than to a character;
// they take effect when a world is created. Factions limit what a player can pick for their character.
// Azazel mode is left out: it swaps the actor for another NPC, which co-op can't follow.

export const FACTIONS = ['stalker', 'dolg', 'freedom', 'csky', 'ecolog', 'killer', 'army', 'bandit', 'monolith',
  'renegade', 'greh', 'isg'];

export const IRONMAN_REGEN_HOURS = [0, 24, 72, 120]; // 0: lives don't come back

export const DEFAULT_SETTINGS = {
  world: {
    story: true,
    warfare: false,
    survival: false,
    campfire: false,
    conditions: false,
    opened_routes: true,
    difficulty: 1, // 1..3
    economy: 1, // 1..3
    ironman: false,
    ironman_lives: 1, // 1..5
    ironman_regen: 0, // IRONMAN_REGEN_HOURS
  },
  factions: FACTIONS.slice(0, 9), // the last three are unlockables in Anomaly
};

const clampInt = (value, min, max, fallback) =>
  Number.isInteger(value) ? Math.min(max, Math.max(min, value)) : fallback;

// For the game, "key=value" lines: booleans as 1/0, factions comma-separated.
export function settingsText(settings) {
  const lines = Object.entries(settings.world).map(([key, value]) =>
    `${key}=${typeof value === 'boolean' ? Number(value) : value}`);
  lines.push(`factions=${settings.factions.join(',')}`);
  return lines.join('\n');
}

// A full, valid copy of settings: unknown keys dropped, missing or bad values replaced by the defaults.
export function normalizeSettings(input = {}) {
  const def = DEFAULT_SETTINGS.world;
  const w = input.world ?? {};
  const bool = (key) => (typeof w[key] === 'boolean' ? w[key] : def[key]);
  const factions = Array.isArray(input.factions) ? FACTIONS.filter((f) => input.factions.includes(f)) : [];
  return {
    world: {
      story: bool('story'),
      warfare: bool('warfare'),
      survival: bool('survival'),
      campfire: bool('campfire'),
      conditions: bool('conditions'),
      opened_routes: bool('opened_routes'),
      difficulty: clampInt(w.difficulty, 1, 3, def.difficulty),
      economy: clampInt(w.economy, 1, 3, def.economy),
      ironman: bool('ironman'),
      ironman_lives: clampInt(w.ironman_lives, 1, 5, def.ironman_lives),
      ironman_regen: IRONMAN_REGEN_HOURS.includes(w.ironman_regen) ? w.ironman_regen : def.ironman_regen,
    },
    factions: factions.length ? factions : [...DEFAULT_SETTINGS.factions],
  };
}
