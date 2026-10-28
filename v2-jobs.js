// U-ETL v2 Jobs & Source Activity UI (Phase 3 Task 8).
(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    const mod = factory();
    root.V2Activity = mod.V2Activity;
    root.V2Jobs = mod.V2Jobs;
  }
})(globalThis, function () {
  'use strict';

  // ---------- Source Activity (Task 1) ----------
  const kinds = {
    queue_wait: ['Queue wait', 'warn'],
    busy_429: ['Busy (429)', 'warn'],
    timeout: ['Timeout', 'err'],
    read_ok: ['Read OK', 'ok'],
    read_error: ['Read error', 'err']
  };

  function query(filters = {}, cursor = null) {
    const params = new URLSearchParams({ limit: '100' });
    if (filters.kind) {
      if (!Object.hasOwn(kinds, filters.kind)) throw new Error('Choose a supported event kind.');
      params.set('kind', filters.kind);
    }
    if (filters.dataset) {
      if (filters.dataset.length > 200 || !/^[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+){0,2}$/.test(filters.dataset)) {
        throw new Error('Use a dataset name containing letters, numbers and underscores.');
      }
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

  function mountActivity(root, { workspace, query: client, onUnauthorized = () => {} }) {
    const doc = root.ownerDocument;
    let destroyed = false, generation = 0, next = null, activeFilters = null;
    const controllers = new Set();
    const make = (tag, className = '', text) => {
      const node = doc.createElement(tag);
      node.className = className;
      if (text !== undefined) node.textContent = text;
      return node;
    };
    const form = make('form', 'card v2-activity-filters');
    function select(labelText, entries) {
      const label = make('label', 'field', labelText), node = make('select');
      for (const [value, text] of entries) {
        const option = make('option', '', text);
        option.value = value;
        node.append(option);
      }
      label.append(node);
      form.append(label);
      return node;
    }
    const range = select('Time range', [['24', 'Last 24 hours'], ['1', 'Last hour'], ['168', 'Last 7 days'], ['720', 'Last 30 days'], ['', 'All retained events']]);
    range.value = '24';
    const kind = select('Event kind', [['', 'All events'], ...Object.entries(kinds).map(([key, value]) => [key, value[0]])]);
    const datasetLabel = make('label', 'field', 'Dataset'), dataset = make('input');
    dataset.type = 'search';
    dataset.maxLength = 200;
    dataset.placeholder = 'All datasets';
    datasetLabel.append(dataset);
    form.append(datasetLabel);
    const refresh = make('button', 'primary', 'Refresh');
    refresh.type = 'submit';
    form.append(refresh);
    const status = make('p', 'muted');
    status.setAttribute('role', 'status');
    status.setAttribute('aria-live', 'polite');
    const content = make('div', 'card tablewrap');
    const controls = make('div', 'actions'), first = make('button', '', 'First page'), more = make('button', '', 'Next page');
    first.type = more.type = 'button';
    controls.append(first, more);
    root.replaceChildren(form, status, content, controls);

    async function load(cursor = null, invalidate = false) {
      const own = ++generation;
      let params;
      try {
        if (!cursor) {
          activeFilters = {
            kind: kind.value,
            dataset: dataset.value,
            since: range.value ? new Date(Date.now() - Number(range.value) * 3600000).toISOString() : null
          };
        }
        params = query(activeFilters, cursor);
      } catch (error) {
        status.textContent = error.message;
        refresh.disabled = false;
        more.disabled = first.disabled = true;
        return;
      }
      if (invalidate) client.invalidate(['source-activity', workspace]);
      refresh.disabled = more.disabled = first.disabled = true;
      status.textContent = 'Loading source activity…';
      const controller = new AbortController();
      controllers.add(controller);
      try {
        const data = await client.fetch(['source-activity', workspace, params],
          '/api/v2/workspaces/' + encodeURIComponent(workspace) + '/source-activity?' + params, { signal: controller.signal });
        if (destroyed || own !== generation) return;
        next = data.next_cursor;
        const table = make('table', 'table'), header = make('tr'), head = make('thead'), body = make('tbody');
        for (const name of ['Time', 'Dataset', 'User', 'Event', 'Wait (ms)', 'Rows', 'Bytes']) header.append(make('th', '', name));
        head.append(header);
        table.append(head, body);
        for (const item of data.items) {
          const row = make('tr');
          for (const value of [item.at, item.dataset, item.user_id]) row.append(make('td', '', value ?? '—'));
          const event = make('td'), badge = kinds[item.kind] || ['Unknown', 'warn'];
          event.append(make('span', 'badge ' + badge[1], badge[0]));
          row.append(event);
          for (const value of [item.waited_ms, item.rows, item.bytes]) row.append(make('td', '', value ?? '—'));
          body.append(row);
        }
        content.replaceChildren(...(data.items.length ? [table] : [make('p', 'muted', 'No source activity for these filters.')]));
        status.textContent = data.items.length + ' events' + (next ? ' · more available' : '');
        more.disabled = !next;
        first.disabled = !cursor;
      } catch (error) {
        if (!destroyed && own === generation) {
          if (error.status === 401) { onUnauthorized(); return; }
          status.textContent = error.message || 'Could not load source activity.';
          content.replaceChildren();
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
    return {
      destroy() {
        destroyed = true;
        generation++;
        for (const controller of controllers) controller.abort();
        controllers.clear();
        root.replaceChildren();
      }
    };
  }

  // ---------- Jobs UI (Task 8) ----------
  const runStates = {
    queued: ['Queued', 'v2-badge-queued'],
    running: ['Running', 'v2-badge-running'],
    publishing: ['Publishing', 'v2-badge-publishing'],
    succeeded: ['Succeeded', 'v2-badge-succeeded'],
    failed: ['Failed', 'v2-badge-failed'],
    cancelled: ['Cancelled', 'v2-badge-cancelled'],
    dead: ['Dead Letter', 'v2-badge-dead']
  };

  function mountJobs(root, { workspace, query: client, role = 'viewer', onUnauthorized = () => {} }) {
    const doc = root.ownerDocument;
    let destroyed = false, generation = 0, pollTimer = null;
    const controllers = new Set();
    const canOperate = (role === 'operator' || role === 'admin');

    const make = (tag, className = '', text) => {
      const node = doc.createElement(tag);
      node.className = className;
      if (text !== undefined) node.textContent = text;
      return node;
    };

    const container = make('div', 'v2-jobs-container');
    const deadLetterBanner = make('div', 'v2-dead-letter-banner');
    deadLetterBanner.style = { display: 'none' };
    const statusText = make('p', 'muted');
    statusText.setAttribute('role', 'status');
    statusText.setAttribute('aria-live', 'polite');
    const tableWrap = make('div', 'card tablewrap');
    container.append(deadLetterBanner, statusText, tableWrap);
    root.replaceChildren(container);

    // Reduced motion preference check
    const prefersReducedMotion = typeof globalThis.matchMedia === 'function' &&
      globalThis.matchMedia('(prefers-reduced-motion: reduce)').matches;

    async function load() {
      const own = ++generation;
      const controller = new AbortController();
      controllers.add(controller);

      try {
        // 1. Fetch dead letters
        const dlPath = '/api/v2/workspaces/' + encodeURIComponent(workspace) + '/dead-letters';
        const dls = await client.fetch(['dead-letters', workspace], dlPath, { signal: controller.signal }).catch(() => []);
        if (destroyed || own !== generation) return;

        if (Array.isArray(dls) && dls.length > 0) {
          deadLetterBanner.style = { display: 'flex' };
          const title = make('div', 'dl-title', `⚠️ ${dls.length} Dead-Lettered Job${dls.length > 1 ? 's' : ''}`);
          const desc = make('div', 'dl-desc', `Latest: ${dls[0].pipeline_name || 'Pipeline'} failed (${dls[0].reason}). Requires operator retry.`);
          deadLetterBanner.replaceChildren(title, desc);
        } else {
          deadLetterBanner.style = { display: 'none' };
          deadLetterBanner.replaceChildren();
        }

        // 2. Fetch runs
        const runsPath = '/api/v2/workspaces/' + encodeURIComponent(workspace) + '/runs?limit=50';
        const runs = await client.fetch(['runs', workspace], runsPath, { signal: controller.signal });
        if (destroyed || own !== generation) return;

        statusText.textContent = `${runs.length} runs listed.`;

        if (!runs.length) {
          tableWrap.replaceChildren(make('p', 'muted', 'No pipeline runs recorded yet.'));
          return;
        }

        const table = make('table', 'table'), head = make('thead'), header = make('tr'), body = make('tbody');
        for (const col of ['Pipeline', 'Status', 'Progress', 'Attempt', 'Created', 'Actions']) {
          header.append(make('th', '', col));
        }
        head.append(header);
        table.append(head, body);

        let hasActiveRuns = false;

        for (const run of runs) {
          const row = make('tr');
          if (['queued', 'running', 'publishing'].includes(run.state)) {
            hasActiveRuns = true;
          }

          // Pipeline
          row.append(make('td', 'v2-who', run.pipeline_name || run.revision_id?.slice(0, 8) || 'Pipeline'));

          // Status Badge
          const statusTd = make('td');
          const [stateLabel, stateClass] = runStates[run.state] || [run.state, ''];
          const badge = make('span', `badge ${stateClass}`, stateLabel);
          statusTd.append(badge);
          row.append(statusTd);

          // Progress
          const progTd = make('td');
          const rowsRead = Number(run.rows_read || 0);
          const maxRows = 5000000;
          const pct = Math.min(100, Math.round((rowsRead / maxRows) * 100));
          const progBar = make('div', 'v2-progress-bar');
          const progFill = make('div', 'v2-progress-fill');
          progFill.style = { width: `${pct}%` };
          progBar.append(progFill);
          const progLabel = make('small', 'muted', `${rowsRead.toLocaleString()} rows`);
          progTd.append(progBar, progLabel);
          row.append(progTd);

          // Attempt
          row.append(make('td', '', `${run.attempt} / ${run.max_attempts || 3}`));

          // Created
          row.append(make('td', '', run.created_at ? new Date(run.created_at).toLocaleTimeString() : '—'));

          // Actions
          const actionTd = make('td');
          if (['queued', 'running', 'publishing'].includes(run.state)) {
            const cancelBtn = make('button', 'danger small', 'Cancel');
            cancelBtn.type = 'button';
            cancelBtn.disabled = Boolean(!canOperate || run.cancel_requested);
            cancelBtn.addEventListener('click', async () => {
              cancelBtn.disabled = true;
              try {
                await client.fetch(['cancel-run', run.id],
                  `/api/v2/workspaces/${encodeURIComponent(workspace)}/runs/${run.id}/cancel`, { method: 'POST' });
                client.invalidate(['runs', workspace]);
                load();
              } catch (err) {
                statusText.textContent = err.message || 'Cancel failed';
              }
            });
            actionTd.append(cancelBtn);
          } else if (['failed', 'dead'].includes(run.state)) {
            const retryBtn = make('button', 'primary small', 'Retry');
            retryBtn.type = 'button';
            retryBtn.disabled = !canOperate;
            retryBtn.addEventListener('click', async () => {
              retryBtn.disabled = true;
              try {
                await client.fetch(['retry-run', run.id],
                  `/api/v2/workspaces/${encodeURIComponent(workspace)}/runs/${run.id}/retry`, { method: 'POST' });
                client.invalidate(['runs', workspace]);
                client.invalidate(['dead-letters', workspace]);
                load();
              } catch (err) {
                statusText.textContent = err.message || 'Retry failed';
              }
            });
            actionTd.append(retryBtn);
          }
          row.append(actionTd);
          body.append(row);
        }

        tableWrap.replaceChildren(table);

        // Schedule polling if there are active runs, not destroyed, and auto-polling enabled
        if (hasActiveRuns && !destroyed && poll && typeof window !== 'undefined' && !prefersReducedMotion) {
          const pollInterval = 3000;
          pollTimer = setTimeout(() => {
            if (!destroyed && own === generation) {
              client.invalidate(['runs', workspace]);
              load();
            }
          }, pollInterval);
          if (pollTimer && typeof pollTimer.unref === 'function') {
            pollTimer.unref();
          }
        }

      } catch (error) {
        if (!destroyed && own === generation) {
          if (error.status === 401) { onUnauthorized(); return; }
          statusText.textContent = error.message || 'Could not load jobs.';
        }
      } finally {
        controllers.delete(controller);
      }
    }

    load();

    return {
      destroy() {
        destroyed = true;
        generation++;
        if (pollTimer) clearTimeout(pollTimer);
        for (const controller of controllers) controller.abort();
        controllers.clear();
        root.replaceChildren();
      }
    };
  }

  const V2Activity = { mount: mountActivity, query };
  const V2Jobs = { mount: mountJobs };

  return {
    mount: mountActivity, // Backwards compatible default for activity.test.js
    query,
    mountActivity,
    mountJobs,
    V2Activity,
    V2Jobs
  };
});
