const { test, before, afterEach } = require('node:test');
const assert = require('node:assert/strict');
let create, T;
const clients = [];
afterEach(() => clients.splice(0).forEach(q => q.clear()));
before(async () => {
  await import('../../vendor/tanstack/index.js'); T = globalThis.TanStack;
  create = require('../../v2-store.js');
});
function setup(fetch) {
  const events = {};
  const env = { fetch, location: { hash: '' }, addEventListener: (n, fn) => { events[n] = fn; } };
  const modules = create(T, env); clients.push(modules.V2Query);
  return { ...modules, env, events };
}
const response = (data, status = 200) => ({ ok: status < 400, status, headers: new Headers(), json: async () => data });
test('two simultaneous fetch calls with the same key make one request', async () => {
  let count = 0;
  const { V2Query: q } = setup(async () => { count++; return response([1]); });
  assert.deepEqual(await Promise.all([q.fetch(['a'], '/a'), q.fetch(['a'], '/a')]), [[1], [1]]);
  assert.equal(count, 1);
});
test('invalidate refetches on next fetch', async () => {
  let count = 0;
  const { V2Query: q } = setup(async () => response(++count));
  assert.equal(await q.fetch(['ws', 'a'], '/a'), 1);
  q.invalidate(['ws']);
  assert.equal(await q.fetch(['ws', 'a'], '/a'), 2);
});
test('non-2xx rejects with status and never retries', async () => {
  let count = 0;
  const { V2Query: q } = setup(async () => { count++; return response({ error: { message: 'busy' } }, 429); });
  await assert.rejects(q.fetch(['a'], '/a'), { status: 429, message: 'busy' });
  assert.equal(count, 1);
});
test('route round trips a source connection and malformed hashes fall back', () => {
  const { V2Route: r, env } = setup();
  const id = 'af3dc629-2720-4bbb-9301-685c063a7714';
  r.go('sources', { connection: id });
  assert.equal(env.location.hash, '#/sources/' + id);
  assert.deepEqual(r.current(), { page: 'sources', connection: id });
  for (const hash of ['#/%', '#/sources/../../bad', '#/unknown', '#/sources/invalid', '#/sources/x?y']) {
    env.location.hash = hash; assert.deepEqual(r.current(), { page: 'sources' });
  }
});
test('store notifies subscribers and stops on unsubscribe', () => {
  const { V2Store: s } = setup();
  let count = 0; const unsubscribe = s.subscribe(() => count++);
  s.set({ ws: 'one' }); assert.equal(s.get('ws'), 'one'); assert.equal(count, 1);
  unsubscribe(); s.set({ ws: 'two' }); assert.equal(count, 1);
});
test('Source activity has its own hash route', () => {
  const { V2Route: route } = setup();
  route.go('source-activity');
  assert.deepEqual(route.current(), { page: 'source-activity' });
});
test('clearing query state cancels an old session response', async () => {
  let complete;
  const { V2Query: q } = setup(() => new Promise(resolve => { complete = () => resolve(response('private')); }));
  const pending = q.fetch(['old'], '/old').catch(() => 'cancelled');
  q.clear(); complete();
  assert.equal(await pending, 'cancelled');
});
test('invalidation while a GET is pending cannot reuse the old response', async () => {
  const requests = [];
  const { V2Query: q } = setup(() => new Promise(resolve => requests.push(resolve)));
  const old = q.fetch(['catalog'], '/catalog').catch(() => 'cancelled');
  q.invalidate(['catalog']);
  const fresh = q.fetch(['catalog'], '/catalog');
  assert.equal(requests.length, 2);
  requests[0](response({ revision: 1 })); requests[1](response({ revision: 2 }));
  await old;
  assert.deepEqual(await fresh, { revision: 2 });
  assert.deepEqual(await q.fetch(['catalog'], '/catalog'), { revision: 2 });
});
