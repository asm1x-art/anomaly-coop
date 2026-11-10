import { setTimeout as sleep } from 'node:timers/promises';
import { FACTIONS } from './settings.js';
import { WORLD, RULES, FACTION_NAMES, yesNo, setSetting, setFaction, saveLabel, WORLD_EVENTS, worldEventOf, eventsText, eventActions, zoneLevels } from './admin_commands.js';

// The Telegram bot: what the admin page does, for the admins listed in server.cfg, and news for them (a player
// joined or left, the host went down, a save failed). Long polling (getUpdates), so no port has to be open;
// no libraries, only fetch. Replies in Russian, plain text. Whatever goes wrong with Telegram, the server goes on.
// It works on server.coop (server.js). What the server doesn't have yet (saveWorld, restartHost, kick, on) the bot
// says isn't there.

const API = 'https://api.telegram.org/bot';
const POLL_SECONDS = 50; // getUpdates waits this long for news
const RETRY_MAX_MS = 60000; // the longest pause between tries while Telegram can't be reached
const CONFIRM_MS = 60000; // a rollback or a reset waits this long for its "yes"
const BUTTON_MS = 10 * 60000; // a log's button works this long
const STALE_S = 60; // commands older than this when they come (sent while the server was off) are dropped
const TEXT_MAX = 4000; // Telegram takes 4096 characters per message
const FILE_MAX = 50 * 1024 * 1024; // what a bot may send
const LOGS_LISTED = 20;
const LOG_BUTTONS = 8;


const COMMANDS = [
  ['status', 'Кто онлайн, мир, сохранения'],
  ['settings', 'Настройки мира и правила'],
  ['set', 'Изменить настройку: /set ключ значение'],
  ['factions', 'Фракции для новых персонажей'],
  ['save', 'Сохранить мир'],
  ['restart_host', 'Перезапустить хост'],
  ['kick', 'Отключить игрока: /kick имя'],
  ['rollback', 'Откатить мир: /rollback ревизия'],
  ['reset_world', 'Сбросить мир'],
  ['logs', 'Логи игроков: /logs имя'],
  ['event', 'События мира: /event, /event surge start'],
  ['confirm', 'Подтвердить откат или сброс'],
  ['help', 'Команды'],
];
const HELP = COMMANDS.map(([c, d]) => `/${c} — ${d}`).join('\n');
const NOT_YET = 'Сервер этого пока не умеет.';

const when = (ms) => new Date(ms).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
const size = (bytes) => (bytes < 1024 * 1024 ? `${Math.ceil(bytes / 1024)} КБ` : `${(bytes / 1024 / 1024).toFixed(1)} МБ`);
const duration = (s) => (s < 3600 ? `${Math.floor(s / 60)} мин` : `${Math.floor(s / 3600)} ч ${Math.floor(s % 3600 / 60)} мин`);
const saveLine = (s) => `№${s.revision} · ${saveLabel(s)} · ${when(s.time)}`;
// an event's details: a name or a reason as such, or in an object
const detail = (e, key) => (typeof e === 'string' ? e : e?.[key] ?? '');

// status().host (server.js, host.js): { running, pid, uptime (s), gave_up, connected, in_world, master }
const HOST_SKIP = ['pid', 'connected', 'in_world'];
function hostLine(host) {
  const parts = [];
  for (const [key, value] of Object.entries(host)) {
    if (HOST_SKIP.includes(key)) continue;
    if (key === 'running') parts.push(value ? 'работает' : 'не работает');
    else if (key === 'memory' && typeof value === 'number') parts.push(size(value));
    else if (key === 'uptime' && typeof value === 'number') {
      if (value) parts.push(`запущен ${duration(value)} назад`);
    } else if (key === 'gave_up') {
      if (value) parts.push('упал 3 раза подряд, ждёт /restart_host');
    } else if (key === 'master') parts.push(value ? 'держит мир' : host.connected ? 'загружает мир' : 'не подключён');
    else if (value !== null && typeof value !== 'object') parts.push(`${key}: ${value}`);
  }
  return `Хост: ${parts.join(', ') || 'есть'}`;
}

