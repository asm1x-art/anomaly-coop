// What the server decides for everyone. The world settings are the options of Anomaly's new game screen
// (gamedata/scripts/ui_mm_faction_select.script) that belong to the world rather than to a character;
// they take effect when a world is created. Factions limit what a player can pick for their character.
// Azazel mode is left out: it swaps the actor for another NPC, which co-op can't follow. Warfare and Ironman are off
// in co-op for now (maybe their own modes later): kept here, always false, as the game reads the keys.
// Difficulty and economy are the world's, the same for everyone: a game loading the world takes them from here
// (coop_rules.script), so a change shows from the next load.
// The rules are co-op's own (groups, fights, death, fast travel, story) and apply at once (coop_rules.script).

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
    // % off a mechanic's upgrades of a tier for the player who brought him the tools for it (coop_mechanics.script)
    tool_discount_1: 20, // rough work
    tool_discount_2: 25, // fine work
    tool_discount_3: 30, // calibration
    tool_group_share: 50, // % of that discount for the bringer's group
    story_rewards_all: false, // a group sharing its story: a step's reward for every member, not only who handed it in
    help_rewards_all: false, // «Помочь с:» (coop_help.script): a member's task handed in, its giver's reward for every helper too
    // the world's mechanics, one value for the whole world (were .ltx keys each game read for itself)
    offline_sim: true, // the host's world lives on with nobody in it (time, A-Life, surges); off: it stands (server.js)
    cleaner: true, // the host releases bodies with nothing worth taking (coop_cleanup.script)
    bar_events: true, // the shelter bar's events (shelter_events.script)
    scorcher: true, // the way to the Brain Scorcher (shelter_scorcher.script)
    shelter_group_only: true, // the shelter's entrance opens for a group only (shelter_entrance.script)
    psi_immunity: true, // Monolith and Sin are immune to psi (coop_psi.script)
    // The Zone: Anomaly's own options of the world (its options menu, alife/event, alife/general, gameplay/general),
    // one value for the whole world; a game in co-op reads them from here and hides them in its options menu
    // (coop_world_options.script). The defaults are Anomaly's own. A choice is its number in RULE_CHOICES (from 1).
    surge: true, // surges (alife/event/emission_state)
    surge_hours: 24, // game hours: the next surge comes in half of it to all of it
    surge_fate: 2, // what a surge does to NPCs out of cover
    surge_warning: 1, // how a surge is warned of
    surge_task: true, // the «hide» task
    psi_storm: true,
    psi_hours: 24,
    psi_fate: 1,
    psi_siren: true, // the siren before a psi storm
    psi_task: true,
    stalker_pop: 50, // % of stalker squads the smarts keep (alife/general/alife_stalker_pop)
    mutant_pop: 75, // % of mutant squads
    offline_combat: 1,
    excl_dist: 75, // m: an offline squad this close to a player doesn't come online in front of him; 0: off
    dynamic_relations: false, // the factions' goodwill moves with what their members do
    war_goodwill_reset: false, // goodwill toward a faction at war resets
    heli_spawn: false, // smarts spawn helicopters
    hardcore_ai_aim: false, // NPCs aim faster and better (gameplay/general/hardcore_ai_aim)
    npc_loot_distance: 5, // m: NPCs loot bodies this far; 0: they don't
    corpse_max_count: 5, // bodies a level keeps before the far ones go (coop_cleanup.script)
    corpse_min_dist: 75, // m: no body goes this close to any player
    release_dropped_items: true, // a dropped thing nobody took goes after 4 game hours (off: after 12)
    // silent kills (gameplay/silent_kills): a kill nobody hears or sees isn't put on the killer
    sk_enabled: false,
    sk_melee_enabled: true,
    sk_all_melee_ok: false, // any melee weapon, not the knife alone
    sk_gun_enabled: true, // a silenced gun
    sk_headshot_only: true,
    sk_fresh_time: 300, // game s a body is fresh: found then, its killer is suspected
    sk_suspect_dist: 10, // m
    sk_melee_hear_dist: 5, // m
    sk_gun_hear_dist: 10, // m
    // disguise (gameplay/disguise): what gives a disguised player away; the factors in % (Anomaly's 0.1..2)
    disguise: true,
    disguise_active_item: true,
    disguise_active_item_pct: 100,
    disguise_weapon: true,
    disguise_weapon_pct: 100,
    disguise_outfit: true,
    disguise_outfit_pct: 100,
    disguise_helmet: true,
    disguise_helmet_pct: 100,
    disguise_backpack: true,
    disguise_backpack_pct: 100,
    disguise_inventory: true,
    disguise_inventory_pct: 100,
    disguise_speed: true,
    disguise_speed_pct: 100,
    disguise_distance: true,
    disguise_distance_factor: 5,
    disguise_stay_time: true,
    disguise_stay_time_factor: 20,
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
  tool_discount_1: [0, 90],
  tool_discount_2: [0, 90],
  tool_discount_3: [0, 90],
  tool_group_share: [0, 100],
  rank_loss: [0, 100],
  travel_enemy_radius: [0, 500],
  surge_hours: [6, 168],
  surge_fate: [1, 4],
  surge_warning: [1, 4],
  psi_hours: [6, 168],
  psi_fate: [1, 3],
  stalker_pop: [25, 100],
  mutant_pop: [25, 100],
  offline_combat: [1, 3],
  excl_dist: [0, 100],
  npc_loot_distance: [0, 25],
  corpse_max_count: [5, 30],
  corpse_min_dist: [75, 200],
  sk_fresh_time: [0, 3600],
  sk_suspect_dist: [0, 100],
  sk_melee_hear_dist: [0, 100],
  sk_gun_hear_dist: [0, 100],
  disguise_active_item_pct: [10, 200],
  disguise_weapon_pct: [10, 200],
  disguise_outfit_pct: [10, 200],
  disguise_helmet_pct: [10, 200],
  disguise_backpack_pct: [10, 200],
  disguise_inventory_pct: [10, 200],
  disguise_speed_pct: [10, 200],
  disguise_distance_factor: [1, 100],
  disguise_stay_time_factor: [1, 100],
};

// rules that are a choice: their values' names, the first is 1 (the game's own values in coop_world_options.script)
export const RULE_CHOICES = {
  surge_fate: ['гибнут в конце', 'гибнут на волне', 'становятся зомби', 'их разрывает'],
  surge_warning: ['сирена и радио', 'сирена', 'радио', 'без предупреждения'],
  psi_fate: ['гибнут от вихря', 'становятся зомби', 'не страдают'],
  offline_combat: ['везде', 'только в смартах', 'нет'],
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
      warfare: false,
      survival: bool('survival'),
      campfire: bool('campfire'),
      conditions: bool('conditions'),
      opened_routes: bool('opened_routes'),
      difficulty: clampInt(w.difficulty, 1, 3, def.difficulty),
      economy: clampInt(w.economy, 1, 3, def.economy),
      ironman: false,
      ironman_lives: clampInt(w.ironman_lives, 1, 5, def.ironman_lives),
      ironman_regen: IRONMAN_REGEN_HOURS.includes(w.ironman_regen) ? w.ironman_regen : def.ironman_regen,
    },
    factions: factions.length ? factions : [...DEFAULT_SETTINGS.factions],
    rules,
  };
}
