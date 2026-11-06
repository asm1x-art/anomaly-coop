import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createNews, parseNews } from '../src/news.js';

test('news: only important types, the last ones kept, the same one not twice, kept through save/load', () => {
  let saved = null;
  const open = () => createNews({ load: () => saved, save: (l) => { saved = l; }, types: ['cooling', 'surge'], keep: 3, now: () => 1000 });
  const news = open();
  assert.equal(parseNews('cooling\tonly two'), null);
  assert.equal(parseNews('Bad type!\tx\ty'), null);
  assert.deepEqual(parseNews(' COOLING \t 01.01 10:00 \t окно   открыто '), { type: 'cooling', world: '01.01 10:00', text: 'окно открыто' });
  assert.equal(news.add('trade\t1\tпатроны'), null);
  assert.ok(news.add('cooling\t1\tокно открыто', 'Мастер'));
  assert.equal(news.add('cooling\t1\tокно открыто', 'Другой мастер'), null);
  for (let i = 2; i <= 5; i++) assert.ok(news.add(`surge\t${i}\tвыброс ${i}`));
  assert.deepEqual(news.list().map((n) => n.world), ['3', '4', '5']);
  assert.deepEqual(news.list().map((n) => n.id), [3, 4, 5]);
  const again = open();
  assert.deepEqual(again.list().map((n) => n.text), ['выброс 3', 'выброс 4', 'выброс 5']);
  assert.equal(again.add('surge\t6\tвыброс 6').id, 6);
  again.clear();
  assert.deepEqual(open().list(), []);
});
