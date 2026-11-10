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
  help_rewards_all: 'Награда за «Помочь с:» — всем',
  offline_sim: 'Оффлайн-симуляция (мир живёт без игроков)', cleaner: 'Уборщик тел и мусора', bar_events: 'События бара',
  scorcher: 'Выжигатель мозгов', shelter_group_only: 'Вход в убежище только группой', psi_immunity: 'Пси-иммунитет Монолита и Греха',
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

// The world's events an admin starts and stops (server.js worldEvent; in the game coop_world_events.script). The game
// that runs the world's timetable does it (the sim master: the host while it runs the world); to stop a surge or a
// psi storm, and for the weather, every game in the world is told (each runs its own). danger: the action asked
// about first, with what it does to the players. zone: one of the Zone's events (coop_zone_events.script): start on a
// level of its own list (none: one of them), stop (over now, no outcome) or outcome (over now with its outcome).
export const WORLD_EVENTS = [
  { id: 'surge', title: 'Выброс', stop: true, danger: 'start',
    warn: 'Выброс у всех игроков на открытых локациях: кто не в укрытии, погибнет в конце.' },
  { id: 'psi', title: 'Пси-шторм', stop: true, danger: 'start',
    warn: 'Пси-шторм у всех игроков на открытых локациях: кто не в укрытии, получит пси-урон и может погибнуть.' },
  { id: 'cooling', title: 'Охлаждение (окно рейда)', stop: true, danger: 'stop',
    warn: 'Окно рейда закроется сейчас: кто в рейде, начнёт терять здоровье от пси, пока не выйдет.' },
  { id: 'calm', title: 'Мёртвый штиль', stop: true, zone: true },
  { id: 'ash', title: 'Пепельный фронт', stop: true, zone: true, danger: 'start',
    warn: 'На локации пепел: игрок без замкнутого научного костюма (СЕВА, ССП) погибнет за несколько минут без антирада.' },
  { id: 'bar_rumour', title: 'Бар: слух о тайнике' },
  { id: 'bar_quarrel', title: 'Бар: ссора' },
  { id: 'bar_spender', title: 'Бар: гуляет отряд' },
  { id: 'bar_gift', title: 'Бар: подарок группе' },
  { id: 'bar_wounded', title: 'Бар: раненый у двери' },
  { id: 'bar_binge', title: 'Бар: техник запил' },
  { id: 'weather_clear', title: 'Погода: ясно' },
  { id: 'weather_partly', title: 'Погода: переменная облачность' },
  { id: 'weather_cloudy', title: 'Погода: облачно' },
  { id: 'weather_rain', title: 'Погода: дождь' },
  { id: 'weather_storm', title: 'Погода: гроза' },
  { id: 'weather_foggy', title: 'Погода: туман' },
];
export const worldEventOf = (id) => WORLD_EVENTS.find((e) => e.id === id) ?? null;
// the actions an event takes
export const eventActions = (e) => (e.zone ? ['start', 'stop', 'outcome'] : e.stop ? ['start', 'stop'] : ['start']);
// a Zone's event's levels as its game reported them ("<id>_levels" = "level:name,..."): [{ id, name }]
export const zoneLevels = (values, id) => String(values?.[`${id}_levels`] ?? '').split(',').filter(Boolean)
  .map((x) => { const [level, name] = x.split(':'); return { id: level, name: name || level }; });
// every game in the world does it, not the sim master alone
export const toEveryGame = (id, action) => id.startsWith('weather_') || ((id === 'surge' || id === 'psi') && action === 'stop');

// game seconds as the admins read them, with the real time at the world's speed (factor)
const gameTime = (seconds, factor) => {
  const s = Math.max(0, Math.round(seconds));
  const text = s < 3600 ? `${Math.floor(s / 60)} мин` : `${Math.floor(s / 3600)} ч ${Math.floor(s % 3600 / 60)} мин`;
  const real = factor > 0 ? Math.round(s / factor / 60) : null;
  return real === null ? text : `${text} (~${real < 60 ? `${real} мин` : `${Math.floor(real / 60)} ч ${real % 60} мин`} реальных)`;
};
// real seconds as the admins read them
const realTime = (seconds) => {
  const s = Math.max(0, Math.round(seconds));
  return s < 3600 ? `${Math.floor(s / 60)} мин` : `${Math.floor(s / 3600)} ч ${Math.floor(s % 3600 / 60)} мин`;
};
const WEATHER = { clear: 'ясно', partly: 'переменная облачность', cloudy: 'облачно', rain: 'дождь', storm: 'гроза',
  foggy: 'туман', pre_blowout: 'перед выбросом' };

// what the world's game said of its events (server.js events(): values as the game reported them) as lines
export function eventsText(events) {
  const v = events?.values;
  if (!v) return ['Событий пока не видно: мир никто не держит или игра ещё не ответила.'];
  const factor = Number(v.factor) || 0;
  const storm = (on, inS) => (on === '1' ? 'идёт' : inS !== undefined ? `через ${gameTime(Number(inS), factor)}` : '?');
  const lines = [`Выброс: ${storm(v.surge, v.surge_in)}`, `Пси-шторм: ${storm(v.psi, v.psi_in)}`];
  lines.push(`Охлаждение: ${v.cool === 'off' ? 'не бывает (Выжигатель выключен)' : v.cool === 'open'
    ? `окно открыто, ещё ${gameTime(Number(v.cool_left), factor)}` : `через ${Math.max(0, Number(v.cool_next) || 0)} ч игровых`}`);
  lines.push(`События бара: ${v.bar_rule === '0' ? 'выключены правилом' : v.barman === '1'
    ? `следующее через ${Math.max(0, Math.round(Number(v.bar_next) || 0))} ч игровых` : 'нет бармена'}`);
  for (const e of WORLD_EVENTS.filter((x) => x.zone)) {
    const where = zoneLevels(v, e.id).find((l) => l.id === v[`${e.id}_level`])?.name ?? v[`${e.id}_level`];
    // the Zone's events last real time: <id>_left is real seconds
    lines.push(`${e.title}: ${v[e.id] === '1' ? `идёт, ${where}, ещё ${realTime(Number(v[`${e.id}_left`]))} реальных` : 'нет'}`);
  }
  if (v.weather) lines.push(`Погода: ${WEATHER[v.weather] ?? v.weather}`);
  if (events.result) lines.push(`Последнее: ${events.result.text}`);
  return lines;
}
