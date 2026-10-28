const http = require('http');
const fs = require('fs');
const path = require('path');

const root = __dirname;
const port = Number(process.env.PORT || 5173);
const types = {'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.mjs':'text/javascript; charset=utf-8','.json':'application/json; charset=utf-8','.css':'text/css; charset=utf-8','.md':'text/plain; charset=utf-8','.png':'image/png'};
const publicFiles = new Set(['/index.html','/styles.css','/ui-reference-theme.css','/app.js','/demo-sync.js','/sync-ui.js','/dataset-workflow.js','/real-source-ui.js','/prototype.js','/assets/utac-logo-source.png','/docs/U-ETL Factory Data Bridge_Blueprint.md']);
for (const file of ['v2-main.js','v2-store.js','v2-table.js','v2-forms.js','v2-capabilities.js','v2-ui.js','v2-ui.css']) publicFiles.add('/' + file);
publicFiles.add('/v2-jobs.js');
for (const file of Object.keys(JSON.parse(fs.readFileSync(path.join(root,'vendor/tanstack/MANIFEST.json'),'utf8')))) publicFiles.add('/vendor/tanstack/' + file);

http.createServer((req, res) => {
  let requested;
  try { requested = decodeURIComponent(req.url.split('?')[0]); } catch { res.writeHead(400); return res.end('Invalid path'); }
  const relative = requested === '/' ? '/index.html' : requested;
  if (!publicFiles.has(relative)) { res.writeHead(404); return res.end('Not found'); }
  const file = path.resolve(root, '.' + relative);
  if (!file.startsWith(root + path.sep)) { res.writeHead(403); return res.end('Forbidden'); }
  fs.readFile(file, (err, data) => {
    if (err) { res.writeHead(404); return res.end('Not found'); }
    res.writeHead(200, {'Content-Type': types[path.extname(file)] || 'application/octet-stream'});
    res.end(data);
  });
}).listen(port, '127.0.0.1', () => {
  console.log(`U-ETL Prototype running at http://localhost:${port}`);
  console.log('Press Ctrl+C to stop.');
});
