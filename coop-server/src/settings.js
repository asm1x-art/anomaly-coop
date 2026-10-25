// What the server decides for everyone. The world settings are the options of Anomaly's new game screen
// (gamedata/scripts/ui_mm_faction_select.script) that belong to the world rather than to a character;
// they take effect when a world is created. Factions limit what a player can pick for their character.
// Azazel mode is left out: it swaps the actor for another NPC, which co-op can't follow.
// The rules are co-op's own (groups, fights, death, fast travel) and apply at once (coop_rules.script).

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
  rules: {
    max_players: 4, // on the server at once
    group_max: 4, // players in a group, the leader included
    faction_penalty: 100, // goodwill a faction loses toward a player who attacks its non-hostile squad
    witness_radius: 100, // m: squads of the attacked one's faction this close stand up for it, as its camp does; 0: the camp only
    downed_time: 90, // s a player lies wounded for others to help up; 0: straight back to the save point
    revive_time: 5, // s of holding F to help one up
    revive_health: 25, // % health one gets up with
    rank_loss: 10, // % of rank lost going back to the save point
    fast_travel: true,
    travel_overloaded: false, // fast travel with too much to carry
    travel_enemy_radius: 50, // m: no fast travel with enemies this close; 0: no such check
  },
};

// rules: [min, max] of the numbers
export const RULE_LIMITS = {
  max_players: [1, 32],
  group_max: [2, 8],
  faction_penalty: [0, 2000],
  witness_radius: [0, 500],
  downed_time: [0, 600],
  revive_time: [1, 60],
  revive_health: [1, 100],
  rank_loss: [0, 100],
  travel_enemy_radius: [0, 500],
};

const clampInt = (value, min, max, fallback) =>
  Number.isInteger(value) ? Math.min(max, Math.max(min, value)) : fallback;

// For the game, "key=value" lines: booleans as 1/0, factions comma-separated.
export function settingsText(settings) {
  const lines = Object.entries(settings.world).map(([key, value]) =>
    `${key}=${typeof value === 'boolean' ? Number(value) : value}`);
  lines.push(`factions=${settings.factions.join(',')}`);
  for (const [key, value] of Object.entries(settings.rules))
    lines.push(`${key}=${typeof value === 'boolean' ? Number(value) : value}`);
  return lines.join('\n');
}

// A full, valid copy of settings: unknown keys dropped, missing or bad values replaced by the defaults.
export function normalizeSettings(input = {}) {
  const def = DEFAULT_SETTINGS.world;
  const w = input.world ?? {};
  const bool = (key) => (typeof w[key] === 'boolean' ? w[key] : def[key]);
  const factions = Array.isArray(input.factions) ? FACTIONS.filter((f) => input.factions.includes(f)) : [];
  const r = input.rules ?? {};
  const rules = {};
  for (const [key, value] of Object.entries(DEFAULT_SETTINGS.rules)) {
    if (typeof value === 'boolean') rules[key] = typeof r[key] === 'boolean' ? r[key] : value;
    else rules[key] = clampInt(r[key], ...RULE_LIMITS[key], value);
  }
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
    rules,
  };
}
