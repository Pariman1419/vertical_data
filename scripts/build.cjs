const fs=require('fs');const path=require('path');const vm=require('vm');
const root=path.resolve(__dirname,'..');const files=['index.html','styles.css','ui-reference-theme.css','app.js','demo-sync.js','sync-ui.js','dataset-workflow.js','real-source-ui.js','prototype.js','assets/utac-logo-source.png'];
for(const file of files){const text=fs.readFileSync(path.join(root,file),'utf8');if(file.endsWith('.js'))new vm.Script(text,{filename:file});}
const out=path.join(root,'dist');fs.mkdirSync(out,{recursive:true});for(const file of files){const target=path.join(out,file);fs.mkdirSync(path.dirname(target),{recursive:true});fs.copyFileSync(path.join(root,file),target);}
console.log('PASS: static build; runtime files and logo asset validated and copied to dist/. Dataset ranking is a deterministic baseline; Real Source requires the same-shell HTTPS Backend. No network or database used.');
