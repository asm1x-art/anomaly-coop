import { test } from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { startTelegram } from '../src/telegram.js';
import { normalizeSettings } from '../src/settings.js';

const ADMIN = 111;
const OTHER = 999;
const json = (data, status = 200) => new Response(JSON.stringify(data), { status });

// Telegram as the bot sees it through fetch. getUpdates: what poll(body, signal) answers; by default it waits
// until the bot stops. Every call is kept: { method, body } (a FormData body as it is).
function fakeTelegram(poll) {
  const calls = [];
  const fetch = async (url, init) => {
    const method = url.slice(url.lastIndexOf('/') + 1);
    const body = init.body instanceof FormData ? init.body : JSON.parse(init.body);
    calls.push({ method, body });
    if (method === 'getUpdates') {
      if (poll) return poll(body, init.signal);
      return new Promise((_, reject) => {
        if (init.signal.aborted) reject(init.signal.reason); // as fetch does
        init.signal.addEventListener('abort', () => reject(init.signal.reason), { once: true });
      });
    }
    return json({ ok: true, result: method === 'sendMessage' ? { message_id: calls.length } : true });
  };
  // the texts sent since the last look
  let seen = 0;
  const sent = () => {
    const texts = calls.slice(seen).filter((c) => c.method === 'sendMessage');
    seen = calls.length;
    return texts;
  };
  return { calls, fetch, sent };
}

// server.coop with a world of two players and three saves; what the bot did is in done
function fakeCoop(extra = {}) {
  let settings = normalizeSettings();
  const events = new EventEmitter();
  const done = [];
  const logs = [
    { player: 'друг', file: 'xray_friend.log', size: 2048, time: Date.parse('2026-10-30T18:00:00') },
    { player: 'друг', file: 'crash.mdmp', size: 3 * 1024 * 1024, time: Date.parse('2026-10-30T17:00:00') },
    { player: 'artem', file: 'xray_artem.log', size: 100, time: Date.parse('2026-10-29T12:00:00') },
  ];
  const coop = {
    online: [
      { id: 1, name: 'artem', level: 'l01_escape', master: true, ping: 42 },
      { id: 2, name: 'друг', level: null, master: false, ping: null },
    ],
    status: () => ({
      online: coop.online,
      world: { owner: 'artem', revision: 12 },
      paused: null,
      saves: [
        { revision: 12, time: Date.now(), name: '', reason: 'auto', who: '' },
        { revision: 11, time: Date.now(), name: '', reason: 'join', who: 'друг' },
        { revision: 10, time: Date.now(), name: 'перед боем', reason: 'named', who: 'artem' },
      ],
      ...(coop.host ? { host: coop.host } : {}),
    }),
    settings: () => settings,
    saveSettings: (s) => (settings = normalizeSettings(s)),
    rollback: (revision) => (done.push(['rollback', revision]), revision + 100),
    resetWorld: () => (done.push(['reset']), !coop.online.length),
    logs: () => logs,
    logFile: (player, file) => (logs.some((l) => l.player === player && l.file === file) ? Buffer.from(`log of ${player}: ${file}`) : null),
    on: (event, handler) => events.on(event, handler),
    emit: (event, data) => events.emit(event, data),
    done,
    ...extra,
  };
  return coop;
}

function start({ coop = fakeCoop(), poll, admins = [ADMIN] } = {}) {
  const tg = fakeTelegram(poll);
  const lines = [];
  const bot = startTelegram({ token: '1:T', admins, coop, fetch: tg.fetch, log: (l) => lines.push(l), retryMs: 1 });
  let next = 1;
  // a message from a user, as getUpdates brings it, handled
  const say = (text, from = ADMIN) => bot.handleUpdate({ update_id: next++,
    message: { message_id: next, date: Math.floor(Date.now() / 1000), chat: { id: from }, from: { id: from, username: 'u' + from }, text } });
  const press = (data, from = ADMIN) => bot.handleUpdate({ update_id: next++,
    callback_query: { id: 'q' + next, from: { id: from }, data, message: { message_id: 1, chat: { id: from } } } });
  return { ...tg, bot, coop, lines, say, press };
}

test('telegram: only admins; anyone else is told once, with their id', async () => {
  const t = start();
  try {
    await t.say('/status', OTHER);
    await t.say('/reset_world', OTHER);
    const sent = t.sent();
    assert.equal(sent.length, 1);
    assert.equal(sent[0].body.chat_id, OTHER);
    assert.match(sent[0].body.text, /только админам.*999/);
    assert.match(t.lines.join('\n'), /u999.*999.*not an admin/);
    assert.deepEqual(t.coop.done, []);

    await t.say('/status');
    assert.equal(t.sent()[0].body.chat_id, ADMIN);
  } finally {
    await t.bot.stop();
  }
});

