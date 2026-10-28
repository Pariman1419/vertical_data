const { test } = require('node:test');
const assert = require('node:assert/strict');
const make = () => require('../../v2-jobs.js');
class Node {
  constructor(tag, doc) { this.tagName = tag; this.ownerDocument = doc; this.children = []; this.listeners = {}; this.attributes = {}; this.value = ''; this.dataset = {}; }
  set textContent(value) { this.text = String(value); this.children = []; }
  get textContent() { return (this.text || '') + this.children.map(c => c.textContent).join(''); }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.text = ''; this.children = nodes; }
  setAttribute(key, value) { this.attributes[key] = value; }
  addEventListener(event, fn) { this.listeners[event] = fn; }
  set innerHTML(value) { throw new Error('data must never use innerHTML'); }
  all(tag) { return [...(this.tagName === tag ? [this] : []), ...this.children.flatMap(c => c.all(tag))]; }
}
function setup(query) { const doc = { createElement: tag => new Node(tag, doc) }; return new Node('div', doc); }
const tick = () => new Promise(resolve => setImmediate(resolve));
test('activity filters produce only supported parameters and cursor pagination', () => {
  const q = make().query({ kind: 'timeout', dataset: 'cycletime_mock', since: '2026-10-28T00:00:00Z' }, '9007199254740993');
  const params = new URLSearchParams(q);
  assert.equal(params.get('limit'), '100'); assert.equal(params.get('kind'), 'timeout');
  assert.equal(params.get('cursor'), '9007199254740993');
  assert.throws(() => make().query({ dataset: "SELECT token; --" }));
});
test('activity page renders inert text, badges, metrics and empty state', async () => {
  const root = setup();
  const api = { fetch: async () => ({ items: [{ at: '2026-10-28T00:00:00Z', kind: 'read_ok', dataset: '<script>evil</script>', user_id: 'fixture-user', waited_ms: '12', rows: '9007199254740993', bytes: '20' }], next_cursor: null }), invalidate() {} };
  const view = make().mount(root, { workspace: 'one', query: api }); await tick();
  assert.ok(root.textContent.includes('<script>evil</script>'));
  assert.ok(root.textContent.includes('9007199254740993'));
  assert.ok(root.all('span').some(n => n.className.includes('badge') && n.textContent.includes('Read OK')));
  assert.equal(root.all('script').length, 0);
  view.destroy();
  const empty = make().mount(root, { workspace: 'one', query: { ...api, fetch: async () => ({ items: [], next_cursor: null }) } });
  await tick(); assert.ok(root.textContent.includes('No source activity')); empty.destroy();
});
test('activity refresh uses filters, pagination is bounded and old workspace response is ignored', async () => {
  const root = setup(), requests = [], invalidations = [];
  const api = { fetch: (key, path) => new Promise(resolve => requests.push({ key, path, resolve })), invalidate: key => invalidations.push(key) };
  const first = make().mount(root, { workspace: 'one', query: api });
  first.destroy();
  const second = make().mount(root, { workspace: 'two', query: api });
  requests[0].resolve({ items: [{ dataset: 'private_old_workspace', kind: 'timeout' }], next_cursor: null });
  requests[1].resolve({ items: [], next_cursor: '500' }); await tick();
  assert.ok(!root.textContent.includes('private_old_workspace'));
  const next = root.all('button').find(b => b.textContent === 'Next page');
  next.listeners.click(); assert.ok(requests[2].path.includes('cursor=500'));
  assert.equal(new URLSearchParams(requests[1].path.split('?')[1]).get('since'), new URLSearchParams(requests[2].path.split('?')[1]).get('since'));
  requests[2].resolve({ items: [], next_cursor: null }); await tick();
  root.all('input')[0].value = 'cycletime_mock';
  root.all('form')[0].listeners.submit({ preventDefault() {} });
  assert.ok(requests[3].path.includes('dataset=cycletime_mock'));
  assert.equal(invalidations.length, 1);
  second.destroy(); requests[3].resolve({ items: [], next_cursor: null });
});
test('an expired session is handled only while its activity view is current', async () => {
  let reject, expired = 0;
  const root = setup(), api = { fetch: () => new Promise((_, failure) => { reject = failure; }), invalidate() {} };
  const first = make().mount(root, { workspace: 'one', query: api, onUnauthorized: () => expired++ });
  first.destroy(); reject({ status: 401 }); await tick(); assert.equal(expired, 0);
  const second = make().mount(root, { workspace: 'two', query: api, onUnauthorized: () => expired++ });
  reject({ status: 401 }); await tick(); assert.equal(expired, 1); second.destroy();
});
