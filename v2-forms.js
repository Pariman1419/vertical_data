(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory;
  else root.V2Forms = factory(root.TanStack);
})(globalThis, function (T) {
  'use strict';
  const matches = (re, text) => typeof text === 'string' && re.exec(text)?.[0] === text;
  function requestError(value) {
    if (!matches(/^[a-z][a-z0-9_]{2,60}$/, value.dataset_name)) return 'Dataset name must be 3–61 lowercase letters, digits or underscores, starting with a letter.';
    const ident = '[A-Za-z_][A-Za-z0-9_]{0,62}';
    const pattern = value.profile === 'pg' ? new RegExp('^' + ident + '\\.' + ident + '$') :
      value.profile === 'scada' ? new RegExp('^' + ident + '\\.' + ident + '\\.' + ident + '$') : null;
    if (!pattern || !matches(pattern, value.remote_object) || value.remote_object.length > 200) return 'Source table does not match the selected profile.';
    if ((value.note || '').length > 500) return 'Note must be at most 500 characters.';
  }
  function filters(columns, values) {
    if (values.length > 5) throw new Error('Use at most five filters.');
    return values.map(f => {
      const type = columns.find(c => c.name === f.column)?.type.toLowerCase();
      const value = String(f.value ?? '');
      const fail = () => { throw new Error('Filter value does not fit ' + (type || 'the selected column') + '.'); };
      if (!type || !['=', '!=', '<', '<=', '>', '>='].includes(f.op)) fail();
      if (/^(u?int)/.test(type)) { if (!matches(/^[+-]?[0-9]+$/, value.trim()) || value.length > 200) fail(); }
      else if (/^(decimal|float|double)/.test(type)) { if (!matches(/^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$/, value.trim()) || !Number.isFinite(Number(value)) || value.length > 200) fail(); }
      else if (/^bool/.test(type)) { if (!/^(true|false)$/i.test(value)) fail(); }
      else if (/^timestamp/.test(type)) { if (!/^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}/.test(value) || !Number.isFinite(Date.parse(value))) fail(); }
      else if (/^date/.test(type)) { if (!matches(/^\d{4}-\d{2}-\d{2}$/, value) || !Number.isFinite(Date.parse(value)) || new Date(value).toISOString().slice(0, 10) !== value) fail(); }
      else if (['utf8', 'largeutf8', 'utf8view'].includes(type)) { if (Array.from(value).length > 200 || value.includes('\0') || value.includes('\\')) fail(); }
      else fail();
      return { column: f.column, op: f.op, value };
    });
  }
  const datasetRequest = () => new T.FormApi({ defaultValues: { profile: 'pg', dataset_name: '', remote_object: '', note: '' },
    validators: { onSubmit: ({ value }) => requestError(value) } });
  const previewFilters = columns => new T.FormApi({ defaultValues: { filters: [] }, validators: { onSubmit: ({ value }) => {
    try { filters(columns, value.filters); } catch (e) { return e.message; }
  } } });
  const active = new WeakSet();
  async function submit(form, callback) {
    if (active.has(form)) return false;
    active.add(form);
    try { await callback(); return true; } finally { active.delete(form); }
  }
  async function validate(form, values) {
    const unmount = form.mount();
    try {
      form.reset(values); await form.validate('submit');
      if (form.state.errors.length) throw new Error(form.state.errors.join(' '));
    } finally { unmount(); }
  }
  const errorMessage = error => error.status === 429 ? 'Source is busy, try again in ' + (Number(error.retryAfter) || 1) + ' s' : error.message;
  return { datasetRequest, previewFilters, requestError, filters, submit, validate, errorMessage };
});
