/* Deterministic, metadata-only candidate ranking. Not AI and not calibrated probability. */
const DATASET_DICTIONARY_VERSION = 'starter-template-1';
const DATASET_ALIASES = [
  { field: 'Lot number', aliases: ['lot', 'lot no', 'lot no.', 'lot number', 'lot id', 'lot identifier', 'lot_no', 'lot_number', 'lot_id', 'batch no', 'batch number', 'batch id', 'batch_no', 'batch_number', 'batch_id'] },
  { field: 'Input quantity', aliases: ['input qty', 'input quantity', 'input wafer quantity', 'input_qty', 'input_quantity'] },
  { field: 'Output quantity', aliases: ['output qty', 'output quantity', 'output wafer quantity', 'output_qty', 'output_quantity'] },
  { field: 'Package code', aliases: ['package', 'package code', 'pkg code', 'package_code', 'pkg_code'] },
  { field: 'Customer code', aliases: ['customer', 'customer code', 'cust code', 'customer_code', 'cust_code'] },
  { field: 'Product code', aliases: ['product code', 'product_code', 'product'] },
  { field: 'Production code', aliases: ['production code', 'production_code', 'prod code', 'prod_code'] },
  { field: 'Production area', aliases: ['production area', 'area', 'production_area', 'prod_area'] },
  { field: 'Equipment', aliases: ['equipment', 'machine', 'machine code', 'equipment code', 'equipment_id', 'machine_code'] },
  { field: 'Process step', aliases: ['process', 'process step', 'operation', 'operation code', 'process_code', 'operation_code'] },
  { field: 'Defect quantity', aliases: ['defect qty', 'defect quantity', 'reject qty', 'reject quantity', 'defect_qty', 'reject_qty'] },
];
const datasetNormalize = value => String(value ?? '').normalize('NFKD').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim().replace(/\s+/g, ' ');
const datasetTokens = value => new Set(datasetNormalize(value).split(' ').filter(Boolean));
function datasetAliasMatch(requested, column) {
  const requestedKey = datasetNormalize(requested), columnKey = datasetNormalize(column);
  for (const entry of DATASET_ALIASES) {
    const labels = [entry.field, ...entry.aliases].map(datasetNormalize);
    if (labels.includes(requestedKey) && labels.includes(columnKey)) return entry;
  }
  return null;
}
function rankDatasetField(requestedField, catalogs) {
  const requestKey = datasetNormalize(requestedField), requestedTokens = datasetTokens(requestedField);
  const candidates = [];
  for (const catalog of catalogs) for (const column of catalog.columns || []) {
    const columnName = Array.isArray(column) ? column[0] : column.name;
    const sourceType = Array.isArray(column) ? column[2] : column.type;
    const columnKey = datasetNormalize(columnName), columnTokens = datasetTokens(columnName);
    let score = 0, reason = '', ambiguity = '';
    if (requestKey && requestKey === columnKey) { score = 100; reason = 'Exact normalized name match.'; }
    else {
      const alias = datasetAliasMatch(requestedField, columnName);
      if (alias) {
        score = 82; reason = `Curated starter-dictionary alias for “${alias.field}”.`;
        if (columnKey === 'batch no' || columnKey === 'batch number' || columnKey === 'batch id') {
          score = 58; ambiguity = 'BATCH_NO may mean a manufacturing lot, production batch, or job; a name alias is insufficient to assign its business meaning.';
        }
      } else {
        const overlap = [...requestedTokens].filter(token => columnTokens.has(token)).length;
        const union = new Set([...requestedTokens, ...columnTokens]).size;
        if (overlap && union) { score = Math.round(45 * overlap / union); reason = `Token overlap ${overlap}/${union}; name-only evidence.`; }
      }
    }
    if (score) candidates.push({
      id: `${catalog.sourceId || 'source'}:${catalog.schema || ''}:${catalog.table || ''}:${columnName}`,
      sourceId: catalog.sourceId || null, sourceName: catalog.sourceName || 'Selected source', schema: catalog.schema || null,
      table: catalog.table || null, column: columnName, sourceType: sourceType || 'Unknown',
      matchingScore: score, scoreUnit: 'ranking points', scoreCalibration: 'uncalibrated; not a probability or percent',
      evidence: [reason, catalog.evidence || 'Schema metadata only; no sample values used.'],
      datatypeCompatibility: 'Unknown — expected business type not specified', joinConfidence: 'Not assessed — join plan and grain not confirmed',
      ambiguity, dictionaryVersion: DATASET_DICTIONARY_VERSION,
    });
  }
  candidates.sort((a, b) => b.matchingScore - a.matchingScore || a.sourceName.localeCompare(b.sourceName) || String(a.table).localeCompare(String(b.table)) || String(a.column).localeCompare(String(b.column)));
  const tiedTop = candidates.length > 1 && candidates[0].matchingScore === candidates[1].matchingScore;
  const topIsAmbiguous = !!candidates[0]?.ambiguity || tiedTop;
  return { requestedField, status: candidates.length ? (topIsAmbiguous ? 'ambiguous' : 'pending') : 'no_suitable_match', candidates,
    issue: !candidates.length ? 'No metadata candidate matched this requested business field.' : topIsAmbiguous ? (candidates[0].ambiguity || 'Top candidates have the same ranking score; user review is required.') : '' };
}
function buildDatasetReview(request, catalogs) {
  return (request.businessFields || []).map(field => rankDatasetField(field, catalogs));
}
function applyDatasetReview(review, candidateId, decision, expectedRevision, requestRevision) {
  if (expectedRevision !== requestRevision) throw new Error('Dataset request revision changed; refresh candidates before reviewing.');
  if (!['approved', 'overridden', 'rejected', 'no_suitable_match'].includes(decision)) throw new Error('Unsupported review decision.');
  const candidate = review.candidates.find(item => item.id === candidateId);
  if (decision !== 'no_suitable_match' && !candidate) throw new Error('Selected candidate is not part of this request.');
  if (decision === 'approved' && (review.status === 'ambiguous' || candidate?.ambiguity)) throw new Error('Ambiguous candidate cannot be directly approved; record an explicit override with rationale.');
  if (decision === 'overridden' && candidate && candidate.id === review.candidates[0]?.id && !candidate.ambiguity) throw new Error('Select an alternative candidate or resolve an identified ambiguity to record an override.');
  return { requestedField: review.requestedField, decision, selectedCandidate: candidate || null, reasonRequired: decision === 'overridden' || decision === 'rejected' || decision === 'no_suitable_match', requestRevision };
}
function datasetDefinitionReadiness(request, decisions) {
  const blockers = [];
  if (!request?.id || !request?.businessFields?.length) blockers.push('Create a Dataset Request with at least one business field.');
  for (const field of request?.businessFields || []) {
    const decision = decisions?.[field];
    if (!decision || !['approved', 'overridden'].includes(decision.decision)) blockers.push(`${field}: candidate review is incomplete.`);
    else if (decision.reasonRequired && !String(decision.reason || '').trim()) blockers.push(`${field}: reviewer rationale is required.`);
  }
  if (!request?.grain || request.grain === 'unknown') blockers.push('Confirm Dataset grain; join and measure behavior depends on it.');
  if ((request?.sources || []).length > 1 && !request?.relationshipReview?.approved) blockers.push('Review and approve cross-source relationships before approving this multi-source Dataset Definition.');
  return { ready: blockers.length === 0, blockers };
}
if (typeof module !== 'undefined') module.exports = { DATASET_DICTIONARY_VERSION, DATASET_ALIASES, datasetNormalize, rankDatasetField, buildDatasetReview, applyDatasetReview, datasetDefinitionReadiness };
