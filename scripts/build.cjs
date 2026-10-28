const fs=require('fs');const path=require('path');const vm=require('vm');
const root=path.resolve(__dirname,'..');const files=['index.html','styles.css','ui-reference-theme.css','app.js','demo-sync.js','sync-ui.js','dataset-workflow.js','real-source-ui.js','prototype.js','assets/utac-logo-source.png','v2-main.js','v2-store.js','v2-table.js','v2-forms.js','v2-capabilities.js','v2-ui.js','v2-ui.css'];
const vendor=JSON.parse(fs.readFileSync(path.join(root,'vendor/tanstack/MANIFEST.json'),'utf8'));
for(const [file,meta] of Object.entries(vendor)){const rel='vendor/tanstack/'+file;if(require('node:crypto').createHash('sha256').update(fs.readFileSync(path.join(root,rel))).digest('hex')!==meta.sha256)throw new Error('Vendor hash mismatch: '+file);files.push(rel);}
files.push('vendor/tanstack/MANIFEST.json');
for(const file of files){const text=fs.readFileSync(path.join(root,file),'utf8');if(file.endsWith('.js')&&!file.startsWith('vendor/')&&file!=='v2-main.js')new vm.Script(text,{filename:file});}
require('node:child_process').execFileSync(process.execPath,['--check','--input-type=module'],{input:fs.readFileSync(path.join(root,'v2-main.js'))});
const out=path.join(root,'dist');fs.mkdirSync(out,{recursive:true});for(const file of files){const target=path.join(out,file);fs.mkdirSync(path.dirname(target),{recursive:true});fs.copyFileSync(path.join(root,file),target);}
console.log('PASS: static build; runtime files and logo asset validated and copied to dist/. Dataset ranking is a deterministic baseline; Real Source requires the same-shell HTTPS Backend. No network or database used.');
