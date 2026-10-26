const test=require('node:test');const assert=require('node:assert/strict');
const {rankDatasetField,buildDatasetReview,applyDatasetReview,datasetDefinitionReadiness}=require('../dataset-workflow.js');
const catalog={sourceId:'oracle-source',sourceName:'Data Prep IOT',schema:'BIDPITDBA',table:'DP_WIP_DATA',evidence:'Oracle metadata discovery snapshot only; no sample values used',columns:[['LOT_NO',1,'VARCHAR2','N'],['BATCH_NO',2,'VARCHAR2','Y'],['INPUT_QTY',3,'NUMBER','Y'],['LOT_NUMBER',4,'VARCHAR2','Y']]};
test('candidate ranking uses deterministic exact/alias evidence and does not call it probability',()=>{
 const result=rankDatasetField('Lot number',[catalog]);assert.equal(result.candidates[0].column,'LOT_NUMBER');assert.equal(result.candidates[0].matchingScore,100);assert.equal(result.candidates.find(c=>c.column==='LOT_NO').matchingScore,82);assert.equal(result.candidates[0].scoreCalibration,'uncalibrated; not a probability or percent');assert.match(result.candidates[0].evidence.join(' '),/metadata discovery snapshot/);assert.equal(result.candidates[0].datatypeCompatibility,'Unknown — expected business type not specified');assert.equal(result.candidates[0].joinConfidence,'Not assessed — join plan and grain not confirmed');
});
test('multi-source Dataset request ranks candidates across each selected Source snapshot',()=>{
 const second={...catalog,sourceId:'oracle-qc',sourceName:'QC Oracle',schema:'QCSCHEMA',table:'LOT_INSPECTION',columns:[['LOT_NUMBER',1,'VARCHAR2','N'],['DEFECT_QTY',2,'NUMBER','Y']]};
 const result=rankDatasetField('Defect quantity',[catalog,second]);assert.equal(result.candidates.length,1);assert.equal(result.candidates[0].sourceName,'QC Oracle');assert.equal(result.candidates[0].schema,'QCSCHEMA');assert.equal(result.candidates[0].matchingScore,82);assert.equal(result.candidates[0].scoreUnit,'ranking points');assert.equal(result.candidates[0].scoreCalibration,'uncalibrated; not a probability or percent');
});
test('BATCH_NO is ranked as explicitly ambiguous and cannot be silently approved',()=>{
 const result=rankDatasetField('Lot number',[catalog]);const batch=result.candidates.find(c=>c.column==='BATCH_NO');assert.equal(batch.matchingScore,58);assert.match(batch.ambiguity,/manufacturing lot, production batch, or job/);assert.throws(()=>applyDatasetReview(result,batch.id,'approved',1,1),/Ambiguous candidate/);const decision=applyDatasetReview(result,batch.id,'overridden',1,1);assert.equal(decision.reasonRequired,true);
});
test('no candidate and missing requested fields remain explicit blockers',()=>{
 const result=rankDatasetField('Quantum flux label',[catalog]);assert.equal(result.status,'no_suitable_match');assert.match(result.issue,/No metadata candidate/);assert.deepEqual(buildDatasetReview({businessFields:['Quantum flux label']},[catalog]).map(x=>x.status),['no_suitable_match']);
});
test('request revision conflict blocks stale candidate decisions',()=>{
 const result=rankDatasetField('Input quantity',[catalog]);assert.throws(()=>applyDatasetReview(result,result.candidates[0].id,'approved',1,2),/revision changed/);
});
test('definition needs every required field reviewed, a confirmed grain, and multi-source relationship approval',()=>{
 const request={id:'d1',businessFields:['Input quantity','Lot number'],grain:'unknown'};const incomplete=datasetDefinitionReadiness(request,{});assert.equal(incomplete.ready,false);assert(incomplete.blockers.some(x=>x.includes('grain')));const ready=datasetDefinitionReadiness({...request,grain:'lot'},{'Input quantity':{decision:'approved'},'Lot number':{decision:'overridden',reason:'Confirmed with data owner'}});assert.equal(ready.ready,true);
 const multi={...request,grain:'lot',sources:['mes','qc']};const reviewed={'Input quantity':{decision:'approved'},'Lot number':{decision:'approved'}};const blocked=datasetDefinitionReadiness(multi,reviewed);assert.equal(blocked.ready,false);assert(blocked.blockers.some(x=>x.includes('relationships')));assert.equal(datasetDefinitionReadiness({...multi,relationshipReview:{approved:true}},reviewed).ready,true);
});
