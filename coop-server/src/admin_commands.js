import { FACTIONS, DEFAULT_SETTINGS, RULE_LIMITS } from './settings.js';

// What an admin may change, and how, for the Telegram bot (telegram.js) and the in-game admin window (server.js
// ADMIN_*): Russian titles and answers.

// what /settings shows and /set changes: [key, title, min, max] for numbers, [key, title] for yes/no
export const WORLD = [
  ['story', 'Сюжет'], ['survival', 'Выживание'], ['campfire', 'Сохранение у костра'],
  ['conditions', 'Изношенные предметы'], ['opened_routes', 'Открытые маршруты'],
  ['difficulty', 'Сложность игры', 1, 3], ['economy', 'Экономика', 1, 3],
];
export const RULE_TITLES = {
  max_players: 'Игроков на сервере', group_max: 'Игроков в группе', faction_penalty: 'Штраф отношений за атаку',
  witness_radius: 'Радиус свидетелей, м', downed_time: 'Время «лёжа», с', revive_time: 'Подъём, с',
  revive_health: 'Здоровье после подъёма, %', rank_loss: 'Потеря ранга при откате, %', fast_travel: 'Быстрое перемещение',
  travel_overloaded: 'Перемещение с перегрузом', travel_enemy_radius: 'Враги рядом (нет перемещения), м',
  tool_discount_1: 'Скидка за инструменты: грубая, %', tool_discount_2: 'Скидка за инструменты: тонкая, %',
  tool_discount_3: 'Скидка за инструменты: калибровка, %', tool_group_share: 'Доля скидки для группы, %',
  story_rewards_all: 'Награда за общий сюжет — всем',
};
// a rule the bot has no title for still shows, under its key
export const RULES = Object.entries(DEFAULT_SETTINGS.rules).map(([key, value]) =>
  (typeof value === 'boolean' ? [key, RULE_TITLES[key] ?? key] : [key, RULE_TITLES[key] ?? key, ...RULE_LIMITS[key]]));
export const FACTION_NAMES = {
  stalker: 'Одиночки', dolg: 'Долг', freedom: 'Свобода', csky: 'Чистое Небо', ecolog: 'Учёные', killer: 'Наёмники',
  army: 'Военные', bandit: 'Бандиты', monolith: 'Монолит', renegade: 'Ренегаты', greh: 'Грех', isg: 'ИСГ',
};
// why a save of the world was made, as the admins read it
const REASONS = {
  auto: () => 'Автосохранение', quick: (s) => `Быстрое · ${s.who}`, named: (s) => `«${s.name}» · ${s.who}`,
  join: (s) => `Вход: ${s.who}`, leave: (s) => `Выход: ${s.who}`, exit: (s) => `Выход мастера: ${s.who}`,
  new: () => 'Новый мир', level: (s) => `Переход: ${s.who}`, rollback: (s) => `Откат к №${s.from}`,
  admin: () => 'По команде админа',
};
export const saveLabel = (s) => (REASONS[s.reason] ?? (() => s.reason))(s);

export const YES = ['1', 'да', 'on', 'вкл', 'yes', 'true'];
export const NO = ['0', 'нет', 'off', 'выкл', 'no', 'false'];
export const yesNo = (value) => (value ? 'да' : 'нет');

// a world setting or a rule from text; the answer says what it is now, or what was wrong
export function setSetting(coop, key = '', value = '') {
  const world = WORLD.find(([k]) => k === key);
  const entry = world ?? RULES.find(([k]) => k === key);
  if (!entry) return `Нет такой настройки${key ? `: ${key}` : ''}. Ключи: ${[...WORLD, ...RULES].map(([k]) => k).join(', ')}`;
  const [, title, min, max] = entry;
  let parsed;
  if (min === undefined) {
    parsed = YES.includes(value.toLowerCase()) ? true : NO.includes(value.toLowerCase()) ? false : undefined;
    if (parsed === undefined) return `${key}: нужно «да» или «нет» (1 или 0).`;
  } else {
    parsed = Number(value);
    if (!/^-?\d+$/.test(value) || parsed < min || parsed > max) return `${key}: нужно целое от ${min} до ${max}.`;
  }
  const s = coop.settings();
  const group = world ? 'world' : 'rules';
  coop.saveSettings({ ...s, [group]: { ...s[group], [key]: parsed } });
  const now = coop.settings()[group][key];
  return `${title}: ${typeof now === 'boolean' ? yesNo(now) : now}`;
}

// a faction allowed for new characters or not (value: on/off, да/нет...); null when it was done, else what was wrong
export function setFaction(coop, id, value = '') {
  const s = coop.settings();
  if (!FACTIONS.includes(id)) return `Нет такой фракции: ${id}. Есть: ${FACTIONS.join(', ')}`;
  const on = YES.includes(String(value).toLowerCase()) ? true : NO.includes(String(value).toLowerCase()) ? false : undefined;
  if (on === undefined) return `Как: /factions ${id} on или /factions ${id} off`;
  const list = on ? [...new Set([...s.factions, id])] : s.factions.filter((f) => f !== id);
  if (!list.length) return 'Нужна хотя бы одна фракция.';
  coop.saveSettings({ ...s, factions: list });
  return null;
}
