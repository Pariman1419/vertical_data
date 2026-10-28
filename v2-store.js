(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory;
  else Object.assign(root, factory(root.TanStack, root));
})(globalThis, function (T, env) {
  'use strict';
  const state = new T.Store({ enabled: false, checked: false, user: null, csrf: '', workspaces: [], ws: null,
    members: null, audit: null, users: null, conns: null, catall: null, cat: null, reqs: null, sel: null,
    result: null, error: '', busy: false, previewBusy: false, previewObject: '', previewLimit: 50, filters: [] });
  const V2Store = {
    get: key => state.state[key],
    set: patch => state.setState(old => ({ ...old, ...patch })),
    subscribe: fn => state.subscribe(fn)
  };
  const client = new T.QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 30000, gcTime: env.document ? 300000 : Infinity } } });
  const V2Query = {
    fetch(key, path, opts = {}) {
      return client.fetchQuery({ queryKey: key, staleTime: opts.staleMs ?? 30000, queryFn: async ({ signal }) => {
        const abort = opts.signal ? AbortSignal.any([signal, opts.signal]) : signal;
        const res = await env.fetch(path, { method: 'GET', credentials: 'same-origin', cache: 'no-store', signal: abort });
        let data = null; try { data = await res.json(); } catch { /* empty error response */ }
        if (!res.ok) {
          const error = new Error(data?.error?.message || 'Request failed');
          error.status = res.status; error.cid = data?.error?.correlation_id;
          error.retryAfter = Number(res.headers.get('Retry-After')) || 1;
          throw error;
        }
        return data;
      } });
    },
    invalidate: prefix => client.invalidateQueries({ queryKey: prefix, refetchType: 'none' }),
    clear() { client.clear(); }
  };
  const pages = new Set(['sources', 'workspaces', 'members', 'audit', 'users', 'account']);
  const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  const V2Route = {
    current() {
      const match = /^#\/([a-z]+)(?:\/([0-9a-f-]+))?$/.exec(env.location.hash);
      if (!match || !pages.has(match[1]) || (match[2] && (match[1] !== 'sources' || !uuid.test(match[2])))) return { page: 'sources' };
      return { page: match[1], ...(match[2] ? { connection: match[2] } : {}) };
    },
    go(page, params = {}) {
      if (!pages.has(page) || (params.connection && (page !== 'sources' || !uuid.test(params.connection)))) throw new Error('Invalid route');
      env.location.hash = '#/' + page + (params.connection ? '/' + params.connection : '');
    }
  };
  return { V2Store, V2Query, V2Route };
});
