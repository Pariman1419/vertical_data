// Task 1: Source activity only. Jobs/worker controls belong to later tasks.
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.V2Activity = factory();
})(globalThis, function () {
  'use strict';
  const kinds = { queue_wait: ['Queue wait', 'warn'], busy_429: ['Busy (429)', 'warn'], timeout: ['Timeout', 'err'],
    read_ok: ['Read OK', 'ok'], read_error: ['Read error', 'err'] };
  function query(filters = {}, cursor = null) {
    const params = new URLSearchParams({ limit: '100' });
    if (filters.kind) {
      if (!Object.hasOwn(kinds, filters.kind)) throw new Error('Choose a supported event kind.');
      params.set('kind', filters.kind);
    }
    if (filters.dataset) {
      if (filters.dataset.length > 200 || !/^[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+){0,2}$/.test(filters.dataset)) throw new Error('Use a dataset name containing letters, numbers and underscores.');
      params.set('dataset', filters.dataset);
    }
    if (filters.since) {
      if (!Number.isFinite(Date.parse(filters.since))) throw new Error('Choose a valid time range.');
      params.set('since', filters.since);
    }
    if (cursor) {
      if (!/^[1-9][0-9]{0,18}$/.test(String(cursor))) throw new Error('Invalid page cursor.');
      params.set('cursor', String(cursor));
    }
    return params.toString();
  }
  function mount(root, { workspace, query: client, onUnauthorized = () => {} }) {
    const doc = root.ownerDocument;
    let destroyed = false, generation = 0, next = null, activeFilters = null;
    const controllers = new Set();
    const make = (tag, className = '', text) => { const node = doc.createElement(tag); node.className = className; if (text !== undefined) node.textContent = text; return node; };
    const form = make('form', 'card v2-activity-filters');
    function select(labelText, entries) {
      const label = make('label', 'field', labelText), node = make('select');
      for (const [value, text] of entries) { const option = make('option', '', text); option.value = value; node.append(option); }
      label.append(node); form.append(label); return node;
    }
    const range = select('Time range', [['24', 'Last 24 hours'], ['1', 'Last hour'], ['168', 'Last 7 days'], ['720', 'Last 30 days'], ['', 'All retained events']]);
    range.value = '24';
    const kind = select('Event kind', [['', 'All events'], ...Object.entries(kinds).map(([key, value]) => [key, value[0]])]);
    const datasetLabel = make('label', 'field', 'Dataset'), dataset = make('input');
    dataset.type = 'search'; dataset.maxLength = 200; dataset.placeholder = 'All datasets'; datasetLabel.append(dataset); form.append(datasetLabel);
    const refresh = make('button', 'primary', 'Refresh'); refresh.type = 'submit'; form.append(refresh);
    const status = make('p', 'muted'); status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
    const content = make('div', 'card tablewrap');
    const controls = make('div', 'actions'), first = make('button', '', 'First page'), more = make('button', '', 'Next page');
    first.type = more.type = 'button'; controls.append(first, more);
    root.replaceChildren(form, status, content, controls);
    async function load(cursor = null, invalidate = false) {
      const own = ++generation;
      let params;
      try {
        if (!cursor) activeFilters = { kind: kind.value, dataset: dataset.value,
          since: range.value ? new Date(Date.now() - Number(range.value) * 3600000).toISOString() : null };
        params = query(activeFilters, cursor);
      } catch (error) { status.textContent = error.message; refresh.disabled = false; more.disabled = first.disabled = true; return; }
      if (invalidate) client.invalidate(['source-activity', workspace]);
      refresh.disabled = more.disabled = first.disabled = true;
      status.textContent = 'Loading source activity…';
      const controller = new AbortController(); controllers.add(controller);
      try {
        const data = await client.fetch(['source-activity', workspace, params],
          '/api/v2/workspaces/' + encodeURIComponent(workspace) + '/source-activity?' + params, { signal: controller.signal });
        if (destroyed || own !== generation) return;
        next = data.next_cursor;
        const table = make('table', 'table'), header = make('tr'), head = make('thead'), body = make('tbody');
        for (const name of ['Time', 'Dataset', 'User', 'Event', 'Wait (ms)', 'Rows', 'Bytes']) header.append(make('th', '', name));
        head.append(header); table.append(head, body);
        for (const item of data.items) {
          const row = make('tr');
          for (const value of [item.at, item.dataset, item.user_id]) row.append(make('td', '', value ?? '—'));
          const event = make('td'), badge = kinds[item.kind] || ['Unknown', 'warn'];
          event.append(make('span', 'badge ' + badge[1], badge[0])); row.append(event);
          for (const value of [item.waited_ms, item.rows, item.bytes]) row.append(make('td', '', value ?? '—'));
          body.append(row);
        }
        content.replaceChildren(...(data.items.length ? [table] : [make('p', 'muted', 'No source activity for these filters.')]));
        status.textContent = data.items.length + ' events' + (next ? ' · more available' : '');
        more.disabled = !next; first.disabled = !cursor;
      } catch (error) {
        if (!destroyed && own === generation) {
          if (error.status === 401) { onUnauthorized(); return; }
          status.textContent = error.message || 'Could not load source activity.'; content.replaceChildren();
        }
      } finally {
        controllers.delete(controller);
        if (!destroyed && own === generation) refresh.disabled = false;
      }
    }
    form.addEventListener('submit', event => { event.preventDefault(); load(null, true); });
    more.addEventListener('click', () => { if (next) load(next); });
    first.addEventListener('click', () => load());
    load();
    return { destroy() { destroyed = true; generation++; for (const controller of controllers) controller.abort(); controllers.clear(); root.replaceChildren(); } };
  }
  return { mount, query };
});
