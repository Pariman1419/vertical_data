/* Synthetic, browser-memory reconciliation model. Not a database connector. */
(function(root){
 const copy=x=>JSON.parse(JSON.stringify(x));
 const blank=()=>({extracted:0,inserted:0,updated:0,unchanged:0,quarantined:0,filtered:0,duplicate:0,pending:0});
 class DemoSync {
  constructor(){
   this.scope='demo-job/src-mes+src-qms/analytics-demo/generation-1';this.strategy='bounded-fixture-reconciliation-v1';
   this.tables=['MES.PROCESS_EVENT','QMS.INSPECTION'];this.source=[];this.target=[];this.history=[];this.active=null;this.seq=0;this.nextRun=1;
   this.watermark=0;this.lastSync=null;this.lastAttempt=null;this.initialized=false;this.late=null;this.tableState={};this.quarantine=[];this.generation=1;
   for(const table of this.tables)this.tableState[table]={lastSync:null,lastAttempt:null,watermark:0,initialized:false};
   this.add({table:this.tables[0],id:'102',lot:'000123',equipment:'EQ-17',process:'P-ETCH',value:'ok'});
   this.add({table:this.tables[0],id:'103',lot:'000124',equipment:'EQ-17',process:'P-ETCH',value:'ok'});
   this.add({table:this.tables[1],id:'882',lot:'UTL2-000123',equipment:'EQ-03',process:'P-TEST',value:'ok'});
  }
  add(row){this.source.push({...row,seq:++this.seq});}
  prepare(scenario){
   if(this.active)throw Error('A demo run is already running');
   if(scenario==='new'){this.add({table:this.tables[0],id:String(200+this.seq),lot:'000125',equipment:'EQ-18',process:'P-ETCH',value:'new'});this.source[0].value='late update';this.source[0].seq=++this.seq;}
   if(scenario==='failure')this.add({table:this.tables[0],id:String(400+this.seq),lot:'000126',equipment:'EQ-19',process:'P-TEST',value:'retry fixture'});
   if(scenario==='partial')this.add({table:this.tables[0],id:String(500+this.seq),lot:'000128',equipment:'EQ-21',process:'P-TEST',value:'partial fixture'});
   if(scenario==='warning')this.add({table:this.tables[0],id:String(600+this.seq),lot:'',equipment:'EQ-22',process:'P-TEST',value:'quarantine fixture'});
   if(scenario==='late'&&!this.late&&!this.source.some(r=>r.table===this.tables[0]&&r.id==='101')){this.late={table:this.tables[0],id:'101',lot:'000122',equipment:'EQ-16',process:'P-ETCH',value:'late commit'};}
  }
  begin(mode,scenario,revision=1,retryOf=null){
   if(this.active)throw Error('A demo run is already running');
   if(mode==='Incremental'&&!this.initialized)throw Error('Initial Load must publish first');
   if(mode==='Initial'&&this.initialized)throw Error('Initial already published; use Incremental');
   if(!['Initial','Incremental','Full Refresh'].includes(mode))throw Error('Unknown mode');
   const old=retryOf&&this.history.find(r=>r.id===retryOf);
   if(retryOf&&(!old||old.state!=='failed'))throw Error('Retry requires a failed run');
   if(!old)this.prepare(scenario);
   const scopeTables=old?old.tables.filter(t=>t.state==='failed'||t.state==='cancelled').map(t=>t.table):(this.selectedTables||this.tables);
   const rows=copy((old?old.snapshot:this.source).filter(r=>scopeTables.includes(r.table)));const upper=old?old.upper:this.seq;
   const run={id:'RUN-DEMO-'+String(this.nextRun++).padStart(3,'0'),state:'running',mode:old?old.mode:mode,scenario:old?'retry':scenario,scope:this.scope,strategy:this.strategy,bundle:old?old.bundle:'DEMO-BUNDLE-'+revision,lower:old?old.lower:this.watermark,upper,snapshot:rows,retryOf,startedAt:new Date().toISOString(),endedAt:null,counts:blank(),tables:scopeTables.map(table=>({table,state:'running',counts:blank(),upper:Math.max(0,...rows.filter(r=>r.table===table).map(r=>r.seq))}))};
   this.lastAttempt=run.startedAt;for(const t of run.tables)this.tableState[t.table].lastAttempt=run.startedAt;
   this.active=run;this.history.unshift(run);
   if(!old&&scenario==='during')this.add({table:this.tables[0],id:String(300+this.seq),lot:'000127',equipment:'EQ-20',process:'P-ETCH',value:'arrived outside boundary'});
   if(!old&&scenario==='late'&&this.late){this.add(this.late);this.late=null;}
   return run;
  }
  finish(){
   const run=this.active;if(!run)throw Error('No active run');
   if(run.scenario==='failure'||(run.mode==='Full Refresh'&&run.scenario==='partial')){
    run.state='failed';run.counts.extracted=run.snapshot.length;run.counts.pending=run.snapshot.length;
    for(const t of run.tables){t.state='failed';t.counts.extracted=run.snapshot.filter(r=>r.table===t.table).length;t.counts.pending=t.counts.extracted;}
   }else{
    if(run.mode==='Full Refresh')this.target=this.target.filter(r=>!run.tables.some(t=>t.table===r.table));
    for(const t of run.tables){
     const incoming=run.snapshot.filter(r=>r.table===t.table);t.counts.extracted=incoming.length;
     if(run.scenario==='partial'&&t.table===run.tables[run.tables.length-1].table){t.state='failed';t.counts.pending=incoming.length;for(const k of Object.keys(run.counts))run.counts[k]+=t.counts[k];continue;}
     for(const row of incoming){const key=r=>r.table===row.table&&r.id===row.id;const idx=this.target.findIndex(key);
      if(!row.lot){t.counts.quarantined++;if(!this.quarantine.some(q=>q.table===row.table&&q.id===row.id))this.quarantine.push({...copy(row),runId:run.id,rule:'required lot_id',status:'unresolved'});continue;}
      if(idx<0){this.target.push(copy(row));t.counts.inserted++;}
      else if(['lot','equipment','process','value'].some(field=>this.target[idx][field]!==row[field])){this.target[idx]=copy(row);t.counts.updated++;}
      else t.counts.unchanged++;
      const quarantined=this.quarantine.find(q=>q.table===row.table&&q.id===row.id);if(quarantined){quarantined.status='resolved';quarantined.resolvedRunId=run.id;}
     }
     t.state=t.counts.quarantined?'succeeded_with_warnings':'succeeded';const ts=this.tableState[t.table];ts.watermark=Math.max(ts.watermark,t.upper);ts.initialized=true;
     for(const k of Object.keys(run.counts))run.counts[k]+=t.counts[k];
    }
    run.state=run.tables.some(t=>t.state==='failed')?'failed':run.counts.quarantined?'succeeded_with_warnings':'succeeded';run.result=run.state==='failed'?'Partial failure':run.counts.quarantined?'Published with warnings':run.counts.inserted+run.counts.updated===0?'No new data':'Published';
    if(run.state!=='failed')this.watermark=Math.max(this.watermark,run.upper);this.initialized=(this.selectedTables||this.tables).every(t=>this.tableState[t].initialized);
    if(run.mode==='Full Refresh'&&run.state!=='failed')this.generation++;
   }
   run.endedAt=new Date().toISOString();
   if(run.state==='succeeded'||run.state==='succeeded_with_warnings')this.lastSync=run.endedAt;
   for(const t of run.tables)if(t.state==='succeeded'||t.state==='succeeded_with_warnings')this.tableState[t.table].lastSync=run.endedAt;
   this.active=null;return run;
  }
  cancel(){const r=this.active;if(!r)return;for(const t of r.tables){t.state='cancelled';t.counts.extracted=r.snapshot.filter(x=>x.table===t.table).length;t.counts.pending=t.counts.extracted;r.counts.extracted+=t.counts.extracted;r.counts.pending+=t.counts.pending;}r.state='cancelled';r.result='Cancelled before Publish';r.endedAt=new Date().toISOString();this.active=null;return r;}
 }
 if(typeof module!=='undefined')module.exports={DemoSync};else root.DemoSync=DemoSync;
})(typeof globalThis!=='undefined'?globalThis:this);
