const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const uiSource = fs.readFileSync(path.join(__dirname, '..', 'real-source-ui.js'), 'utf8');
const appSource = fs.readFileSync(path.join(__dirname, '..', 'prototype.js'), 'utf8');

test('Source catalog filtering happens locally after loading the complete visible catalog', () => {
  const result = vm.runInNewContext(`${uiSource}
    realSourceUI.catalogObjects = [
      {schema:'ALPHA', name:'WIP_CURRENT', kind:'TABLE'},
      {schema:'ALPHA', name:'WIP_HISTORY', kind:'VIEW'},
      {schema:'BETA', name:'LOT_DETAIL', kind:'MATERIALIZED VIEW'},
      {schema:'GAMMA', name:'OTHER', kind:'TABLE'}
    ];
    realSourceUI.catalogComplete = true;
    realSourceUI.catalogSchemaOptions = ['ALPHA','BETA','GAMMA'];
    realSourceUI.catalogSelectedSchemas = ['ALPHA','BETA'];
    realSourceUI.catalogTypeFilter = 'view';
    realSourceUI.catalogObjectSearch = 'wip';
    ({count: realSourceFilteredCatalog().length,
      name: realSourceFilteredCatalog()[0]?.name,
      schemaCount: realSourceUI.catalogSchemaOptions.length,
      complete: realSourceUI.catalogComplete});`, {});
  assert.deepEqual(JSON.parse(JSON.stringify(result)), {
    count: 1, name: 'WIP_HISTORY', schemaCount: 3, complete: true,
  });
});

test('workspace navigation labels the local storage page U-ETL Database', () => {
  const navigation=fs.readFileSync(path.join(__dirname,'..','app.js'),'utf8');
  assert.match(navigation,/\['copies','U-ETL Database'\]/);
  assert.doesNotMatch(navigation,/\['copies','U-ETL DataBridge'\]/);
});