test('telegram: /status lists players, the world, saves and the host when there is one', async () => {
  const t = start();
  try {
    await t.say('/status');
    let text = t.sent()[0].body.text;
    assert.match(text, /Онлайн: 2 из 4/);
    assert.match(text, /artem — l01_escape, 42 мс, мастер/);
    assert.match(text, /друг — в меню/);
    assert.match(text, /ревизия 12, сейв artem/);
    assert.match(text, /№11 · Вход: друг/);
    assert.doesNotMatch(text, /Хост/);

    t.coop.host = { running: true, memory: 812 * 1024 * 1024, uptime: 7500, pid: 4242, gave_up: false, connected: true,
      in_world: true, master: true };
    await t.say('/status@coop_bot');
    text = t.sent()[0].body.text;
    assert.match(text, /Хост: работает, 812\.0 МБ, запущен 2 ч 5 мин назад, держит мир/);
  } finally {
    await t.bot.stop();
  }
});

test('telegram: /settings shows the keys, /set changes them through saveSettings and checks the value', async () => {
  const t = start();
  try {
    await t.say('/settings');
    const text = t.sent()[0].body.text;
    assert.match(text, /story = да · Сюжет/);
    assert.match(text, /difficulty = 1 · Сложность игры \(1–3\)/);
    assert.match(text, /max_players = 4 · Игроков на сервере \(1–32\)/);

    await t.say('/set max_players 6');
    assert.equal(t.sent()[0].body.text, 'Игроков на сервере: 6');
    assert.equal(t.coop.settings().rules.max_players, 6);
    await t.say('/set story 0');
    assert.equal(t.coop.settings().world.story, false);
    await t.say('/set difficulty 3');
    assert.equal(t.coop.settings().world.difficulty, 3);
    t.sent();

    await t.say('/set max_players 99');
    await t.say('/set story maybe');
    await t.say('/set nope 1');
    await t.say('/set');
    const [range, bool, unknown, none] = t.sent().map((c) => c.body.text);
    assert.match(range, /от 1 до 32/);
    assert.match(bool, /«да» или «нет»/);
    assert.match(unknown, /Нет такой настройки: nope\. Ключи: story, .*max_players/);
    assert.match(none, /Ключи:/);
    assert.equal(t.coop.settings().rules.max_players, 6);
  } finally {
    await t.bot.stop();
  }
});

test('telegram: /factions lists them and turns them on and off, never all off', async () => {
  const t = start();
  try {
    await t.say('/factions');
    assert.match(t.sent()[0].body.text, /isg · ИСГ — нет/);
    await t.say('/factions isg on');
    assert.match(t.sent()[0].body.text, /isg · ИСГ — да/);
    assert.equal(t.coop.settings().factions.includes('isg'), true);
    await t.say('/factions dolg off');
    assert.equal(t.coop.settings().factions.includes('dolg'), false);
    await t.say('/factions zombied on');
    assert.match(t.sent()[1].body.text, /Нет такой фракции/);

    t.coop.saveSettings({ ...t.coop.settings(), factions: ['army'] });
    await t.say('/factions army off');
    assert.match(t.sent()[0].body.text, /хотя бы одна/);
    assert.deepEqual(t.coop.settings().factions, ['army']);
  } finally {
    await t.bot.stop();
  }
});

test('telegram: /save, /restart_host, /kick: said not to be there yet until the server has them', async () => {
  let t = start();
  try {
    await t.say('/save');
    await t.say('/restart_host');
    await t.say('/kick друг');
    assert.deepEqual(t.sent().map((c) => c.body.text), Array(3).fill('Сервер этого пока не умеет.'));
  } finally {
    await t.bot.stop();
  }

  const asked = [];
  t = start({ coop: fakeCoop({
    saveWorld: async () => (asked.push('save'), true),
    restartHost: () => (asked.push('restart'), false),
    kick: (name) => (asked.push(name), name === 'Меченый Стрелок'),
  }) });
  try {
    await t.say('/save');
    await t.say('/restart_host');
    await t.say('/kick Меченый Стрелок');
    await t.say('/kick никто');
    await t.say('/kick');
    assert.deepEqual(asked, ['save', 'restart', 'Меченый Стрелок', 'никто']);
    const [save, restart, kicked, nobody, who] = t.sent().map((c) => c.body.text);
    assert.equal(save, 'Мир сохраняется.');
    assert.match(restart, /Хоста нет/);
    assert.equal(kicked, 'Отключён: Меченый Стрелок');
    assert.match(nobody, /Нет такого игрока онлайн: никто/);
    assert.match(who, /Кого\?/);
  } finally {
    await t.bot.stop();
  }
});

