const { test, before } = require('node:test');
const assert = require('node:assert/strict');
let forms;
before(async () => {
  await import('../../vendor/tanstack/index.js');
  forms = require('../../v2-forms.js')(globalThis.TanStack);
});
test('dataset names agree with the server whitelist', () => {
  const cases = [['abc', true], ['ab_', true], ['my_set2', true], ['a'.repeat(61), true], ['abc_123', true],
    ['Bad', false], ['x', false], ['has space', false], ['a-b', false], ['name\nparams: *x', false], ['1abc', false], ['a'.repeat(70), false]];
  for (const [dataset_name, valid] of cases) {
    assert.equal(forms.requestError({ profile: 'pg', dataset_name, remote_object: 'schema.table' }) === undefined, valid, dataset_name);
  }
  assert.ok(forms.datasetRequest() instanceof globalThis.TanStack.FormApi);
});
test('remote objects mirror profile-specific server rules', () => {
  for (const [profile, remote_object, valid] of [['pg', 'a.b', true], ['pg', 'a.b.c', false], ['pg', '1a.b', false],
    ['scada', 'db.dbo.Table1', true], ['scada', 'db..t', false], ['pg', 'a.b\n', false]]) {
    assert.equal(forms.requestError({ profile, remote_object, dataset_name: 'abc' }) === undefined, valid);
  }
});
test('Int64 filters reject fractional input and preserve large integers', () => {
  const columns = [{ name: 'id', type: 'Int64' }];
  assert.throws(() => forms.filters(columns, [{ column: 'id', op: '=', value: '1.5' }]));
  assert.deepEqual(forms.filters(columns, [{ column: 'id', op: '=', value: '9007199254740993' }]),
    [{ column: 'id', op: '=', value: '9007199254740993' }]);
  assert.ok(forms.previewFilters(columns) instanceof globalThis.TanStack.FormApi);
});
test('a second submit is ignored while the same form is in flight', async () => {
  let complete, calls = 0;
  const form = forms.datasetRequest();
  const first = forms.submit(form, async () => { calls++; await new Promise(r => { complete = r; }); });
  assert.equal(await forms.submit(form, async () => { calls++; }), false);
  complete(); await first; assert.equal(calls, 1);
});
test('429 maps to a message containing Retry-After seconds', () => {
  assert.match(forms.errorMessage({ status: 429, retryAfter: 7 }), /Source is busy.*7 s/);
});
test('FormApi validation actually rejects bad request and filter values', async () => {
  await assert.rejects(forms.validate(forms.datasetRequest(), { profile: 'pg', dataset_name: 'Bad', remote_object: 'a.b' }));
  await forms.validate(forms.datasetRequest(), { profile: 'pg', dataset_name: 'good', remote_object: 'a.b' });
  await assert.rejects(forms.validate(forms.previewFilters([{ name: 'id', type: 'Int64' }]),
    { filters: [{ column: 'id', op: '=', value: '1.5' }] }));
});
test('string filters reject backslashes in the parser and FormApi validation', async () => {
  for (const type of ['Utf8', 'LargeUtf8', 'Utf8View']) {
    const columns = [{ name: 'text', type }];
    for (const value of ['\\', 'a\\b', "x\\'; DROP TABLE t; --"]) {
      const filters = [{ column: 'text', op: '=', value }];
      assert.throws(() => forms.filters(columns, filters));
      await assert.rejects(forms.validate(forms.previewFilters(columns), { filters }));
    }
  }
});
