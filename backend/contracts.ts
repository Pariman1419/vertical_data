// Design contracts only; these interfaces are not implemented HTTP endpoints or persisted records.
export type Id = string;
export type Revision = number;
// Engine-neutral product contract. A listed engine is not evidence that an adapter is installed.
export type DatabaseEngine = 'oracle'|'sqlserver'|'postgresql'|'mysql'|'mariadb';
export type ConnectorCapability = 'test'|'discover'|'profile'|'extract'|'write';
export interface ConnectorDescriptor { engine:DatabaseEngine; adapterVersion:string; capabilities:ConnectorCapability[]; status:'available'|'planned'|'disabled'; }
export interface DiscoveryScope { sourceId:Id; visibility:'all_granted_catalog'|'explicit_allowlist'; schemas?:string[]; excludedSchemas?:string[]; excludedObjects?:string[]; includeViews:boolean; maxSchemas:number; maxObjects:number; timeoutSeconds:number; }
export interface DiscoveredObject { schema:string; name:string; kind:'table'|'view'|'materialized_view'|'other'; columns:unknown[]; primaryKeys:unknown[]; foreignKeys:unknown[]; sourceIdentity:Id; configRevision:Revision; snapshotId:Id; }
export interface MetadataAiPolicy { policyId:string; runtime:'local'|'private_endpoint'|'external'; allowedFields:string[]; sampleValuesAllowed:false; credentialsAllowed:false; retentionDays:number; }
export type DatasetGrain = 'lot'|'lot_operation'|'production_event'|'user_defined'|'unknown';
export type FieldReviewDecision = 'pending'|'approved'|'overridden'|'rejected'|'no_suitable_match'|'stale';
export interface DatasetFieldRequest { requestedName:string; businessDefinition?:string; expectedLogicalType?:string; required:boolean; }
export interface DatasetSourceRef { sourceId:Id; configRevision:Revision; schema:string; table:string; discoverySnapshotId?:Id; metadataFingerprint?:string; }
export interface DatasetTimeWindow { from?:string; to?:string; timezone?:string; }
export interface DatasetRequest {
 id:Id; revision:Revision; name:string; purpose:string; businessFields:DatasetFieldRequest[];
 sources:DatasetSourceRef[]; timeWindow?:DatasetTimeWindow; filterRequest?:string;
 grain:DatasetGrain; grainRationale?:string; targetId?:Id; targetGeneration?:Id;
 createdAt:string; createdBy?:Id; status:'draft'|'candidates_ready'|'reviewing'|'stale'|'definition_approved';
}
export interface CandidateEvidence { kind:'name_exact'|'dictionary_alias'|'token_overlap'|'datatype'|'constraint'|'profile'; detail:string; sourceSnapshotId?:Id; sampleRowsUsed:false; }
export interface DatasetCandidate {
 id:Id; requestedField:string; sourceId:Id; schema:string; table:string; column:string; sourceType:string;
 matchingScore:number; scoreUnit:'ranking_points'; calibrated:false; scoreExplanation:string;
 semanticMatch:'name_exact'|'dictionary_alias'|'token_overlap'|'none'; datatypeCompatibility:'compatible'|'incompatible'|'unknown';
 joinConfidence:'not_assessed'|'low'|'medium'|'high'; ambiguity:string[]; evidence:CandidateEvidence[];
 dictionaryVersion:string; modelVersion?:string;
}
export interface FieldReview { requestedField:string; decision:FieldReviewDecision; selectedCandidateId?:Id; reviewerId?:Id; rationale?:string; expectedRequestRevision:Revision; createdAt:string; }
export interface DatasetDefinition {
 id:Id; requestId:Id; requestRevision:Revision; definitionRevision:Revision; name:string; purpose:string;
 sources:DatasetSourceRef[]; businessFields:DatasetFieldRequest[]; fieldReviews:FieldReview[];
 grain:DatasetGrain; grainRationale?:string; joinPlan:unknown[]; filters:unknown[]; qualityRules:unknown[];
 targetId?:Id; targetGeneration?:Id; dictionaryVersion:string; candidateProviderVersion:string;
 approval?:{actorId:Id;at:string;revision:Revision;}; status:'draft'|'reviewed'|'approved'|'stale';
}
export interface CandidateSuggestionProvider {
 readonly providerId:string; readonly providerVersion:string;
 suggest(request:DatasetRequest,metadata:unknown[]):Promise<DatasetCandidate[]>;
}
export interface RuleBasedCandidateProvider extends CandidateSuggestionProvider { readonly providerId:'metadata-rule-baseline'; }
// Required product capability, but no provider is enabled until its metadata-egress policy is approved.
// Never pass credentials or row samples through this interface.
export interface AiCandidateProvider extends CandidateSuggestionProvider { readonly providerId:string; readonly providerVersion:string; readonly dataPolicy:MetadataAiPolicy; }
export type RunState = 'queued'|'running'|'cancel_requested'|'cancelled'|'failed'|'succeeded'|'succeeded_with_warnings';
export interface ConnectionConfig { id:Id; role:'Source'|'Target'; revision:number; engine:DatabaseEngine; endpoint:string; database:string; auth:'sql'|'windows'|'integrated'|'external'; secretRef?:Id; rememberUsername:boolean; }
export interface CredentialSession { scope:Id; expiresAt:string; secretRef?:Id; /* plaintext credentials never returned by API */ }
export interface RowCounts { extracted:number; inserted:number; updated:number; unchanged:number; quarantined:number; filtered:number; duplicateSuperseded:number; }
export interface RunBoundary { lower:string; upper:string; snapshotRef:Id; strategyVersion:Id; semantics:string; }
export interface RunRequest { requestId:Id; sourceIds:Id[]; targetId:Id; targetGeneration:Id; tableMappingIds:Id[]; bundleId:Id; mode:'initial'|'incremental'|'full_refresh'; expectedRevision:number; }
export interface JobReceipt { jobId:Id; state:RunState; statusUrl:string; }
export interface Connector {
 readonly descriptor:ConnectorDescriptor;
 test(config:ConnectionConfig,session:CredentialSession):Promise<{passed:boolean;runtimeIdentity:string;testedAt:string}>;
 discover(scope:DiscoveryScope):Promise<JobReceipt>;
 profile(table:Id,limits:{sampleRows:number;timeoutSeconds:number}):Promise<JobReceipt>;
 establishBoundary(table:Id,strategyVersion:Id):Promise<RunBoundary>;
 extract(table:Id,boundary:RunBoundary,cursor?:string):Promise<{rows:unknown[];nextCursor?:string}>;
}
export interface Worker { enqueue(request:RunRequest):Promise<JobReceipt>; cancel(runId:Id,expectedRevision:number):Promise<JobReceipt>; retry(runId:Id,scope:Id[],requestId:Id):Promise<JobReceipt>; }
export interface TargetWriter { stage(runId:Id,table:Id,rows:unknown[]):Promise<void>; validate(runId:Id,table:Id):Promise<RowCounts>; publishWithWatermark(runId:Id,table:Id,boundary:RunBoundary):Promise<void>; }
export interface Registry { getRun(id:Id):Promise<{state:RunState;bundleId:Id;configRevisions:Record<Id,number>;counts:RowCounts}>; approveMapping(id:Id,expectedRevision:number,actor:Id):Promise<Id>; }