test('telegram: /rollback and /reset_world wait for a confirmation, a minute at most', async (ctx) => {
  ctx.mock.timers.enable({ apis: ['Date'], now: Date.parse('2026-10-30T18:00:00') });
  const t = start();
  try {
    await t.say('/rollback 9');
    assert.match(t.sent()[0].body.text, /Нет сохранения №9/);
    await t.say('/rollback 12');
    assert.match(t.sent()[0].body.text, /№12 — это мир сейчас/);

    await t.say('/rollback 10');
    const ask = t.sent()[0].body;
    assert.match(ask.text, /Откатить мир к №10 · «перед боем» · artem/);
    const [yes, no] = ask.reply_markup.inline_keyboard[0];
    assert.equal(no.text, 'Отмена');
    assert.deepEqual(t.coop.done, []);
    await t.say('/confirm');
    assert.deepEqual(t.coop.done, [['rollback', 10]]);
    assert.equal(t.sent()[0].body.text, 'Мир возвращён к №10.');
    await t.press(yes.callback_data); // used already
    await t.say('/confirm');
    assert.deepEqual(t.sent().map((c) => c.body.text), ['Это уже неактуально.', 'Нечего подтверждать.']);
    assert.equal(t.calls.filter((c) => c.method === 'answerCallbackQuery').length, 1);

    // players online: not even asked
    await t.say('/reset_world');
    assert.match(t.sent()[0].body.text, /все игроки должны выйти/);
    t.coop.online = [];

    await t.say('/reset_world');
    let buttons = t.sent()[0].body.reply_markup.inline_keyboard[0];
    await t.press(buttons[1].callback_data); // cancel
    await t.press(buttons[0].callback_data);
    assert.deepEqual(t.sent().map((c) => c.body.text), ['Отменено.', 'Это уже неактуально.']);
    assert.deepEqual(t.coop.done, [['rollback', 10]]);

    await t.say('/reset_world');
    buttons = t.sent()[0].body.reply_markup.inline_keyboard[0];
    ctx.mock.timers.tick(61000);
    await t.press(buttons[0].callback_data);
    assert.equal(t.sent()[0].body.text, 'Это уже неактуально.');

    await t.say('/reset_world');
    buttons = t.sent()[0].body.reply_markup.inline_keyboard[0];
    await t.press(buttons[0].callback_data, OTHER); // not an admin
    assert.deepEqual(t.coop.done, [['rollback', 10]]);
    await t.press(buttons[0].callback_data);
    assert.deepEqual(t.coop.done, [['rollback', 10], ['reset']]);
    assert.match(t.sent().at(-1).body.text, /Мир удалён/);
  } finally {
    await t.bot.stop();
  }
});

test('telegram: /logs lists who has them and a player\'s files; a file goes as a document', async () => {
  const t = start();
  try {
    await t.say('/logs');
    assert.match(t.sent()[0].body.text, /друг \(2\), artem \(1\)/);
    await t.say('/logs никто');
    assert.match(t.sent()[0].body.text, /Нет логов у никто/);

    await t.say('/logs друг');
    const list = t.sent()[0].body;
    assert.match(list.text, /xray_friend\.log · 2 КБ/);
    assert.match(list.text, /crash\.mdmp · 3\.0 МБ/);
    assert.deepEqual(list.reply_markup.inline_keyboard.map((row) => row[0].text), ['xray_friend.log', 'crash.mdmp']);

    const document = async () => {
      const call = t.calls.findLast((c) => c.method === 'sendDocument');
      const file = call.body.get('document');
      return [call.body.get('chat_id'), call.body.get('caption'), file.name, await file.text()];
    };
    await t.press(list.reply_markup.inline_keyboard[1][0].callback_data);
    assert.deepEqual(await document(), [String(ADMIN), 'друг · crash.mdmp', 'crash.mdmp', 'log of друг: crash.mdmp']);
    await t.say('/logs друг xray_friend.log');
    assert.deepEqual(await document(), [String(ADMIN), 'друг · xray_friend.log', 'xray_friend.log', 'log of друг: xray_friend.log']);
    assert.equal(t.sent().length, 0);
  } finally {
    await t.bot.stop();
  }
});

test('telegram: news for every admin from the server\'s events; none without events', async () => {
  const t = start({ admins: [ADMIN, 222] });
  try {
    t.coop.emit('joined', { name: 'друг' });
    t.coop.emit('left', 'artem');
    t.coop.emit('host_down', { code: 3, restarting: false });
    t.coop.emit('host_up');
    t.coop.emit('save_failed', { reason: 'хост не ответил' });
    await new Promise((r) => setImmediate(r));
    const news = t.sent().map((c) => [c.body.chat_id, c.body.text]);
    assert.deepEqual(news.filter(([chat]) => chat === 222).map(([, text]) => text), [
      'Вошёл: друг', 'Вышел: artem', 'Хост упал (код 3). Больше не перезапускается: /restart_host', 'Хост запущен.',
      'Мир не сохранился: хост не ответил',
    ]);
    assert.equal(news.length, 10);
  } finally {
    await t.bot.stop();
  }

  const quiet = start({ coop: fakeCoop({ on: undefined }) });
  await quiet.bot.stop();
  assert.match(quiet.lines.join('\n'), /no events/);
});

