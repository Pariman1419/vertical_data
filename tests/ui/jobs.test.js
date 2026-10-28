const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mountJobs } = require('../../v2-jobs.js');

class Node {
  constructor(tag, doc) {
    this.tagName = tag;
    this.ownerDocument = doc;
    this.children = [];
    this.listeners = {};
    this.attributes = {};
    this.value = '';
    this.style = {};
    this.disabled = false;
  }
  set textContent(value) {
    this.text = String(value);
    this.children = [];
  }
  get textContent() {
    return (this.text || '') + this.children.map(c => c.textContent).join('');
  }
  append(...nodes) {
    this.children.push(...nodes);
  }
  replaceChildren(...nodes) {
    this.text = '';
    this.children = nodes;
  }
  setAttribute(key, value) {
    this.attributes[key] = value;
  }
  addEventListener(event, fn) {
    this.listeners[event] = fn;
  }
  all(tag) {
    return [...(this.tagName === tag ? [this] : []), ...this.children.flatMap(c => c.all(tag))];
  }
}

function setup() {
  const doc = { createElement: tag => new Node(tag, doc) };
  return new Node('div', doc);
}

const tick = () => new Promise(resolve => setTimeout(resolve, 10));

test('Jobs UI renders dead-letter banner when dead letters are present', async () => {
  const root = setup();
  const deadLetters = [
    { run_id: 'dl-1', pipeline_name: 'orders_etl', reason: 'flight_timeout', at: '2026-10-28T10:00:00Z' }
  ];
  const runs = [
    { id: 'run-1', pipeline_name: 'orders_etl', state: 'dead', rows_read: 100, attempt: 3, max_attempts: 3, created_at: '2026-10-28T09:50:00Z' }
  ];

  const api = {
    fetch: async (key, path) => {
      if (path.includes('dead-letters')) return deadLetters;
      if (path.includes('runs')) return runs;
      return [];
    },
    invalidate: () => {}
  };

  const view = mountJobs(root, { workspace: 'ws-test', query: api, role: 'operator' });
  await tick();

  assert.ok(root.textContent.includes('Dead-Lettered Job'));
  assert.ok(root.textContent.includes('orders_etl'));
  assert.ok(root.textContent.includes('flight_timeout'));

  view.destroy();
});

test('Jobs UI renders runs table with status badges and progress bar', async () => {
  const root = setup();
  const runs = [
    { id: 'run-active', pipeline_name: 'active_pipeline', state: 'running', rows_read: 2500000, attempt: 1, max_attempts: 3, created_at: '2026-10-28T10:10:00Z' },
    { id: 'run-done', pipeline_name: 'done_pipeline', state: 'succeeded', rows_read: 5000000, attempt: 1, max_attempts: 3, created_at: '2026-10-28T10:00:00Z' }
  ];

  const api = {
    fetch: async (key, path) => {
      if (path.includes('dead-letters')) return [];
      if (path.includes('runs')) return runs;
      return [];
    },
    invalidate: () => {}
  };

  const view = mountJobs(root, { workspace: 'ws-test', query: api, role: 'operator' });
  await tick();

  assert.ok(root.textContent.includes('active_pipeline'));
  assert.ok(root.textContent.includes('Running'));
  assert.ok(root.textContent.includes('2,500,000 rows'));
  assert.ok(root.textContent.includes('Succeeded'));

  // Cancel button rendered for running job
  const buttons = root.all('button');
  const cancelBtn = buttons.find(b => b.textContent === 'Cancel');
  assert.ok(cancelBtn, 'Cancel button should be present for running run');
  assert.equal(cancelBtn.disabled, false, 'Cancel button enabled for operator');

  view.destroy();
});

test('Viewer role has Cancel and Retry buttons disabled', async () => {
  const root = setup();
  const runs = [
    { id: 'run-1', pipeline_name: 'p1', state: 'running', rows_read: 100, attempt: 1, max_attempts: 3 },
    { id: 'run-2', pipeline_name: 'p2', state: 'failed', rows_read: 0, attempt: 1, max_attempts: 3 }
  ];

  const api = {
    fetch: async (key, path) => (path.includes('dead-letters') ? [] : runs),
    invalidate: () => {}
  };

  const view = mountJobs(root, { workspace: 'ws-test', query: api, role: 'viewer' });
  await tick();

  const buttons = root.all('button');
  const cancelBtn = buttons.find(b => b.textContent === 'Cancel');
  const retryBtn = buttons.find(b => b.textContent === 'Retry');

  assert.ok(cancelBtn && cancelBtn.disabled === true, 'Cancel disabled for viewer');
  assert.ok(retryBtn && retryBtn.disabled === true, 'Retry disabled for viewer');

  view.destroy();
});

test('Clicking Retry calls retry endpoint and invalidates query', async () => {
  const root = setup();
  const runs = [
    { id: 'run-dead', pipeline_name: 'failed_pipe', state: 'dead', rows_read: 0, attempt: 3, max_attempts: 3 }
  ];
  const postCalls = [];
  const invalidations = [];

  const api = {
    fetch: async (key, path, opts) => {
      if (opts?.method === 'POST') {
        postCalls.push(path);
        return { state: 'queued' };
      }
      return path.includes('dead-letters') ? [] : runs;
    },
    invalidate: key => invalidations.push(key)
  };

  const view = mountJobs(root, { workspace: 'ws-test', query: api, role: 'operator' });
  await tick();

  const retryBtn = root.all('button').find(b => b.textContent === 'Retry');
  assert.ok(retryBtn);
  await retryBtn.listeners.click();

  assert.ok(postCalls.some(p => p.includes('/runs/run-dead/retry')));
  assert.ok(invalidations.some(k => k[0] === 'runs'));

  view.destroy();
});
