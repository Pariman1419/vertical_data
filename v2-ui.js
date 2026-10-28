/*
 * U-ETL v2 UI layer: sign-in, workspace, members, audit trail, users.
 * Loads after prototype.js and wraps layout/page/navPage; it does not edit the pilot UI.
 * No inline handlers: all events go through delegated listeners (audit R06).
 * If /api/v2 is not served by this origin (legacy pilot server) the layer stays inert.
 */
(function () {
  'use strict';
  const V2 = new Proxy({}, { get: (_, key) => V2Store.get(key), set: (_, key, value) => { V2Store.set({ [key]: value }); return true; } });
  let generation = 0, previewTable = null, activityView = null;
  const resourceVersions = {};
  const requestForm = V2Forms.datasetRequest();
  const KEY = 'uetl.v2.workspace';
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
  const ROLES = ['viewer', 'author', 'reviewer', 'operator', 'admin'];
  const PAGES = { v2ws: 'Workspaces', v2src: 'Sources (SPICE)', v2members: 'Members', v2audit: 'Audit trail', v2users: 'Users', v2account: 'Account', v2activity: 'Source activity' };

  async function api(method, path, body) {
    const scope = generation;
    const res = await fetch('/api/v2' + path, {
      method, credentials: 'same-origin', cache: 'no-store',
      headers: body === undefined ? { 'X-CSRF-Token': V2.csrf } : { 'Content-Type': 'application/json', 'X-CSRF-Token': V2.csrf },
      body: body === undefined ? undefined : JSON.stringify(body)
    });
    V2.enabled = V2.enabled || res.headers.has('x-correlation-id');
    let data = null;
    try { data = await res.json(); } catch { /* empty body */ }
    if (res.status === 401 && V2.user && scope === generation) { reset(); render(); }
    if (!res.ok) {
      const e = new Error(data?.error?.message || 'Request failed');
      e.status = res.status; e.cid = data?.error?.correlation_id;
      e.retryAfter = Number(res.headers.get('Retry-After')) || 1;
      throw e;
    }
    return data;
  }

  function reset() { generation++; V2Query.clear(); Object.assign(V2, { user: null, csrf: '', workspaces: [], ws: null, members: null, audit: null, users: null, conns: null, catall: null, cat: null, reqs: null, sel: null, result: null, busy: false, previewBusy: false, previewObject: '', previewLimit: 50, filters: [], error: '' }); }
  const role = () => (V2.workspaces.find(w => w.id === V2.ws) || {}).role || '';
  const isSuper = () => V2.user?.platform_role === 'superadmin';
  const canManage = () => isSuper() || role() === 'admin';
  const fail = e => { V2.error = V2Forms.errorMessage(e) + (e.cid ? ` (ref ${e.cid.slice(0, 8)})` : ''); render(); };

  async function boot() {
    const scope = generation;
    try {
      const me = await api('GET', '/auth/me');
      if (scope !== generation) return;
      adopt(me);
    } catch { /* 401 = signed out, anything else = legacy server */ }
    V2.checked = true;
    if (V2.enabled) { PAGES_ADDED || addMenu(); if (location.hash.startsWith('#/')) applyRoute(); render(); }
  }

  function adopt(me) {
    generation++; V2Query.clear();
    V2.previewObject = ''; V2.filters = []; V2.previewLimit = 50; V2.previewBusy = false;
    V2.user = me.user; V2.csrf = me.csrf; V2.workspaces = me.workspaces;
    let saved = null; try { saved = localStorage.getItem(KEY); } catch { /* storage may be blocked */ }
    V2.ws = V2.workspaces.some(w => w.id === saved) ? saved : (V2.workspaces[0]?.id || null);
    V2.members = V2.audit = V2.users = V2.conns = V2.catall = V2.cat = V2.reqs = V2.sel = V2.result = null; V2.error = '';
  }

  let PAGES_ADDED = false;
  function addMenu() {
    PAGES_ADDED = true;
    M.push(['v2ws', PAGES.v2ws], ['v2src', PAGES.v2src], ['v2members', PAGES.v2members], ['v2audit', PAGES.v2audit], ['v2activity', PAGES.v2activity], ['v2account', PAGES.v2account]);
  }
  function syncMenu() {
    const has = M.some(x => x[0] === 'v2users');
    if (isSuper() && !has) M.push(['v2users', PAGES.v2users]);
    if (!isSuper() && has) M.splice(M.findIndex(x => x[0] === 'v2users'), 1);
  }

  // ---- wrap the pilot shell ----
  const baseLayout = layout, basePage = page, baseNav = navPage;
  navPage = p => (PAGES[p] ? p : baseNav(p));
  page = () => (PAGES[S.page] ? v2Page() : basePage());
  layout = function () {
    previewTable?.destroy(); previewTable = null;
    activityView?.destroy(); activityView = null;
    const routePage = { v2src: 'sources', v2ws: 'workspaces', v2members: 'members', v2audit: 'audit', v2users: 'users', v2account: 'account', v2activity: 'source-activity' }[S.page];
    if (V2.user && routePage && V2Route.current().page !== routePage) V2Route.go(routePage);
    if (V2.enabled && V2.user) {
      if (!V2.workspaces.some(w => w.id === V2.ws)) setWs(V2.workspaces[0]?.id || null); // keep selector and state in step
      syncMenu(); // must run before the pilot shell builds the nav
    }
    baseLayout();
    if (!V2.enabled) return;
    const shell = document.querySelector('.shell');
    if (!V2.checked) { shell.innerHTML = '<main class="main"><section class="content"><p class="muted">Loading…</p></section></main>'; return; }
    if (!V2.user) { shell.innerHTML = loginMarkup(); return; }
    decorate();
    const tableHost = document.querySelector('[data-v2-table]');
    if (tableHost && V2.result) previewTable = V2Table.mount(tableHost, V2.result);
    const activityHost = document.querySelector('[data-v2-activity]');
    if (activityHost && V2.ws) activityView = V2Activity.mount(activityHost, { workspace: V2.ws, query: V2Query, onUnauthorized: () => { reset(); render(); } });
  };

  function decorate() {
    const idn = document.querySelector('.identity');
    if (idn) idn.insertAdjacentHTML('beforeend', `<span class="v2-who">${esc(V2.user.display_name || V2.user.username)}${isSuper() ? ' · platform admin' : ''}</span><button type="button" class="v2-signout" data-v2="logout">Sign out</button>`);
    const brand = document.querySelector('.sidebar .brand');
    if (brand) {
      brand.innerHTML = V2.workspaces.length
        ? `<label class="v2-ws-label">WORKSPACE<select data-v2-ws aria-label="Workspace">${V2.workspaces.map(w => `<option value="${esc(w.id)}" ${w.id === V2.ws ? 'selected' : ''}>${esc(w.name)}</option>`).join('')}</select></label>`
        : 'WORKSPACE<br><span class="v2-ws-none">No workspace yet</span>';
    }
  }

  // ---- screens ----
  function loginMarkup() {
    return `<main class="main"><section class="content"><div class="v2-login card">
      <h2>Sign in</h2><p class="muted">Use your U-ETL account. This is separate from any source database password.</p>
      ${V2.error ? `<div class="callout v2-error" role="alert">${esc(V2.error)}</div>` : ''}
      <form data-v2-form="login" autocomplete="on">
        <label class="field">Username<input name="username" autocomplete="username" required maxlength="100" autofocus></label>
        <label class="field">Password<input name="password" type="password" autocomplete="current-password" required maxlength="256"></label>
        <button class="primary" ${V2.busy ? 'disabled' : ''}>${V2.busy ? 'Signing in…' : 'Sign in'}</button>
      </form></div></section></main>`;
  }

  function banner() { return V2.error ? `<div class="callout v2-error" role="alert">${esc(V2.error)}</div>` : ''; }
  const roleBadge = r => badge(esc(r), r === 'admin' ? 'ok' : 'warn');

  function v2Page() {
    const p = S.page;
    if (p === 'v2ws') return wsPage();
    if (p === 'v2account') return accountPage();
    if (!V2.ws && p !== 'v2users') return intro(PAGES[p], 'Select or create a workspace first.') + banner();
    if (p === 'v2src') return srcPage();
    if (p === 'v2members') return membersPage();
    if (p === 'v2audit') return auditPage();
    if (p === 'v2activity') return intro('Source activity', 'Queue waits, busy replies and preview outcomes. No query text or source values are logged.') + '<div data-v2-activity></div>';
    return usersPage();
  }

  const connUrl = () => `/workspaces/${V2.ws}/connections/${V2.sel}`;
  const statusBadge = s => badge(esc(s), s === 'ok' ? 'ok' : s === 'failed' ? 'err' : 'warn');

  function srcPage() {
    load('conns', `/workspaces/${V2.ws}/connections`);
    const list = V2.conns || [];
    if (V2.conns !== null && V2.sel && !list.some(c => c.id === V2.sel)) V2.sel = null;
    if (!V2.sel && list.length) V2.sel = list[0].id;
    const mgr = canManage();
    const rows = list.map(c => `<tr><td>${esc(c.name)}</td><td><code>${esc(c.base_url)}</code><br><small class="muted">${esc(V2Capabilities.capabilities(c.capabilities))}</small></td><td>${statusBadge(c.status)}</td><td>${c.last_test_at ? esc(new Date(c.last_test_at).toLocaleString()) : '—'}</td>
      <td><button type="button" data-v2="pick-conn" data-id="${esc(c.id)}">${c.id === V2.sel ? 'Selected' : 'Select'}</button>${mgr ? ` <button type="button" data-v2="test-conn" data-id="${esc(c.id)}">Test</button> <button type="button" data-v2="del-conn" data-id="${esc(c.id)}">Delete</button>` : ''}</td></tr>`).join('');
    const add = mgr ? `<div class="title">Add connection</div><form class="card" data-v2-form="conn"><label class="field">Name<input name="name" required maxlength="100"></label>
      <label class="field">SPICE HTTP URL<input name="base_url" required maxlength="300" placeholder="http://host:8091"></label>
      <p class="muted">Only hosts on the server allowlist are accepted. SPICE data is read over Arrow Flight with row, size and time limits.</p><button class="primary">Add</button></form>` : '';
    return intro('Sources (SPICE)', 'การเชื่อมต่อแหล่งข้อมูล, แค็ตตาล็อก และ preview แบบจำกัดขนาด') + banner() +
      `<div class="card tablewrap"><table class="table"><thead><tr><th>Name</th><th>URL</th><th>Status</th><th>Last test</th><th></th></tr></thead><tbody>${rows || '<tr><td colspan="5" class="muted">No connections.</td></tr>'}</tbody></table></div>` +
      add + (V2.sel ? catalogPanel(mgr) + previewPanel() + requestPanel(mgr) : '');
  }

  function catalogPanel(mgr) {
    load('cat', connUrl() + '/catalog');
    if (mgr) load('catall', connUrl() + '/catalog/all');
    const objs = Object.entries(V2.cat?.objects || {});
    const names = objs.map(([n, o]) => `<tr><td><code>${esc(n)}</code></td><td>${o.columns.length}</td><td>${esc(o.columns.slice(0, 6).map(c => c.name).join(', '))}${o.columns.length > 6 ? '…' : ''}</td></tr>`).join('');
    const picker = mgr ? `<div class="title">Allowed objects</div><form class="card" data-v2-form="allow"><p class="muted">Only ticked objects can be viewed or previewed in this workspace.</p>
      <div class="v2-checks">${(V2.catall?.objects || []).map(o => `<label><input type="checkbox" name="obj" value="${esc(o.name)}" ${o.allowed ? 'checked' : ''}> ${esc(o.name)}</label>`).join('') || '<span class="muted">Refresh the catalog first.</span>'}</div>
      <button class="primary">Save allowlist</button></form>` : '';
    return `<div class="title">Catalog${V2.cat?.revision ? ` · revision ${V2.cat.revision}` : ''}</div>` + (mgr ? '<p><button type="button" data-v2="refresh-cat">Refresh catalog from source</button></p>' : '') +
      `<div class="card tablewrap"><table class="table"><thead><tr><th>Object</th><th>Columns</th><th>First columns</th></tr></thead><tbody>${names || '<tr><td colspan="3" class="muted">No allowed objects.</td></tr>'}</tbody></table></div>` + picker;
  }

  function previewPanel() {
    const objs = Object.entries(V2.cat?.objects || {});
    if (!objs.length || (!isSuper() && !['author', 'operator', 'admin'].includes(role()))) return '';
    const r = V2.result;
    const object = objs.some(([name]) => name === V2.previewObject) ? V2.previewObject : objs[0][0];
    V2.previewObject = object;
    const columns = V2.cat.objects[object].columns;
    const filters = V2.filters.map((f, i) => `<div class="v2-filter" data-filter-row="${i}">
      <label>Column<select data-filter="column" aria-label="Filter ${i + 1} column">${columns.map(c => `<option value="${esc(c.name)}" ${c.name === f.column ? 'selected' : ''}>${esc(c.name)}</option>`).join('')}</select></label>
      <label>Operator<select data-filter="op" aria-label="Filter ${i + 1} operator">${['=', '!=', '<', '<=', '>', '>='].map(op => `<option value="${esc(op)}" ${op === f.op ? 'selected' : ''}>${esc(op)}</option>`).join('')}</select></label>
      <label>Value<input data-filter="value" aria-label="Filter ${i + 1} value" value="${esc(f.value)}" required maxlength="200"></label>
      <button type="button" data-v2="remove-filter" data-index="${i}" aria-label="Remove filter ${i + 1}">Remove</button></div>`).join('');
    const table = r ? `<div class="card"><p class="muted">${r.rows.length} rows · ${r.columns.length} columns · first 20 columns shown. Choose Columns to change them.</p><div data-v2-table></div>${r.truncated ? '<p class="muted">Truncated at the preview limit.</p>' : ''}</div>` : '';
    return `<div class="title">Preview</div><form class="card" data-v2-form="preview"><label class="field">Object<select name="object">${objs.map(([n]) => `<option ${n === object ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select></label>
      <label class="field">Rows (1–1000)<input name="limit" type="number" min="1" max="1000" value="${esc(V2.previewLimit)}"></label>
      <fieldset><legend>Filters (all must match, up to 5)</legend>${filters}<button type="button" data-v2="add-filter" ${V2.filters.length >= 5 ? 'disabled' : ''}>Add filter</button></fieldset>
      <button class="primary" ${V2.previewBusy ? 'disabled' : ''}>${V2.previewBusy ? 'Running preview…' : 'Run preview'}</button><span role="status">${V2.previewBusy ? ' Reading source…' : ''}</span></form>` + table;
  }

  const PROFILES = { pg: 'PostgreSQL (schema.table)', scada: 'SQL Server SCADA (Database.schema.table)' };
  const reqBadge = s => badge(esc(s), s === 'applied' ? 'ok' : s === 'cancelled' ? 'err' : 'warn');

  function requestPanel(mgr) {
    load('reqs', connUrl() + '/dataset-requests');
    const list = V2.reqs || [];
    const rows = list.map(q => `<tr><td><code>${esc(q.dataset_name)}</code></td><td>${esc(q.profile)}</td><td><code>${esc(q.remote_object)}</code></td><td>${reqBadge(q.status)}</td><td>${esc(new Date(q.created_at).toLocaleString())}</td>
      <td>${q.status === 'pending' && mgr ? `<button type="button" data-v2="cancel-req" data-id="${esc(q.id)}">Cancel</button>` : ''}</td></tr>
      ${q.status === 'pending' ? `<tr><td colspan="6"><div class="muted">Paste this into <code>spicepod.yaml</code> on the SPICE host, then restart/reload SPICE and press “Refresh catalog”:</div><pre class="v2-yaml">${esc(q.snippet)}</pre>
      <button type="button" data-v2="copy" data-text="${esc(q.snippet)}">Copy</button></td></tr>` : ''}`).join('');
    const form = mgr ? `<form class="card" data-v2-form="request"><label class="field">Source profile<select name="profile">${Object.entries(PROFILES).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join('')}</select></label>
      <label class="field">Dataset name in SPICE (a-z, 0-9, _)<input name="dataset_name" required pattern="[a-z][a-z0-9_]{2,60}" maxlength="61"></label>
      <label class="field">Source table<input name="remote_object" required maxlength="200" placeholder="schema.table"></label>
      <label class="field">Note (optional)<input name="note" maxlength="500"></label>
      <p class="muted">No database password is entered here. The new dataset reuses the credentials already configured for the chosen profile on the SPICE host. A SPICE operator must apply the entry; this page does not change SPICE.</p>
      <button class="primary">Create request</button></form>` : '';
    return `<div class="title">Request a new dataset</div>${form}
      <div class="card tablewrap"><table class="table"><thead><tr><th>Name</th><th>Profile</th><th>Source table</th><th>Status</th><th>Created</th><th></th></tr></thead><tbody>${rows || '<tr><td colspan="6" class="muted">No requests.</td></tr>'}</tbody></table></div>
      <p class="muted">Apply steps: 1) back up spicepod.yaml, 2) paste the entry, 3) validate the YAML, 4) reload/restart SPICE (not yet confirmed which one is needed), 5) press “Refresh catalog”: the request closes itself when the name appears.</p>`;
  }

  function accountPage() {
    return intro('Account', `Signed in as ${esc(V2.user.username)}`) + banner() +
      `<div class="title">Change password</div>
       <form class="card" data-v2-form="password">
       <label class="field">Current password<input name="current_password" type="password" required autocomplete="current-password" maxlength="256"></label>
       <label class="field">New password (min 12 characters)<input name="new_password" type="password" required minlength="12" autocomplete="new-password" maxlength="256"></label>
       <label class="field">Repeat new password<input name="repeat" type="password" required minlength="12" autocomplete="new-password" maxlength="256"></label>
       <p class="muted">Other signed-in sessions of this account are signed out when the password changes.</p>
       <button class="primary">Change password</button></form>`;
  }

  function wsPage() {
    const rows = V2.workspaces.map(w => `<tr><td>${esc(w.name)}</td><td><code>${esc(w.slug)}</code></td><td>${roleBadge(w.role)}</td><td>${w.id === V2.ws ? badge('Active') : `<button type="button" data-v2="pick" data-id="${esc(w.id)}">Use</button>`}</td></tr>`).join('');
    const create = isSuper() ? `<div class="title">Create workspace</div><form class="card" data-v2-form="workspace"><label class="field">Name<input name="name" required maxlength="100"></label><label class="field">Slug (a-z, 0-9, -)<input name="slug" required pattern="[a-z0-9][a-z0-9-]{1,40}"></label><button class="primary">Create</button></form>` : '';
    return intro('Workspaces', 'ข้อมูลและสิทธิ์ถูกแยกตาม Workspace; ผู้ใช้เห็นเฉพาะ Workspace ที่เป็นสมาชิก') + banner() +
      `<div class="card tablewrap"><table class="table"><thead><tr><th>Name</th><th>Slug</th><th>Your role</th><th></th></tr></thead><tbody>${rows || '<tr><td colspan="4" class="muted">No workspaces.</td></tr>'}</tbody></table></div>` + create;
  }

  function membersPage() {
    if (!canManage()) return intro('Members', 'Workspace membership') + `<div class="callout">Only workspace admins can manage members. Your role: ${esc(role() || 'none')}.</div>`;
    load('members', `/workspaces/${V2.ws}/members`);
    const rows = (V2.members || []).map(m => `<tr><td>${esc(m.username)}</td><td>${esc(m.display_name)}</td><td>${roleBadge(m.role)}</td><td><button type="button" data-v2="remove" data-id="${esc(m.id)}">Remove</button></td></tr>`).join('');
    return intro('Members', 'กำหนด role ต่อ Workspace: viewer · author · reviewer · operator · admin') + banner() +
      `<div class="card tablewrap">${V2.members ? `<table class="table"><thead><tr><th>Username</th><th>Name</th><th>Role</th><th></th></tr></thead><tbody>${rows}</tbody></table>` : '<p class="muted">Loading…</p>'}</div>
       <div class="title">Add or change a member</div>
       <form class="card" data-v2-form="member"><label class="field">Username<input name="username" required maxlength="100"></label>
       <label class="field">Role<select name="role">${ROLES.map(r => `<option>${r}</option>`).join('')}</select></label>
       <p class="muted">An author cannot approve their own revision; this is enforced by the database.</p><button class="primary">Save member</button></form>`;
  }

  function auditPage() {
    if (!canManage()) return intro('Audit trail', 'Security events') + `<div class="callout">Only workspace admins can read the audit trail.</div>`;
    load('audit', `/workspaces/${V2.ws}/audit-events?limit=100`);
    const rows = (V2.audit || []).map(a => `<tr><td>${esc(new Date(a.at).toLocaleString())}</td><td>${esc(a.actor || '—')}</td><td>${esc(a.action)}</td><td>${badge(esc(a.outcome), a.outcome === 'allow' ? 'ok' : 'err')}</td><td><code>${esc((a.correlation_id || '').slice(0, 8))}</code></td></tr>`).join('');
    return intro('Audit trail', 'บันทึกแบบ append-only: แก้ไขหรือลบไม่ได้ แม้ผ่านฐานข้อมูล', '<button type="button" data-v2="refresh-audit">Refresh</button>') + banner() +
      `<div class="card tablewrap">${V2.audit ? `<table class="table"><thead><tr><th>Time</th><th>Actor</th><th>Action</th><th>Outcome</th><th>Ref</th></tr></thead><tbody>${rows || '<tr><td colspan="5" class="muted">No events.</td></tr>'}</tbody></table>` : '<p class="muted">Loading…</p>'}</div>`;
  }

  function usersPage() {
    if (!isSuper()) return intro('Users', 'Platform users') + '<div class="callout">Platform administrators only.</div>';
    load('users', '/users');
    const rows = (V2.users || []).map(u => `<tr><td>${esc(u.username)}</td><td>${esc(u.display_name)}</td><td>${u.platform_role === 'superadmin' ? badge('platform admin') : ''}</td><td>${u.is_active ? badge('Active') : badge('Disabled', 'err')}</td></tr>`).join('');
    return intro('Users', 'บัญชีผู้ใช้ภายใน (รหัสผ่านเก็บเป็น argon2id hash)') + banner() +
      `<div class="card tablewrap">${V2.users ? `<table class="table"><thead><tr><th>Username</th><th>Name</th><th></th><th>Status</th></tr></thead><tbody>${rows}</tbody></table>` : '<p class="muted">Loading…</p>'}</div>
       <div class="title">Create user</div>
       <form class="card" data-v2-form="user"><label class="field">Username<input name="username" required pattern="[A-Za-z0-9._-]{3,64}" maxlength="64" autocomplete="off"></label>
       <label class="field">Display name<input name="display_name" maxlength="100"></label>
       <label class="field">Initial password (min 12 characters)<input name="password" type="password" required minlength="12" maxlength="256" autocomplete="new-password"></label>
       <button class="primary">Create user</button></form>`;
  }

  const queryKey = kind => ['ui', V2.user?.id, V2.ws, kind, ...(['cat', 'catall', 'reqs'].includes(kind) ? [V2.sel] : [])];
  function load(kind, path) {
    if (V2[kind] !== null) return;
    const scope = generation, version = resourceVersions[kind] || 0;
    V2Query.fetch(queryKey(kind), '/api/v2' + path).then(d => {
      if (scope !== generation || version !== (resourceVersions[kind] || 0)) return;
      V2[kind] = d; V2.error = ''; render();
    }, e => {
      if (scope !== generation || version !== (resourceVersions[kind] || 0) || TanStack.isCancelledError(e)) return;
      if (e.status === 401) reset();
      else { V2[kind] = []; V2.error = e.message; }
      render();
    });
  }
  const invalidate = kind => { resourceVersions[kind] = (resourceVersions[kind] || 0) + 1; V2Query.invalidate(['ui', V2.user?.id, V2.ws, kind]); V2[kind] = null; };
  function pickConnection(id) {
    generation++;
    V2.sel = id; V2.cat = V2.catall = V2.reqs = V2.result = null;
    V2.previewObject = ''; V2.filters = []; V2.previewBusy = false;
  }
  function applyRoute() {
    const route = V2Route.current();
    S.page = { sources: 'v2src', workspaces: 'v2ws', members: 'v2members', audit: 'v2audit', users: 'v2users', account: 'v2account', 'source-activity': 'v2activity' }[route.page];
    if (route.page === 'sources' && route.connection !== V2.sel) pickConnection(route.connection || null);
  }
  addEventListener('hashchange', () => { if (V2.enabled && V2.user) { applyRoute(); render(); } });

  // ---- events (delegated; no inline handlers) ----
  document.addEventListener('submit', async ev => {
    const form = ev.target.closest('[data-v2-form]');
    if (!form || !V2.enabled) return;
    ev.preventDefault();
    const f = Object.fromEntries(new FormData(form));
    const kind = form.dataset.v2Form;
    if ((kind === 'preview' && V2.previewBusy) || (kind === 'login' && V2.busy)) return;
    let scope = generation;
    const target = connUrl();
    const submitButton = form.querySelector('button.primary');
    V2.error = '';
    try {
      if (kind === 'login') {
        V2.busy = true; render();
        await api('POST', '/auth/login', { username: f.username, password: f.password });
        if (scope !== generation) return;
        const me = await api('GET', '/auth/me');
        if (scope !== generation) return;
        adopt(me); scope = generation;
        S.page = V2.workspaces.length ? 'v2src' : 'v2ws';
        if (V2.workspaces.length && location.hash.startsWith('#/')) applyRoute();
        scope = generation;
      } else if (kind === 'workspace') {
        await api('POST', '/workspaces', { name: f.name, slug: f.slug });
        if (scope !== generation) return;
        const me = await api('GET', '/auth/me'); if (scope !== generation) return;
        V2.workspaces = me.workspaces; S.notice = 'Workspace created';
      } else if (kind === 'conn') {
        await api('POST', `/workspaces/${V2.ws}/connections`, { name: f.name, kind: 'rest', base_url: f.base_url });
        if (scope !== generation) return;
        invalidate('conns'); S.notice = 'Connection added';
      } else if (kind === 'request') {
        const submitted = await V2Forms.submit(requestForm, async () => {
          await V2Forms.validate(requestForm, f);
          if (scope !== generation) return;
          await api('POST', target + '/dataset-requests', { profile: f.profile, dataset_name: f.dataset_name, remote_object: f.remote_object, note: f.note || null });
        });
        if (!submitted || scope !== generation) return;
        invalidate('reqs'); S.notice = 'Request created';
      } else if (kind === 'allow') {
        await api('PUT', target + '/allowed-objects', { objects: new FormData(form).getAll('obj') });
        if (scope !== generation) return;
        invalidate('cat'); invalidate('catall'); S.notice = 'Allowlist saved';
      } else if (kind === 'preview') {
        V2.previewBusy = true;
        if (submitButton) { submitButton.disabled = true; submitButton.textContent = 'Running preview…'; }
        const columns = V2.cat.objects[f.object].columns;
        await V2Forms.validate(V2Forms.previewFilters(columns), { filters: V2.filters });
        if (scope !== generation) return;
        const result = await api('POST', target + '/preview', { object: f.object, limit: Number(f.limit) || 50,
          filters: V2Forms.filters(columns, V2.filters) });
        if (scope === generation) V2.result = result;
      } else if (kind === 'member') {
        await api('POST', `/workspaces/${V2.ws}/members`, { username: f.username, role: f.role });
        if (scope !== generation) return;
        invalidate('members'); S.notice = 'Member saved';
      } else if (kind === 'password') {
        if (f.new_password !== f.repeat) throw new Error('The two new passwords do not match');
        await api('POST', '/auth/change-password', { current_password: f.current_password, new_password: f.new_password });
        if (scope !== generation) return;
        S.notice = 'Password changed';
      } else if (kind === 'user') {
        await api('POST', '/users', { username: f.username, display_name: f.display_name || '', password: f.password });
        if (scope !== generation) return;
        invalidate('users'); S.notice = 'User created';
      }
      if (kind !== 'preview') form.reset?.();
    } catch (e) { if (scope === generation) V2.error = V2Forms.errorMessage(e) + (e.cid ? ` (ref ${e.cid.slice(0, 8)})` : ''); }
    if (scope !== generation) return;
    if (kind === 'preview' && scope === generation) V2.previewBusy = false;
    V2.busy = false; render();
  });

  document.addEventListener('click', async ev => {
    const el = ev.target.closest('[data-v2]');
    if (!el || !V2.enabled) return;
    const act = el.dataset.v2;
    let scope = generation;
    try {
      if (act === 'logout') { await api('POST', '/auth/logout', {}); if (scope !== generation) return; reset(); S.page = 'sources'; V2.error = ''; }
      else if (act === 'add-filter') { const cols = V2.cat?.objects[V2.previewObject]?.columns || []; if (cols.length && V2.filters.length < 5) V2.filters = [...V2.filters, { column: cols[0].name, op: '=', value: '' }]; }
      else if (act === 'remove-filter') { V2.filters = V2.filters.filter((_, i) => i !== Number(el.dataset.index)); }
      else if (act === 'pick') { setWs(el.dataset.id); }
      else if (act === 'remove') { await api('DELETE', `/workspaces/${V2.ws}/members/${el.dataset.id}`); if (scope !== generation) return; invalidate('members'); S.notice = 'Member removed'; }
      else if (act === 'pick-conn') { pickConnection(el.dataset.id); V2Route.go('sources', { connection: V2.sel }); }
      else if (act === 'cancel-req') { await api('POST', connUrl() + `/dataset-requests/${el.dataset.id}/cancel`); if (scope !== generation) return; invalidate('reqs'); S.notice = 'Request cancelled'; }
      else if (act === 'copy') { try { await navigator.clipboard.writeText(el.dataset.text); if (scope === generation) S.notice = 'Copied'; } catch { if (scope === generation) S.notice = 'Copy failed: select the text manually'; } }
      else if (act === 'test-conn') { pickConnection(el.dataset.id); scope = generation; const t = await api('POST', connUrl() + '/test'); if (scope !== generation) return; invalidate('conns'); S.notice = t.status === 'ok' ? 'Connection OK' : 'Test failed: ' + t.error; }
      else if (act === 'del-conn') { await api('DELETE', `/workspaces/${V2.ws}/connections/${el.dataset.id}`); if (scope !== generation) return; pickConnection(null); invalidate('conns'); S.notice = 'Connection deleted'; }
      else if (act === 'refresh-cat') { const r = await api('POST', connUrl() + '/catalog/refresh'); if (scope !== generation) return; invalidate('cat'); invalidate('catall'); invalidate('reqs'); S.notice = `Catalog revision ${r.revision}: ${r.objects} objects` + (r.requests_applied ? `; ${r.requests_applied} request(s) fulfilled` : ''); }
      else if (act === 'refresh-audit') { invalidate('audit'); }
    } catch (e) { if (scope === generation) fail(e); return; }
    render();
  });

  document.addEventListener('change', ev => {
    if (ev.target.matches('[data-v2-form="preview"] [name="object"]')) { generation++; V2.previewBusy = false; V2.previewObject = ev.target.value; V2.filters = []; V2.result = null; render(); }
    const filterRow = ev.target.closest('[data-filter-row]');
    if (filterRow) V2.filters = V2.filters.map((f, i) => i === Number(filterRow.dataset.filterRow) ? { ...f, [ev.target.dataset.filter]: ev.target.value } : f);
    const sel = ev.target.closest('[data-v2-ws]');
    if (sel) { setWs(sel.value); render(); }
  });
  document.addEventListener('input', ev => {
    if (ev.target.matches('[data-v2-form="preview"] [name="limit"]')) V2.previewLimit = ev.target.value;
    const row = ev.target.closest('[data-filter-row]');
    if (row && ev.target.dataset.filter === 'value') V2.filters = V2.filters.map((f, i) => i === Number(row.dataset.filterRow) ? { ...f, value: ev.target.value } : f);
  });

  function setWs(id) {
    generation++; V2Query.clear();
    V2.previewBusy = false; V2.previewObject = ''; V2.filters = [];
    V2.ws = id; V2.members = V2.audit = V2.conns = V2.cat = V2.catall = V2.reqs = V2.sel = V2.result = null;
    try { if (id) localStorage.setItem(KEY, id); } catch { /* optional convenience */ }
  }

  boot();
})();
