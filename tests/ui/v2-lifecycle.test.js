const { test, before } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
let T, createStore, forms;
before(async () => {
  await import('../../vendor/tanstack/index.js'); T = globalThis.TanStack;
  createStore = require('../../v2-store.js'); forms = require('../../v2-forms.js')(T);
});
const tick = () => new Promise(resolve => setImmediate(resolve));
const response = (data, status = 200) => ({ ok: status < 400, status, headers: new Headers({ 'x-correlation-id': 'fixture' }), json: async () => data });
async function ui() {
  const handlers = {}, requests = [];
  let actor = 'userA';
  const me = () => ({ user: { id: actor }, csrf: actor, workspaces: [{ id: 'wsA', role: 'admin' }] });
  const env = { location: { hash: '' }, fetch: async (url, opts) => {
    if (url.endsWith('/auth/me')) return response(me());
    if (url.endsWith('/auth/logout')) return response({});
    if (url.endsWith('/auth/login')) { actor = 'userB'; return response(me()); }
    return new Promise(resolve => requests.push({ url, opts, resolve }));
  } };
  const modules = createStore(T, env);
  const context = { ...modules, TanStack: T, V2Forms: forms, V2Capabilities: { capabilities: () => '' },
    document: { addEventListener: (event, fn) => { (handlers[event] ||= []).push(fn); }, querySelector: selector => selector === '.shell' ? {} : null },
    localStorage: { getItem: () => null, setItem() {} }, location: env.location, fetch: env.fetch,
    S: { page: 'v2src' }, M: [], layout() {}, page() {}, navPage: p => p, render() {}, addEventListener() {},
    FormData: class { constructor(form) { this.values = form.values; } *[Symbol.iterator]() { yield* Object.entries(this.values); } },
    badge: () => '', intro: () => '', Date, Proxy, console };
  vm.runInNewContext(fs.readFileSync(require.resolve('../../v2-ui.js'), 'utf8'), context);
  await tick();
  modules.V2Store.set({ cat: { objects: { old: { columns: [{ name: 'id', type: 'Int64' }] }, new: { columns: [{ name: 'id', type: 'Int64' }] } } },
    sel: 'connection', previewObject: 'old', filters: [], result: null });
  const submit = (kind, values) => {
    const form = { dataset: { v2Form: kind }, values, closest() { return this; }, querySelector: () => ({}), reset() {} };
    return handlers.submit[0]({ target: form, preventDefault() {} });
  };
  return { ...modules, context, requests, submit, handlers };
}
test('changing preview object discards an old response and frees the submit state', async () => {
  const h = await ui();
  const pending = h.submit('preview', { object: 'old', limit: '10' }); await tick();
  assert.equal(h.requests.length, 1);
  h.handlers.change[0]({ target: { matches: () => true, value: 'new', closest: () => null } });
  h.requests[0].resolve(response({ columns: [], rows: [['old object data']] })); await pending;
  assert.equal(h.V2Store.get('previewObject'), 'new');
  assert.equal(h.V2Store.get('result'), null);
  assert.equal(h.V2Store.get('previewBusy'), false);
  h.V2Query.clear();
});
test('old 401 cannot sign out a new login', async () => {
  const h = await ui();
  h.V2Store.set({ filters: [{ column: 'id', op: '=', value: 'private' }] });
  // Use a valid integer for the running preview, then change the local draft.
  h.V2Store.set({ filters: [] });
  const old = h.submit('preview', { object: 'old', limit: '10' }); await tick();
  h.V2Store.set({ filters: [{ column: 'id', op: '=', value: 'private' }] });
  await h.handlers.click[0]({ target: { closest: () => ({ dataset: { v2: 'logout' } }) } });
  await h.submit('login', { username: 'userB', password: 'synthetic' });
  assert.equal(h.V2Store.get('user').id, 'userB');
  h.requests[0].resolve(response({ error: { message: 'expired' } }, 401)); await old;
  assert.equal(h.V2Store.get('user').id, 'userB');
  h.V2Query.clear();
});
test('logout clears preview inputs before another session starts', async () => {
  const h = await ui();
  h.V2Store.set({ filters: [{ column: 'id', op: '=', value: 'private' }], previewObject: 'private_object' });
  await h.handlers.click[0]({ target: { closest: () => ({ dataset: { v2: 'logout' } }) } });
  assert.deepEqual(Array.from(h.V2Store.get('filters')), []);
  assert.equal(h.V2Store.get('previewObject'), '');
});
for (const status of [200, 500]) test('late connection deletion ' + status + ' cannot change another workspace', async () => {
  const h = await ui();
  const old = h.handlers.click[0]({ target: { closest: () => ({ dataset: { v2: 'del-conn', id: 'connection' } }) } });
  await tick();
  h.handlers.change[0]({ target: { matches: () => false, closest: selector => selector === '[data-v2-ws]' ? { value: 'wsB' } : null } });
  const result = { rows: [['workspace B']] };
  h.V2Store.set({ sel: 'connectionB', result });
  h.requests[0].resolve(response({ error: { message: 'old failure' } }, status)); await old;
  assert.equal(h.V2Store.get('sel'), 'connectionB');
  assert.equal(h.V2Store.get('result'), result);
  assert.equal(h.V2Store.get('error'), '');
  h.V2Query.clear();
});
test('catalog refresh ignores callbacks from the pre-refresh GET', async () => {
  const h = await ui();
  h.V2Store.set({ conns: [{ id: 'connection', name: 'Source' }], cat: null, catall: { objects: [] }, reqs: [] });
  h.context.page(); await tick();
  const old = h.requests.find(r => r.url.endsWith('/catalog'));
  assert.ok(old);
  const refreshing = h.handlers.click[0]({ target: { closest: () => ({ dataset: { v2: 'refresh-cat' } }) } });
  await tick();
  h.requests.find(r => r.url.endsWith('/catalog/refresh')).resolve(response({ revision: 2, objects: 0 }));
  await refreshing;
  h.context.page(); await tick();
  const catalog = h.requests.filter(r => r.url.endsWith('/catalog'));
  assert.equal(catalog.length, 2);
  old.resolve(response({ revision: 1, objects: {} })); await tick();
  assert.equal(h.V2Store.get('cat'), null);
  catalog[1].resolve(response({ revision: 2, objects: {} })); await tick();
  assert.equal(h.V2Store.get('cat').revision, 2);
  h.V2Query.clear();
});
