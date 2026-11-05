import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createClock } from '../src/clock.js';

test('clock: runs at its factor only while running, jumps, factor changes, set back, kept', () => {
  let real = 1000;
  let saved = null;
  const make = () => createClock({ load: () => saved, save: (s) => (saved = s), now: () => real });
  const clock = make();
  assert.equal(clock.isSet(), false);
  assert.equal(clock.init(0, 6), false); // no time
  assert.equal(clock.init(5_000_000, 6), true);
  assert.equal(clock.init(9, 6), false); // the first one stays
  real += 1000;
  assert.equal(clock.now(), 5_000_000); // stands until someone is in the world
  clock.setRunning(true);
  real += 1000;
  assert.equal(clock.now(), 5_006_000);
  clock.setFactor(10);
  real += 1000;
  assert.equal(clock.now(), 5_016_000);
  assert.equal(clock.epoch(), 1);
  clock.jump(3_600_000);
  assert.equal(clock.now(), 8_616_000);
  assert.equal(clock.epoch(), 2);
  clock.setRunning(false);
  real += 5000;
  assert.equal(clock.now(), 8_616_000);
  assert.deepEqual(saved, { game: 8_616_000, factor: 10, epoch: 2 });
  clock.set(6_000_000);
  assert.equal(clock.now(), 6_000_000);
  assert.equal(clock.epoch(), 3);

  // a restart finds it as it was, standing
  const again = make();
  assert.equal(again.now(), 6_000_000);
  assert.equal(again.running(), false);
  again.clear();
  assert.equal(saved, null);
});