test('telegram: polling sets the commands, follows the offset, waits out network errors, stops on a bad token', async () => {
  const offsets = [];
  let calls = 0;
  const t = start({
    poll: async (body, signal) => {
      offsets.push(body.offset);
      calls++;
      if (calls === 1) throw new TypeError('fetch failed');
      if (calls === 2) return json({ ok: true, result: [
        { update_id: 5, message: { message_id: 1, date: Math.floor(Date.now() / 1000), chat: { id: ADMIN }, from: { id: ADMIN }, text: '/help' } },
        { update_id: 6, message: { message_id: 2, date: Math.floor(Date.now() / 1000) - 3600, chat: { id: ADMIN }, from: { id: ADMIN }, text: '/reset_world' } },
      ] });
      if (calls === 3) return json({ ok: false, error_code: 502, description: 'Bad Gateway' }, 502);
      if (calls === 4) return json({ ok: true, result: [] });
      return json({ ok: false, error_code: 401, description: 'Unauthorized' }, 401);
    },
  });
  for (let i = 0; i < 100 && !t.lines.some((l) => /token/.test(l)); i++) await new Promise((r) => setTimeout(r, 10));
  assert.equal(t.calls[0].method, 'setMyCommands');
  assert.ok(t.calls[0].body.commands.some((c) => c.command === 'reset_world'));
  assert.deepEqual(offsets, [0, 0, 7, 7, 7]);
  // the old command (sent an hour ago) is dropped: only /help answered
  const sent = t.sent();
  assert.equal(sent.length, 1);
  assert.match(sent[0].body.text, /\/status — /);
  assert.match(t.lines.join('\n'), /fetch failed, trying again[\s\S]*reached again[\s\S]*Bad Gateway[\s\S]*does not know this token/);
  await t.bot.stop();
});

test('telegram: /event calm start <level> passes the level; the list shows the Zone\'s events and their levels', async () => {
  const done = [];
  const coop = fakeCoop({
    events: () => ({ values: { calm: '1', calm_level: 'l08_yantar', calm_left: '3600', calm_levels: 'l08_yantar:Янтарь,k00_marsh:Болота', factor: '6' } }),
    worldEvent: (...args) => (done.push(args), 'ok'),
  });
  const t = start({ coop });
  try {
    await t.say('/event');
    const list = t.sent()[0].body.text;
    assert.match(list, /Мёртвый штиль: идёт, Янтарь, ещё 1 ч 0 мин/);
    assert.match(list, /calm: локации l08_yantar, k00_marsh/);
    await t.say('/event calm start k00_marsh');
    assert.deepEqual(done.at(-1), ['calm', 'start', 'бот', 'k00_marsh']);
    await t.say('/event calm outcome');
    assert.deepEqual(done.at(-1), ['calm', 'outcome', 'бот', '']);
  } finally {
    await t.bot.stop();
  }
});

test('telegram: /event shows the world\'s events; a surge waits for a yes, the weather goes at once', async () => {
  const done = [];
  const coop = fakeCoop({
    events: () => ({ values: { surge: '0', surge_in: '7200', psi: '1', factor: '10', cool: 'off', bar_rule: '1', barman: '0', weather: 'rain' } }),
    worldEvent: (name, action, who) => (done.push([name, action, who]), `${name} ${action}: отправлено хосту.`),
  });
  const t = start({ coop });
  try {
    await t.say('/event');
    const list = t.sent()[0].body.text;
    assert.match(list, /Выброс: через 2 ч 0 мин \(~12 мин реальных\)/);
    assert.match(list, /Пси-шторм: идёт/);
    assert.match(list, /Охлаждение: не бывает/);
    assert.match(list, /Погода: дождь/);
    assert.match(list, /weather_storm — Погода: гроза/);
    await t.say('/event weather_storm');
    assert.deepEqual(done, [['weather_storm', 'start', 'бот']]);
    assert.match(t.sent()[0].body.text, /отправлено хосту/);
    await t.say('/event surge start');
    assert.match(t.sent()[0].body.text, /Выброс: начать\? .*погибнет/);
    assert.equal(done.length, 1);
    await t.say('/confirm');
    assert.deepEqual(done.at(-1), ['surge', 'start', 'бот']);
    await t.say('/event surge stop'); // safe: at once
    assert.deepEqual(done.at(-1), ['surge', 'stop', 'бот']);
  } finally {
    await t.bot.stop();
  }
});