// admins: Telegram user ids; fetch: Telegram's API is reached through it (tests give their own)
export function startTelegram({ token, admins, coop, log = console.log, fetch = globalThis.fetch, retryMs = 1000 }) {
  const stop = new AbortController();
  let offset = 0;
  const refused = new Set(); // users told once that the bot isn't theirs

  // a Telegram method; FormData goes as multipart (a file), anything else as JSON. Too many requests: once more,
  // after the pause Telegram asks for.
  const call = async (method, body, signal = AbortSignal.timeout(30000)) => {
    for (let attempt = 0; ; attempt++) {
      const form = body instanceof FormData;
      const res = await fetch(`${API}${token}/${method}`, {
        method: 'POST', signal,
        headers: form ? undefined : { 'Content-Type': 'application/json' },
        body: form ? body : JSON.stringify(body),
      });
      const data = await res.json().catch(() => ({}));
      if (data.ok) return data.result;
      const wait = data.parameters?.retry_after;
      if (res.status === 429 && wait && wait <= 30 && !attempt) {
        await sleep(wait * 1000, null, { signal: stop.signal });
        continue;
      }
      throw Object.assign(new Error(`${method}: ${data.description ?? `HTTP ${res.status}`}`), { status: res.status });
    }
  };
  const say = (chat, text, extra = {}) => call('sendMessage', {
    chat_id: chat, text: text.length > TEXT_MAX ? text.slice(0, TEXT_MAX) + '\n…' : text, ...extra,
  }).catch((e) => log(`telegram: ${e.message}`));

  // Buttons under a message: an id in callback_data, what it does here. A confirmation is used once; /confirm in
  // the same chat says yes to the last one.
  let nextButton = 1;
  const buttons = new Map(); // id -> { chat, until, once, run }
  const confirms = new Map(); // chat -> button id
  const button = (chat, ms, once, run) => {
    const now = Date.now();
    for (const [id, b] of buttons) if (b.until < now) buttons.delete(id);
    const id = String(nextButton++);
    buttons.set(id, { chat, until: now + ms, once, run });
    return id;
  };
  const confirm = (chat, question, yes, run) => {
    const id = button(chat, CONFIRM_MS, true, run);
    confirms.set(chat, id);
    return say(chat, `${question}\nПодтвердите в течение минуты: кнопка или /confirm.`, { reply_markup: { inline_keyboard: [[
      { text: yes, callback_data: `run:${id}` }, { text: 'Отмена', callback_data: `cancel:${id}` }]] } });
  };
  const press = async (chat, id) => {
    const b = buttons.get(id);
    if (!b || b.chat !== chat || b.until < Date.now()) return say(chat, 'Это уже неактуально.');
    if (b.once) buttons.delete(id);
    return attempt(chat, b.run);
  };
  // what failed is said in the chat too
  const attempt = (chat, run) => Promise.resolve().then(run).catch((e) => {
    log(`telegram: ${e.stack ?? e.message}`);
    return say(chat, `Не получилось: ${e.message}`);
  });

  // the world's events: their state and how to start one; one started or stopped (the dangerous asked about first)
  const worldEvent = (chat, id = '', action = 'start', level = '') => {
    if (typeof coop.worldEvent !== 'function') return say(chat, NOT_YET);
    const e = worldEventOf(id);
    if (!e) {
      const now = coop.events();
      const zones = WORLD_EVENTS.filter((x) => x.zone)
        .map((x) => `${x.id}: локации ${zoneLevels(now?.values, x.id).map((l) => l.id).join(', ') || '?'}`);
      return say(chat, [...eventsText(now), '', 'Запустить: /event <событие> start, остановить: /event <событие> stop.',
        'События Зоны: /event <событие> start [локация], stop, outcome (исход сейчас).',
        ...WORLD_EVENTS.map((x) => `${x.id} — ${x.title}${eventActions(x).length > 1 ? ` (${eventActions(x).join('/')})` : ''}`),
        ...zones].join('\n'));
    }
    const run = () => say(chat, coop.worldEvent(e.id, action, 'бот', level));
    if (e.danger === action) return confirm(chat, `${e.title}: ${action === 'start' ? 'начать' : 'остановить'}? ${e.warn}`,
      action === 'start' ? 'Начать' : 'Остановить', run);
    return run();
  };

  const settingsText = () => {
    const s = coop.settings();
    const line = (values) => ([key, title, min, max]) => min === undefined
      ? `${key} = ${yesNo(values[key])} · ${title}`
      : `${key} = ${values[key]} · ${title} (${min}–${max})`;
    return ['Мир (при создании нового мира; сложность и экономика — со следующей загрузки):', ...WORLD.map(line(s.world)),
      '', 'Правила (действуют сразу):', ...RULES.map(line(s.rules)),
      '', `Фракции: ${s.factions.map((f) => FACTION_NAMES[f] ?? f).join(', ')} — /factions`,
      'Изменить: /set ключ значение'].join('\n');
  };

  const factions = (args) => {
    const [id, value = ''] = args.toLowerCase().split(/\s+/);
    if (id) {
      const answer = setFaction(coop, id, value);
      if (answer) return answer;
    }
    const now = coop.settings().factions;
    return ['Из каких фракций можно создать персонажа:',
      ...FACTIONS.map((f) => `${f} · ${FACTION_NAMES[f] ?? f} — ${yesNo(now.includes(f))}`),
      'Включить или выключить: /factions id on|off'].join('\n');
  };

  const statusText = () => {
    const st = coop.status();
    const max = coop.settings().rules.max_players;
    const lines = [`Онлайн: ${st.online.length} из ${max}`];
    for (const p of st.online) {
      const where = [p.level ?? 'в меню', p.ping == null ? '' : `${p.ping} мс`, p.authority ? 'хозяин локации' : '',
        p.master ? 'мастер' : ''].filter(Boolean);
      lines.push(`${p.name} — ${where.join(', ')}`);
    }
    lines.push(st.world ? `Мир: ревизия ${st.world.revision}, сейв ${st.world.owner}` : 'Мира ещё нет');
    if (st.paused) lines.push(`Пауза: попросил ${st.paused}`);
    if (st.host) lines.push(hostLine(st.host));
    if (st.saves?.length) lines.push('Последние сохранения:', ...st.saves.slice(0, 3).map(saveLine));
    return lines.join('\n');
  };

  // /logs: who has logs; /logs <player>: theirs, the newest with buttons; /logs <player> <file>: the file itself.
  // Names may hold spaces, so "<player> <file>" is matched against what there is.
  const logs = (chat, args) => {
    const all = coop.logs();
    if (!args) {
      const count = new Map();
      for (const l of all) count.set(l.player, (count.get(l.player) ?? 0) + 1);
      if (!count.size) return say(chat, 'Логов нет.');
      return say(chat, `Логи есть у: ${[...count].map(([p, n]) => `${p} (${n})`).join(', ')}\n/logs имя — список`);
    }
    const one = all.find((l) => `${l.player} ${l.file}` === args);
    if (one) return sendLog(chat, one);
    const mine = all.filter((l) => l.player === args);
    if (!mine.length) return say(chat, `Нет логов у ${args}.`);
    const lines = mine.slice(0, LOGS_LISTED).map((l) => `${l.file} · ${size(l.size)} · ${when(l.time)}`);
    if (mine.length > LOGS_LISTED) lines.push(`…и ещё ${mine.length - LOGS_LISTED}`);
    const keyboard = mine.slice(0, LOG_BUTTONS).map((l) =>
      [{ text: l.file.length > 40 ? '…' + l.file.slice(-39) : l.file, callback_data: `run:${button(chat, BUTTON_MS, false, () => sendLog(chat, l))}` }]);
    return say(chat, `Логи ${args}, новые сверху:\n${lines.join('\n')}\nПрислать: кнопка или /logs ${args} файл`,
      { reply_markup: { inline_keyboard: keyboard } });
  };
  const sendLog = async (chat, l) => {
    const data = coop.logFile(l.player, l.file);
    if (!data) return say(chat, 'Этого лога уже нет.');
    if (data.length > FILE_MAX) return say(chat, `${l.file}: ${size(data.length)}, Telegram столько не пропустит. Возьмите на веб-странице.`);
    const form = new FormData();
    form.append('chat_id', String(chat));
    form.append('caption', `${l.player} · ${l.file}`);
    form.append('document', new Blob([data]), l.file);
    await call('sendDocument', form, AbortSignal.timeout(5 * 60000)).catch((e) => say(chat, `Не отправилось: ${e.message}`));
  };

  // an optional call to the server: its answer, or NOT_YET when the server has no such function
  const optional = async (chat, fn, args, done, failed) => {
    if (typeof coop[fn] !== 'function') return say(chat, NOT_YET);
    return say(chat, (await coop[fn](...args)) ? done : failed);
  };

  const command = async (chat, cmd, args) => {
    switch (cmd) {
      case 'start':
      case 'help':
        return say(chat, HELP);
      case 'status':
        return say(chat, statusText());
      case 'settings':
        return say(chat, settingsText());
      case 'set':
        return say(chat, setSetting(coop, ...args.split(/\s+/)));
      case 'factions':
        return say(chat, factions(args));
      case 'save':
        return optional(chat, 'saveWorld', [], 'Мир сохраняется.', 'Сохранить сейчас некому: мир никто не держит.');
      case 'restart_host':
        return optional(chat, 'restartHost', [], 'Хост перезапускается.', 'Хоста нет: в server.cfg не указана папка игры.');
      case 'kick':
        if (!args) return say(chat, 'Кого? /kick имя');
        return optional(chat, 'kick', [args], `Отключён: ${args}`, `Нет такого игрока онлайн: ${args}`);
      case 'rollback': {
        const revision = Number(args);
        const save = coop.status().saves?.find((s) => s.revision === revision);
        if (!save) return say(chat, args ? `Нет сохранения №${args}. Список: /status` : 'Как: /rollback ревизия');
        if (revision === coop.status().world?.revision) return say(chat, `№${revision} — это мир сейчас: откатывать не к чему.`);
        return confirm(chat, `Откатить мир к ${saveLine(save)}? Игроки в игре загрузят его заново.`, 'Откатить', () =>
          say(chat, coop.rollback(revision) ? `Мир возвращён к №${revision}.` : `Нет сохранения №${revision}.`));
      }
      case 'reset_world':
        if (coop.status().online.length) return say(chat, 'Сначала все игроки должны выйти.');
        return confirm(chat, 'Удалить мир, всех персонажей и выданные id? Это необратимо.', 'Удалить мир', () =>
          say(chat, coop.resetWorld() ? 'Мир удалён. Следующий вошедший создаст новый.' : 'Сначала все игроки должны выйти.'));
      case 'confirm': {
        const id = confirms.get(chat);
        confirms.delete(chat);
        if (!id || !buttons.has(id)) return say(chat, 'Нечего подтверждать.');
        return press(chat, id);
      }
      case 'logs':
        return logs(chat, args);
      case 'event':
        return worldEvent(chat, ...args.split(/\s+/));
      default:
        return say(chat, `Не знаю такой команды.
${HELP}`);
    }
  };

  const isAdmin = (user) => admins.includes(user?.id);
  const refuse = (chat, user) => {
    if (refused.has(user?.id)) return;
    refused.add(user?.id);
    log(`telegram: ${user?.username ? '@' + user.username : user?.first_name ?? '?'} (id ${user?.id}) is not an admin`);
    return say(chat, `Это бот сервера Anomaly co-op, он отвечает только админам. Ваш id: ${user?.id}`);
  };

  const handleUpdate = async (update) => {
    const query = update.callback_query;
    if (query) {
      await call('answerCallbackQuery', { callback_query_id: query.id }).catch(() => {});
      const chat = query.message?.chat.id;
      if (!chat) return;
      if (!isAdmin(query.from)) return refuse(chat, query.from);
      const [action, id] = String(query.data).split(':');
      if (action === 'cancel') {
        if (buttons.get(id)?.chat === chat) buttons.delete(id);
        return say(chat, 'Отменено.');
      }
      return press(chat, id);
    }
    const msg = update.message;
    if (!msg?.text) return;
    const chat = msg.chat.id;
    if (!isAdmin(msg.from)) return refuse(chat, msg.from);
    if (msg.date < Date.now() / 1000 - STALE_S) return;
    const m = msg.text.trim().match(/^\/(\w+)(?:@\w+)?\s*([\s\S]*)$/);
    if (!m) return say(chat, HELP);
    log(`telegram: ${msg.from.username ? '@' + msg.from.username : msg.from.id}: /${m[1]}`);
    return attempt(chat, () => command(chat, m[1].toLowerCase(), m[2].trim()));
  };

  // news for every admin (each must have written to the bot once, or Telegram won't let it write first);
  // an admin it can't write to is logged once
  const unreachable = new Set();
  const notify = (text) => {
    for (const admin of admins) call('sendMessage', { chat_id: admin, text }).catch((e) => {
      if (unreachable.has(admin)) return;
      unreachable.add(admin);
      log(`telegram: no news for ${admin}: ${e.message}`);
    });
  };
  const NEWS = {
    joined: (e) => `Вошёл: ${detail(e, 'name')}`,
    left: (e) => `Вышел: ${detail(e, 'name')}`,
    host_down: (e) => [`Хост упал${e?.code != null ? ` (код ${e.code})` : ''}.`,
      e?.restarting === false ? 'Больше не перезапускается: /restart_host' : e?.restarting ? 'Перезапускается.' : ''].filter(Boolean).join(' '),
    host_up: () => 'Хост запущен.',
    save_failed: (e) => `Мир не сохранился${detail(e, 'reason') ? `: ${detail(e, 'reason')}` : '.'}`,
  };
  if (typeof coop.on === 'function') {
    for (const [event, text] of Object.entries(NEWS)) coop.on(event, (e) => notify(text(e)));
  } else log('telegram: the server reports no events yet, no news for admins');

  // A pause between tries that grows while Telegram can't be reached; a token Telegram doesn't know stops the bot.
  const poll = async () => {
    let commandsSet = false;
    let delay = 0;
    while (!stop.signal.aborted) {
      try {
        if (!commandsSet) {
          await call('setMyCommands', { commands: COMMANDS.map(([command, description]) => ({ command, description })) });
          commandsSet = true;
        }
        const updates = await call('getUpdates', { offset, timeout: POLL_SECONDS, allowed_updates: ['message', 'callback_query'] },
          AbortSignal.any([stop.signal, AbortSignal.timeout((POLL_SECONDS + 15) * 1000)]));
        if (delay) log('telegram: reached again');
        delay = 0;
        for (const update of updates) {
          offset = update.update_id + 1;
          await handleUpdate(update).catch((e) => log(`telegram: ${e.message}`));
        }
      } catch (e) {
        if (stop.signal.aborted) break;
        if (e.status === 401 || e.status === 404) {
          log('telegram: Telegram does not know this token, the bot is off (check token in server.cfg)');
          break;
        }
        if (!delay) log(`telegram: ${e.message}${e.cause ? ` (${e.cause.code ?? e.cause.message})` : ''}, trying again`);
        delay = Math.min(delay ? delay * 2 : retryMs, RETRY_MAX_MS);
        await sleep(delay, null, { signal: stop.signal }).catch(() => {});
      }
    }
  };
  const done = poll();

  return {
    handleUpdate,
    // stopped: the poll loop has ended
    stop: () => {
      stop.abort();
      return done;
    },
  };
}
