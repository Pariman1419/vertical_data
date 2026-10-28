const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
test('static build includes the local v2 module dependency tree', () => {
  const root = path.resolve(__dirname, '../..');
  execFileSync(process.execPath, ['scripts/build.cjs'], { cwd: root, stdio: 'pipe' });
  const dist = path.join(root, 'dist'), visited = new Set();
  function visit(relative) {
    if (visited.has(relative)) return;
    visited.add(relative);
    const file = path.join(dist, relative);
    assert.ok(fs.existsSync(file), 'missing runtime asset: ' + relative);
    if (relative !== 'v2-main.js' && !relative.startsWith('vendor/tanstack/')) return;
    if (!relative.endsWith('.js') && !relative.endsWith('.mjs')) return;
    const source = fs.readFileSync(file, 'utf8');
    const imports = source.matchAll(/^\s*(?:import\s+(?:[^;]*?\bfrom\s*)?|export\s+[^;]*?\bfrom\s*)['"]([^'"]+)['"]/gm);
    for (const [, specifier] of imports) {
      assert.ok(specifier.startsWith('.'), 'bare browser import: ' + specifier);
      visit(path.posix.normalize(path.posix.join(path.posix.dirname(relative), specifier)));
    }
  }
  const html = fs.readFileSync(path.join(dist, 'index.html'), 'utf8');
  for (const [, name] of html.matchAll(/(?:src|href)="([^"]+)"/g)) visit(name);
  assert.ok(visited.has('vendor/tanstack/store/store.js'));
});
