/*
 * U-ETL v2 UI layer: sign-in, workspace, members, audit trail, users.
 * Loads after prototype.js and wraps layout/page/navPage; it does not edit the pilot UI.
 * No inline handlers: all events go through delegated listeners (audit R06).
 * If /api/v2 is not served by this origin (legacy pilot server) the layer stays inert.
 */
(function () {
  'use strict';
  const V2 = { enabled: false, checked: false, user: null, csrf: '', workspaces: [], ws: null, members: null, audit: null, users: null, error: '', busy: false };
  const KEY = 'uetl.v2.workspace';
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
  const ROLES = ['viewer', 'author', 'reviewer', 'operator', 'admin'];
  const PAGES = { v2ws: 'Workspaces', v2members: 'Members', v2audit: 'Audit trail', v2users: 'Users' };

  async function api(method, path, body) {
    const res = await fetch('/api/v2' + path, {
      method, credentials: 'same-origin', cache: 'no-store',
      headers: body === undefined ? { 'X-CSRF-Token': V2.csrf } : { 'Content-Type': 'application/json', 'X-CSRF-Token': V2.csrf },
      body: body === undefined ? undefined : JSON.stringify(body)
    });
    V2.enabled = V2.enabled || res.headers.has('x-correlation-id');
    let data = null;
    try { data = await res.json(); } catch { /* empty body */ }
    if (res.status === 401 && V2.user) { reset(); render(); }
    if (!res.ok) {
      const e = new Error(data?.error?.message || 'Request failed');
      e.status = res.status; e.cid = data?.error?.correlation_id;
      throw e;
    }
    return data;
  }

  function reset() { Object.assign(V2, { user: null, csrf: '', workspaces: [], ws: null, members: null, audit: null, users: null }); }
  const role = () => (V2.workspaces.find(w => w.id === V2.ws) || {}).role || '';
  const isSuper = () => V2.user?.platform_role === 'superadmin';
  const canManage = () => isSuper() || role() === 'admin';
  const fail = e => { V2.error = e.message + (e.cid ? ` (ref ${e.cid.slice(0, 8)})` : ''); render(); };

  async function boot() {
    try {
      const me = await api('GET', '/auth/me');
      adopt(me);
    } catch { /* 401 = signed out, anything else = legacy server */ }
    V2.checked = true;
    if (V2.enabled) { PAGES_ADDED || addMenu(); render(); }
  }

  function adopt(me) {
    V2.user = me.user; V2.csrf = me.csrf; V2.workspaces = me.workspaces;
    let saved = null; try { saved = localStorage.getItem(KEY); } catch { /* storage may be blocked */ }
    V2.ws = V2.workspaces.some(w => w.id === saved) ? saved : (V2.workspaces[0]?.id || null);
    V2.members = V2.audit = V2.users = null; V2.error = '';
  }

  let PAGES_ADDED = false;
  function addMenu() {
    PAGES_ADDED = true;
    M.push(['v2ws', PAGES.v2ws], ['v2members', PAGES.v2members], ['v2audit', PAGES.v2audit]);
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
    baseLayout();
    if (!V2.enabled) return;
    const shell = document.querySelector('.shell');
    if (!V2.checked) { shell.innerHTML = '<main class="main"><section class="content"><p class="muted">Loading…</p></section></main>'; return; }
    if (!V2.user) { shell.innerHTML = loginMarkup(); return; }
    syncMenu();
    decorate();
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
    if (!V2.ws && p !== 'v2users') return intro(PAGES[p], 'Select or create a workspace first.') + banner();
    if (p === 'v2members') return membersPage();
    if (p === 'v2audit') return auditPage();
    return usersPage();
  }

  function wsPage() {
    const rows = V2.workspaces.map(w => `<tr><td>${esc(w.name)}</td><td><code>${esc(w.slug)}</code></td><td>${roleBadge(w.role)}</td><td>${w.id === V2.ws ? badge('Active') : `<button type="button" data-v2="pick" data-id="${esc(w.id)}">Use</button>`}</td></tr>`).join('');
    const create = isSuper() ? `<div class="title">Create workspace</div><form class="card" data-v2-form="workspace"><label class="field">Name<input name="name" required maxlength="100"></label><label class="field">Slug (a-z, 0-9, -)<input name="slug" required pattern="[a-z0-9][a-z0-9-]{1,40}"></label><button class="primary">Create</button></form>` : '';
    return intro('Workspaces', 'ข้อมูลและสิทธิ์ถูกแยกตาม Workspace; ผู้ใช้เห็นเฉพาะ Workspace ที่เป็นสมาชิก') + banner() +
      `<div class="card tablewrap"><table><thead><tr><th>Name</th><th>Slug</th><th>Your role</th><th></th></tr></thead><tbody>${rows || '<tr><td colspan="4" class="muted">No workspaces.</td></tr>'}</tbody></table></div>` + create;
  }

  function membersPage() {
    if (!canManage()) return intro('Members', 'Workspace membership') + `<div class="callout">Only workspace admins can manage members. Your role: ${esc(role() || 'none')}.</div>`;
    load('members', `/workspaces/${V2.ws}/members`);
    const rows = (V2.members || []).map(m => `<tr><td>${esc(m.username)}</td><td>${esc(m.display_name)}</td><td>${roleBadge(m.role)}</td><td><button type="button" data-v2="remove" data-id="${esc(m.id)}">Remove</button></td></tr>`).join('');
    return intro('Members', 'กำหนด role ต่อ Workspace: viewer · author · reviewer · operator · admin') + banner() +
      `<div class="card tablewrap">${V2.members ? `<table><thead><tr><th>Username</th><th>Name</th><th>Role</th><th></th></tr></thead><tbody>${rows}</tbody></table>` : '<p class="muted">Loading…</p>'}</div>
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
      `<div class="card tablewrap">${V2.audit ? `<table><thead><tr><th>Time</th><th>Actor</th><th>Action</th><th>Outcome</th><th>Ref</th></tr></thead><tbody>${rows || '<tr><td colspan="5" class="muted">No events.</td></tr>'}</tbody></table>` : '<p class="muted">Loading…</p>'}</div>`;
  }

  function usersPage() {
    if (!isSuper()) return intro('Users', 'Platform users') + '<div class="callout">Platform administrators only.</div>';
    load('users', '/users');
    const rows = (V2.users || []).map(u => `<tr><td>${esc(u.username)}</td><td>${esc(u.display_name)}</td><td>${u.platform_role === 'superadmin' ? badge('platform admin') : ''}</td><td>${u.is_active ? badge('Active') : badge('Disabled', 'err')}</td></tr>`).join('');
    return intro('Users', 'บัญชีผู้ใช้ภายใน (รหัสผ่านเก็บเป็น argon2id hash)') + banner() +
      `<div class="card tablewrap">${V2.users ? `<table><thead><tr><th>Username</th><th>Name</th><th></th><th>Status</th></tr></thead><tbody>${rows}</tbody></table>` : '<p class="muted">Loading…</p>'}</div>
       <div class="title">Create user</div>
       <form class="card" data-v2-form="user"><label class="field">Username<input name="username" required pattern="[A-Za-z0-9._-]{3,64}" maxlength="64" autocomplete="off"></label>
       <label class="field">Display name<input name="display_name" maxlength="100"></label>
       <label class="field">Initial password (min 12 characters)<input name="password" type="password" required minlength="12" maxlength="256" autocomplete="new-password"></label>
       <button class="primary">Create user</button></form>`;
  }

  const inflight = {};
  function load(kind, path) {
    if (V2[kind] !== null || inflight[kind]) return;
    inflight[kind] = true;
    api('GET', path).then(d => { V2[kind] = d; V2.error = ''; }, e => { V2[kind] = []; V2.error = e.message; })
      .finally(() => { inflight[kind] = false; render(); });
  }
  const invalidate = k => { V2[k] = null; };

  // ---- events (delegated; no inline handlers) ----
  document.addEventListener('submit', async ev => {
    const form = ev.target.closest('[data-v2-form]');
    if (!form || !V2.enabled) return;
    ev.preventDefault();
    const f = Object.fromEntries(new FormData(form));
    const kind = form.dataset.v2Form;
    V2.error = '';
    try {
      if (kind === 'login') {
        V2.busy = true; render();
        adopt(await api('POST', '/auth/login', { username: f.username, password: f.password }).then(r => ({ ...r, workspaces: [] })));
        adopt(await api('GET', '/auth/me'));
        S.page = V2.workspaces.length ? 'sources' : 'v2ws';
      } else if (kind === 'workspace') {
        await api('POST', '/workspaces', { name: f.name, slug: f.slug });
        const me = await api('GET', '/auth/me'); V2.workspaces = me.workspaces; S.notice = 'Workspace created';
      } else if (kind === 'member') {
        await api('POST', `/workspaces/${V2.ws}/members`, { username: f.username, role: f.role });
        invalidate('members'); S.notice = 'Member saved';
      } else if (kind === 'user') {
        await api('POST', '/users', { username: f.username, display_name: f.display_name || '', password: f.password });
        invalidate('users'); S.notice = 'User created';
      }
      form.reset?.();
    } catch (e) { V2.error = e.message + (e.cid ? ` (ref ${e.cid.slice(0, 8)})` : ''); }
    V2.busy = false; render();
  });

  document.addEventListener('click', async ev => {
    const el = ev.target.closest('[data-v2]');
    if (!el || !V2.enabled) return;
    const act = el.dataset.v2;
    try {
      if (act === 'logout') { await api('POST', '/auth/logout', {}); reset(); S.page = 'sources'; V2.error = ''; }
      else if (act === 'pick') { setWs(el.dataset.id); }
      else if (act === 'remove') { await api('DELETE', `/workspaces/${V2.ws}/members/${el.dataset.id}`); invalidate('members'); S.notice = 'Member removed'; }
      else if (act === 'refresh-audit') { invalidate('audit'); }
    } catch (e) { return fail(e); }
    render();
  });

  document.addEventListener('change', ev => {
    const sel = ev.target.closest('[data-v2-ws]');
    if (sel) { setWs(sel.value); render(); }
  });

  function setWs(id) {
    V2.ws = id; V2.members = V2.audit = null;
    try { localStorage.setItem(KEY, id); } catch { /* optional convenience */ }
  }

  boot();
})();
