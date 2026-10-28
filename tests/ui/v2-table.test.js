const { test, before } = require('node:test');
const assert = require('node:assert/strict');
let table;
before(async () => {
  await import('../../vendor/tanstack/index.js');
  table = require('../../v2-table.js')(globalThis.TanStack);
});
test('300 columns by 1000 rows exposes only the viewport and overscan', () => {
  const columns = Array.from({ length: 300 }, (_, i) => ({ name: 'c' + i, type: 'Utf8' }));
  const rows = Array.from({ length: 1000 }, () => Array(300).fill('x'));
  const model = table._model({ columns, rows });
  assert.equal(model.columns().length, 20);
  model.setVisibleColumns(columns.map(c => c.name));
  for (const [top, left] of [[0, 0], [12000, 22000], [30000, 50000]]) {
    const view = model.window({ width: 800, height: 600, scrollTop: top, scrollLeft: left });
    assert.ok(view.rows.length <= 60); assert.ok(view.columns.length <= 40);
    assert.ok(view.cells.length <= 2400);
  }
});
test('sorting is stable and compares numeric strings without losing precision', () => {
  const model = table._model({ columns: [{ name: 'n', type: 'Int64' }, { name: 'label', type: 'Utf8' }],
    rows: [['10', 'a'], ['2', 'b'], ['2', 'c'], ['9007199254740993', 'd'], ['9007199254740992', 'e']] });
  model.sort('n');
  assert.deepEqual(model.rows().map(r => r.original[1]), ['b', 'c', 'a', 'e', 'd']);
});
test('hostile values stay unchanged and display is capped at 200 characters', () => {
  for (const text of ['<script>alert(1)</script>', '"quotes\' here', 'x'.repeat(10000)]) {
    const cell = table.cell(text);
    assert.equal(cell.title, text); assert.ok(cell.text.length <= 200);
    if (text.length <= 200) assert.equal(cell.text, text);
  }
});
test('column picker search is case insensitive', () => {
  const model = table._model({ columns: [{ name: 'Machine_ID', type: 'Utf8' }, { name: 'Lot', type: 'Utf8' }], rows: [] });
  assert.deepEqual(model.search('MACHINE').map(c => c.name), ['Machine_ID']);
});