test('discovered metadata snapshots persist without sample values and restore from shared Backend metadata', () => {
  assert.match(appSource,/const realSourceSnapshotStorageKey='utl-etl-real-source-snapshots-v1'/);
  assert.match(appSource,/localStorage\.setItem\(realSourceSnapshotStorageKey,JSON\.stringify\(Object\.values\(window\.realSourceSnapshots/);
  assert.match(appSource,/savedRealSourceSnapshots=parsed\.filter\(s=>s&&typeof s\.sourceId==='string'/);
  assert.match(appSource,/map\(\(\{sourceId,sourceName,configRevision,schema,table,object,columns,keys,foreign_keys,discoveredAt,limitations\}\)=>\(\{sourceId,sourceName,configRevision,schema,table,object,columns,keys,foreign_keys,discoveredAt,limitations\}\)\)/);
  assert.match(appSource,/snapshot\.configRevision!==\(profile\.revision\|\|1\)/);
  assert.match(uiSource,/batchResults\.forEach\(item=>window\.cacheRealSourceSnapshot\?\.\(item\.metadata,id\)\)/);
  assert.match(uiSource,/catalogKeys\.has\(`\$\{m\.schema\}\|\$\{m\.name\}`\)/);
});

test('U-ETL Database lists every primary-key column, including composite keys', () => {
  assert.match(appSource, /<th>Primary key<\/th>/);
  assert.match(appSource, /collectionPrimaryKeyMarkup\(s\)/);
  const helper=appSource.match(/function collectionPrimaryKeyMarkup\(snapshot\)\{[\s\S]*?\nfunction copies\(/)?.[0]||'';
  const result=vm.runInNewContext(`${helper.slice(0,helper.lastIndexOf('\nfunction copies('))}
    function safe(value){return String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');}
    JSON.stringify({composite:collectionPrimaryKeyMarkup({keys:[['PK_T','P','ORDER_NO',2],['FK_T','R','OTHER_ID',1],['PK_T','P','LOT_NO',1]]}),none:collectionPrimaryKeyMarkup({keys:[]}),unknown:collectionPrimaryKeyMarkup({})});`,{});
  assert.deepEqual(JSON.parse(result),{
    composite:'<span class="primary-key-entry"><strong>PK_T</strong><small>Key columns: LOT_NO, ORDER_NO</small></span>',
    none:'<span class="muted">No primary key</span>',
    unknown:'<span class="muted">Not discovered</span>',
  });
});

test('Primary key constraint and its columns render on separate lines with smaller column text', () => {
  assert.match(appSource, /<strong>\$\{safe\(name\)\}<\/strong><small>Key columns:/);
  const css=fs.readFileSync(path.join(__dirname,'..','styles.css'),'utf8');
  assert.match(css,/\.primary-key-cell \.primary-key-entry small\{font-size:11px/);
});

test('Database Connection and U-ETL Database table typography matches and cells top-align', () => {
  const css=fs.readFileSync(path.join(__dirname,'..','ui-reference-theme.css'),'utf8');
  assert.match(css,/\.connection-table-head\s*\{[^}]*font-size:\s*13px/s);
  assert.match(css,/\.connection-cells\s*\{[^}]*align-items:\s*start;[^}]*font-size:\s*13px/s);
  assert.match(css,/\.table td\s*\{[^}]*font-size:\s*13px;[^}]*vertical-align:\s*top/s);
});

test('U-ETL Database stores ordered table load groups, not join/key relationships', () => {
  assert.match(appSource,/const collectionLoadGroupsStorageKey='utl-etl-collection-load-groups-v1'/);
  assert.match(appSource,/Create load group/);
  assert.match(appSource,/function addCollectionLoadItem\(\)/);
  assert.match(appSource,/function moveCollectionLoadItem\(index,offset\)/);
  assert.match(appSource,/function saveCollectionLoadGroup\(event\)/);
  assert.match(appSource,/function editCollectionLoadGroup\(id\)/);
  assert.match(appSource,/Sequential · Manual run/);
  assert.match(appSource,/runLocalCollectionGroup/);
  assert.match(appSource,/later tables are not started/);
  assert.match(appSource,/renderCollectionRelationships=function\(snapshots\)\{const byKey=new Map\(snapshots\.map/);
});

test('U-ETL Database exposes a confirmed local bounded Extract & Load and honest persisted status', () => {
  assert.match(appSource,/Rows to load per table \(default 100\)/);
  assert.match(appSource,/data-local-load-rows/);
  assert.match(appSource,/>Load data</);
  assert.match(appSource,/max="2147483647" value="100"/);
  assert.match(appSource,/runLocalExtractLoad\(sourceId,schema,table\)/);
  assert.match(appSource,/runLocalCollectionGroup/);
  assert.match(appSource,/refreshLocalTargetStatuses/);
  assert.match(uiSource,/realSourceWaitForProfileJob\(profileId,action,data\)/);
});

test('discovered metadata table filter wraps long schema.table labels without overlap', () => {
  const css=fs.readFileSync(path.join(__dirname,'..','styles.css'),'utf8');
  assert.match(css,/\.source-manager-drawer \.metadata-filter-options\s*\{grid-template-columns:repeat\(auto-fit,minmax\(min\(100%,240px\),1fr\)\)\}/);
  assert.match(css,/\.source-manager-drawer \.metadata-filter-options label span\s*\{min-width:0;overflow-wrap:anywhere;word-break:break-word\}/);
});

test('Source catalog loads bounded pages sequentially before exposing filters', () => {
  assert.match(uiSource, /while\(realSourceUI\.catalogNextCursor\)/);
  assert.match(uiSource, /page_size:100/);
  assert.match(uiSource, /realSourceUI\.catalogComplete\?`<div class="callout">Visible Table\/View catalog loaded/);
  assert.match(uiSource, /realSourceFilteredCatalog\(\)/);
});

test('catalog paging and reload controls appear above and below the table', () => {
  const markup = uiSource.match(/function realSourceCatalogMarkup\(\)[\s\S]*?\nfunction /)?.[0] || '';
  assert.match(uiSource, /function realSourceCatalogPaginationMarkup\(page,pages,position\)/);
  assert.match(markup, /<div class="tablewrap"><table class="table"><thead><tr><th>Schema<\/th>/);
  assert.doesNotMatch(markup, /catalog-pagination-top/);
  assert.match(uiSource, /realSourceAutoSelectMarkup\(\)\}\$\{realSourceCatalogPaginationMarkup\([\s\S]*?'top'\)\}/);
  assert.equal((markup.match(/realSourceCatalogPaginationMarkup\(page,pages,'bottom'\)/g) || []).length, 1);
  assert.match(uiSource, /catalog-pagination-\$\{position\}/);
  assert.match(uiSource, /realSourceSetVisibleCatalogPage\(\$\{page-1\}\)/);
  assert.match(uiSource, /realSourceSetVisibleCatalogPage\(\$\{page\+1\}\)/);
  assert.match(uiSource, /realSourceLoadAllCatalog\(true\)/);
  const css = fs.readFileSync(path.join(__dirname,'..','ui-reference-theme.css'),'utf8');
  assert.match(css, /\.source-manager-drawer \.catalog-pagination-top\s*\{[^}]*margin: 0 0 4px/s);
  assert.match(css, /\.source-manager-drawer \.catalog-pagination button\s*\{[^}]*font-size: 12px/s);
  assert.match(css, /\.source-manager-drawer \.catalog-pagination button\s*\{[^}]*min-height: 28px/s);
});

test('each catalog row offers an independent structure/sample preview without selecting it for a Dataset', async () => {
  assert.match(uiSource, /View structure \/ sample/);
  const result = await vm.runInNewContext(`${uiSource}
    let requested=null, notifications=[];
    const checked=[{value:'LOT_NO'}];
    const document={querySelectorAll(){return checked;},getElementById(id){return id==='catalog-preview-budget-ack'?{checked:true}:id==='catalog-preview-rows'?{value:'5'}:null;},querySelector(){return null;}};
    function notify(value){notifications.push(value);}
    realSourceUI.profileId='src';realSourceUI.config={timeout:12};realSourceUI.profiles={src:{connected:true}};
    realSourceUI.catalogObjects=[{schema:'S',name:'V1',kind:'VIEW'}];
    realSourceUI.batchResults=[{schema:'S',name:'V1',ok:true,metadata:{schema:'S',table:'V1',object:[['S','V1','VIEW']],columns:[['LOT_NO',1,'VARCHAR2','N']],keys:[],foreign_keys:[],limitations:'visible metadata'}}];
    realApi=async(path,data)=>{if(path==='sample'){requested=data;return {job_id:'sample-job'};}if(path==='jobs/sample-job')return {action:'sample',state:'read_completed',ended_at:'now',result:{columns:['LOT_NO'],rows:[['L-1']],sample_count:1}};throw new Error('Unexpected API path '+path);};
    const key=realSourceCatalogKey(realSourceUI.catalogObjects[0]);
    (async()=>{await realSourcePreviewObject(key);const selectedBefore=realSourceUI.catalogSelectedObjects.length;await realSourceReadObjectPreview();return JSON.stringify({selectedBefore,selectedAfter:realSourceUI.catalogSelectedObjects.length,kind:realSourceUI.catalogPreview.kind,requested,sample:realSourceUI.catalogPreview.sample,markup:realSourceCatalogPreviewMarkup(),notifications});})();`, {setTimeout:fn=>fn()});
  const observed=JSON.parse(result);
  assert.equal(observed.selectedBefore,0);
  assert.equal(observed.selectedAfter,0);
  assert.equal(observed.kind,'VIEW');
  assert.deepEqual(observed.requested,{profile_id:'src',schema:'S',table:'V1',timeout:12,sample_rows:5,batch_size:5,columns:['LOT_NO'],budget_ack:true});
  assert.deepEqual(observed.sample.rows,[['L-1']]);
  assert.match(observed.markup,/Example values · 1 rows · not saved/);
  assert.deepEqual(observed.notifications,[]);
});

test('Select all sample fields affects only previewable fields and does not rerender the catalog', () => {
  assert.match(uiSource, /Select all sample fields/);
  const result=vm.runInNewContext(`${uiSource}
    const previewFields=[{checked:false},{checked:false}];
    let query='';
    const document={querySelectorAll(selector){query=selector;return previewFields;}};
    realSourceSetAllPreviewColumns(true);
    const selected=previewFields.map(field=>field.checked);
    realSourceSetAllPreviewColumns(false);
    JSON.stringify({query,selected,cleared:previewFields.map(field=>field.checked)});`,{});
  assert.deepEqual(JSON.parse(result),{
    query:'.catalog-preview-column',selected:[true,true],cleared:[false,false],
  });
});

test('column-key Auto-select honors every-key mode, object type and multi-line input', async () => {
  const result=await vm.runInNewContext(`${uiSource}
    const controls={
      'catalog-auto-keynames':{value:' lot_no\\nORDER_NO, LOT_NO '},
      'catalog-auto-mode':{value:'all'},'catalog-auto-kind':{value:'view'},
    };
    const selectionStatus={textContent:'No object checked.'},discoverButton={disabled:true};
    const document={getElementById(id){return controls[id]||({'catalog-selection-status':selectionStatus,'discover-checked-object':discoverButton})[id]||null;},querySelector(){return null;}};
    let request=null;
    realSourceUI.profileId='src';realSourceUI.profiles={src:{connected:true}};realSourceUI.catalogComplete=true;
    realSourceUI.catalogObjects=[{schema:'S',name:'T1',kind:'TABLE'},{schema:'S',name:'V1',kind:'VIEW'},{schema:'S',name:'V2',kind:'VIEW'}];
    realSourceWaitForJob=async(action,data)=>{request={action,data};return {result:{objects:[{schema:'S',name:'T1'},{schema:'S',name:'V1'}],truncated:false}};};
    (async()=>{await realSourceAutoSelectByColumns();return JSON.stringify({request,selected:realSourceUI.catalogSelectedObjects,status:realSourceUI.catalogAutoStatus,buttonDisabled:discoverButton.disabled,selectionStatus:selectionStatus.textContent});})();`,{});
  assert.deepEqual(JSON.parse(result),{
    request:{action:'match_columns',data:{keynames:['LOT_NO','ORDER_NO'],match_mode:'all',timeout:15}},
    selected:[{schema:'S',name:'V1',kind:'VIEW'}],
    status:'1 View object(s) selected · all keyname match',buttonDisabled:false,
    selectionStatus:'1 object(s) checked · all checked objects will be discovered sequentially (maximum 20 per run).',
  });
});

test('Auto-select controls sit immediately before the catalog table and use the object-row font size', () => {
  const result=vm.runInNewContext(`${uiSource}
    let placement=null,markup='';
    const panel={querySelector(selector){return selector===':scope > .tablewrap'?{insertAdjacentHTML(where,html){placement=where;markup=html;}}:null;}};
    realSourcePlaceAutoSelect(panel);
    JSON.stringify({placement,hasButton:markup.includes('Auto-select')});`,{});
  assert.deepEqual(JSON.parse(result),{placement:'beforebegin',hasButton:true});
  assert.match(fs.readFileSync(path.join(__dirname,'..','ui-reference-theme.css'),'utf8'),/\.source-manager-drawer \.catalog-auto-select\s*\{[^}]*font-size: 13px/s);
});

test('Clear all Table/View selections unchecks the list without deleting the loaded catalog or discoveries', () => {
  assert.match(uiSource,/Clear all selections/);
  const result=vm.runInNewContext(`${uiSource}
    let liveSourceDiscovery={schema:'S',table:'T'},liveSourceDraft={target:'target'},invalidated='';
    function invalidateDatasetRequest(reason){invalidated=reason;}
    const checks=[{checked:true},{checked:true}],status={textContent:''},discover={disabled:false},details={cleared:false,replaceChildren(){this.cleared=true;}};
    const document={querySelector(){return null;},querySelectorAll(selector){return selector==='.catalog-object-checkbox:checked'?checks:[];},getElementById(id){return ({'catalog-selection-status':status,'discover-checked-object':discover,'real-source-discovery-results':details})[id]||null;}};
    realSourceUI.profileId='src';realSourceUI.catalogSelectedObjects=[{schema:'S',name:'T',kind:'TABLE'}];realSourceUI.catalogComplete=true;realSourceUI.catalogObjects=[{schema:'S',name:'T',kind:'TABLE'}];realSourceUI.schema='S';realSourceUI.table='T';realSourceUI.metadata={schema:'S',table:'T'};realSourceUI.batchResults=[{schema:'S',name:'T',ok:true}];
    realSourceClearCatalogSelection();
    JSON.stringify({checked:checks.map(c=>c.checked),selected:realSourceUI.catalogSelectedObjects.length,catalog:realSourceUI.catalogObjects.length,complete:realSourceUI.catalogComplete,batch:realSourceUI.batchResults.length,schema:realSourceUI.schema,metadata:realSourceUI.metadata,status:status.textContent,buttonDisabled:discover.disabled,detailsCleared:details.cleared,invalidated});`,{});
  assert.deepEqual(JSON.parse(result),{
    checked:[false,false],selected:0,catalog:1,complete:true,batch:1,schema:'',metadata:null,
    status:'No object checked.',buttonDisabled:true,detailsCleared:true,
    invalidated:'All Oracle catalog object selections cleared',
  });
});

test('Source catalog view state remains session-only; it is not written to browser storage', () => {
  assert.doesNotMatch(uiSource,/localStorage/);
  const result=vm.runInNewContext(`${uiSource}
    realSourceUI.profileId='iot';realSourceUI.catalogObjects=[{schema:'S',name:'T',kind:'TABLE'}];realSourceUI.catalogComplete=true;
    realSourceSaveProfileViewState();realSourceUI.catalogObjects=[];realSourceUI.catalogComplete=false;realSourceUI.profileId=null;
    let liveSourceDiscovery=null,liveSourceDraft=null;realSourceActivateProfile('iot');
    JSON.stringify({restored:realSourceUI.catalogObjects[0].name,complete:realSourceUI.catalogComplete});`,{});
  assert.deepEqual(JSON.parse(result),{restored:'T',complete:true});
});

test('opening Manage refreshes the active profile catalog from the shared Backend without reconnecting', () => {
  assert.match(appSource, /async function manageSourceConnection\(id\)/);
  assert.match(appSource, /realSourceUI\.notice='Opening saved catalog…';S\.drawer='source-manager';render\(\);await realSourceRestoreCatalog\(id\)/);
  assert.match(uiSource, /async function realSourceRestoreCatalog\(id\)/);
  assert.match(uiSource, /catalog\/cache\?profile_id=\$\{encodeURIComponent\(id\)\}/);
});

test('catalog row checkboxes preserve multiple selections and track the active Discovery target', () => {
  const result = vm.runInNewContext(`${uiSource}
    let liveSourceDiscovery = null;
    let liveSourceDraft = null;
    function invalidateDatasetRequest() {}
    function render() {}
    const document = {getElementById(){return null;}};
    const first = {dataset:{schema:'ALPHA',object:'T1',kind:'TABLE'},checked:true};
    const second = {dataset:{schema:'BETA',object:'V1',kind:'VIEW'},checked:true};
    realSourceToggleCatalogObject(first);
    realSourceToggleCatalogObject(second);
    const afterChecks = {count:realSourceUI.catalogSelectedObjects.length, schema:realSourceUI.schema, table:realSourceUI.table};
    first.checked = false;
    realSourceToggleCatalogObject(first);
    JSON.stringify({afterChecks, remaining:realSourceUI.catalogSelectedObjects.map(o=>o.schema+'.'+o.name), active:realSourceUI.schema+'.'+realSourceUI.table});`, {});
  assert.deepEqual(JSON.parse(result), {
    afterChecks:{count:2,schema:'BETA',table:'V1'},
    remaining:['BETA.V1'],active:'BETA.V1',
  });
});

test('switching Source profile clears schema, object, and catalog state from the previous database', () => {
  const result = vm.runInNewContext(`${uiSource}
    let liveSourceDiscovery = {schema:'DB_B',table:'OLD'};
    let liveSourceDraft = {target:'old'};
    realSourceUI.profileId = 'warehouse-bsm';
    realSourceUI.schema = 'BIDPITDBA';
    realSourceUI.table = 'DP_WIP_DATA';
    realSourceUI.objectType = 'TABLE';
    realSourceUI.catalogObjects = [{schema:'BIDPITDBA',name:'DP_WIP_DATA',kind:'TABLE'}];
    realSourceUI.catalogComplete = true;
    realSourceUI.catalogSelectedObjects = [{schema:'BIDPITDBA',name:'DP_WIP_DATA',kind:'TABLE'}];
    realSourceActivateProfile('prep-iot');
    const fresh={profile:realSourceUI.profileId,schema:realSourceUI.schema,table:realSourceUI.table,objects:realSourceUI.catalogObjects.length,selected:realSourceUI.catalogSelectedObjects.length,complete:realSourceUI.catalogComplete};
    realSourceUI.schema='IOT_SCHEMA'; realSourceUI.table='IOT_TABLE';
    realSourceActivateProfile('warehouse-bsm');
    JSON.stringify({fresh,restored:{profile:realSourceUI.profileId,schema:realSourceUI.schema,table:realSourceUI.table,objects:realSourceUI.catalogObjects.length,selected:realSourceUI.catalogSelectedObjects.length,complete:realSourceUI.catalogComplete}});`, {});
  assert.deepEqual(JSON.parse(result), {
    fresh:{profile:'prep-iot',schema:'',table:'',objects:0,selected:0,complete:false},
    restored:{profile:'warehouse-bsm',schema:'BIDPITDBA',table:'DP_WIP_DATA',objects:1,selected:1,complete:true},
  });
});

test('checked-object Discovery is sequential, bounded, and produces metadata snapshots for Dataset selection', async () => {
  const result = await vm.runInNewContext(`${uiSource}
    let liveSourceDiscovery = null;
    let liveSourceDraft = null;
    let active = 0, maxActive = 0;
    const requested = [], snapshots = [], jobs = {};
    const status={textContent:''}, button={disabled:false}, summary={replaceChildren(){},innerHTML:''}, details={innerHTML:''};
    const checkboxes=[{disabled:false},{disabled:false}];
    const document={getElementById(id){return ({'discover-checked-object':button,'batch-discovery-status':status,'batch-discovery-results':summary,'real-source-discovery-results':details})[id]||null;},querySelectorAll(){return checkboxes;}};
    const window={cacheRealSourceSnapshot(s){snapshots.push(s.schema+'.'+s.table);}};
    function invalidateDatasetRequest() {}
    function liveCandidate(name){return name.toLowerCase();}
    const setTimeout=(fn)=>fn();
    realSourceUI.profileId='source-iot';
    realSourceUI.profiles={'source-iot':{connected:true}};
    realSourceUI.catalogSelectedObjects=[{schema:'S1',name:'T1',kind:'TABLE'},{schema:'S2',name:'T2',kind:'TABLE'}];
    realApi=async (path,data)=>{
      if(path==='discover'){requested.push(data.schema+'.'+data.table);jobs[data.table]=data;active++;maxActive=Math.max(maxActive,active);active--;return {job_id:data.table};}
      const table=path.split('/')[1];return {action:'discover',state:'succeeded',ended_at:'now',result:{object:[[table,1,'TABLE']],columns:[['EVENT_ID',1,'NUMBER','N']],keys:[['PK_'+table,'P','EVENT_ID',1,null,null]],foreign_keys:[]}};
    };
    (async()=>{await realSourceDiscoverChecked();const all=details.innerHTML;realSourceSetMetadataFilter({checked:true,value:'S1'},'schema');const filtered=details.innerHTML;realSourceClearMetadataFilter('schema');return JSON.stringify({requested,snapshots,maxActive,batch:realSourceUI.batchResults.map(r=>r.ok),metadata:realSourceUI.batchResults.map(r=>r.metadata?.keys?.[0]?.[0]),count:realSourceUI.batchResults.length,notice:status.textContent,checkedDisabled:checkboxes.some(c=>c.disabled),all,filtered,restored:details.innerHTML});})();`, {setTimeout:fn=>fn()});
  const observed=JSON.parse(result);
  assert.match(observed.all,/PK_T1[\s\S]*PK_T2/);
  assert.match(observed.filtered,/PK_T1/);
  assert.doesNotMatch(observed.filtered,/PK_T2/);
  assert.match(observed.restored,/PK_T1[\s\S]*PK_T2/);
  for(const key of ['all','filtered','restored'])delete observed[key];
  assert.deepEqual(observed, {
    requested:['S1.T1','S2.T2'],snapshots:['S1.T1','S2.T2'],maxActive:1,batch:[true,true],metadata:['PK_T1','PK_T2'],count:2,
    notice:'Metadata discovery finished: 2 of 2 objects succeeded in this run. No rows read.',checkedDisabled:false,
  });
});

test('checked-object Discovery rejects over-budget selection before calling Source', async () => {
  const result = await vm.runInNewContext(`${uiSource}
    let message='';
    function notify(value){message=value;}
    realSourceUI.profileId='source-iot';
    realSourceUI.profiles={'source-iot':{connected:true}};
    realSourceUI.catalogSelectedObjects=Array.from({length:21},(_,i)=>({schema:'S',name:'T'+i,kind:'TABLE'}));
    realApi=async()=>{throw new Error('Source must not be called');};
    (async()=>{await realSourceDiscoverChecked();return JSON.stringify({message,count:realSourceUI.batchResults.length});})();`, {});
  assert.deepEqual(JSON.parse(result), {
    message:'For a bounded run, select no more than 20 objects at a time.',count:0,
  });
});

test('Load all schema metadata continues from one keyset page to the next before enabling filters', async () => {
  const result = await vm.runInNewContext(`${uiSource}
    function render() {}
    realSourceUI.profileId = 'source-1';
    realSourceUI.profiles = {'source-1': {connected:true}};
    const cursors = [];
    realSourceRun = async (action, data) => {
      cursors.push(data.cursor);
      const result = data.cursor === null
        ? {objects:[{schema:'ALPHA',name:'T1',kind:'TABLE'}], next_cursor:{owner:'ALPHA',name:'T1',kind:'TABLE',object_id:1}}
        : {objects:[{schema:'BETA',name:'V1',kind:'VIEW'}], next_cursor:null};
      realSourceUI.catalogObjects.push(...result.objects);
      realSourceUI.catalogNextCursor = result.next_cursor;
      realSourceUI.catalogPageCount++;
      realSourceUI.catalogSchemaOptions = [...new Set(realSourceUI.catalogObjects.map(o=>o.schema))].sort();
      realSourceUI.catalogComplete = !result.next_cursor;
      return result;
    };
    (async()=>{await realSourceLoadAllCatalog(); return JSON.stringify({
      cursors, count:realSourceUI.catalogObjects.length,
      schemas:realSourceUI.catalogSchemaOptions, complete:realSourceUI.catalogComplete
    });})();`, {});
  assert.deepEqual(JSON.parse(result), {
    cursors: [null, {owner:'ALPHA',name:'T1',kind:'TABLE',object_id:1}],
    count: 2, schemas: ['ALPHA','BETA'], complete: true,
  });
});
