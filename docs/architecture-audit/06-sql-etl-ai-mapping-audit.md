# SQL ETL and AI mapping audit

Audit date: 2026-10-26. Static discovery; no custom SQL, inference requests or database calls executed. Current and proposed capabilities are separated below. See [00](00-executive-summary.md).

## SQL authoring: current state

**SQL ETL authoring is NOT IMPLEMENTED.** SQL appears in backend source as fixed Oracle/SQLite statements. There is no SQL editor, user-query execution route or SQL-to-Dataset pipeline. A source sample is a generated projection query, not a query authored by the user. The Dataset `filterRequest` field is explicitly a business description, not executable SQL.

Evidence: `prototype.js:datasetRequestPanel/submitDatasetRequest`; `server.py:Handler.do_POST`; `OracleReadAdapter.sample/extract_bounded`; `backend/contracts.ts`; actual API inventory in [02](02-frontend-api-inventory.md).

| Capability | Existing evidence | Assessment |
|---|---|---|
| SQL editor/parser | No editor dependency, textarea mode, parser or query document route | NOT IMPLEMENTED |
| Arbitrary SQL execution | Accepted actions do not accept SQL; all fields strictly checked | NOT IMPLEMENTED; keep this trust boundary during v2 design |
| Dialects | Fixed Oracle catalog/ROWNUM queries; SQLite DDL/upsert | Two internal dialects, no author-facing dialect contract |
| Parameter binding | Oracle values use named binds; SQLite values use placeholders; identifiers separately validated/quoted | Implemented for generated SQL only |
| Query validation | Action-specific schema/table/column checks; no arbitrary-query AST policy | Partial reusable boundary; not ready for user SQL |
| Read-only source | Fresh connection, autocommit false, SET TRANSACTION READ ONLY, SELECT-only generated reads | Implemented source-side defense; actual account grants NOT VERIFIED |
| Preview limits | Source sample <=100 rows, UI catalog example <=5; local target preview <=100 | Implemented samples, no SQL-query preview |
| SQL revision history | None in real storage/schema | NOT IMPLEMENTED |
| SQL approval/audit | No query entity, immutable revision or server approval | NOT IMPLEMENTED |
| SQL scheduling | No scheduler/secret service | NOT IMPLEMENTED |
| Query-to-Dataset publish | Only session-only createDatasetSimulation | NOT IMPLEMENTED |

## Readiness for requested modes

| Mode | Reuse | Required design before implementation |
|---|---|---|
| A. Extract SQL | Oracle session/read budget/error sanitization; future verified SPICE adapter | Dialect/version, one-statement read policy, parser validation, source object authorization, bound typed parameters, column/result schema, row/byte/time/query-cost budgets, cancel and repeatable extraction boundary |
| B. Transform SQL | TargetWriter design boundary and canonical dictionary concepts | Decide execution location: approved target/staging engine, rather than writes on source; run-scoped relations, permitted functions/statements, transaction/publication semantics, resource budgets and lineage |
| C. SQL Dataset Definition | DatasetRequest/Definition source refs and revision ideas | Persist SQL text/hash/dialect/parameters, output schema/grain, dependencies, review evidence, immutable revision and approval; query changes invalidate preview/approval |
| D. Shared Visual/SQL Pipeline Definition | Existing mapping review/readiness checks as UI behavior | One server-validated, versioned executable definition with explicit authoring mode, source/target versions, typed steps and approvals; visual and SQL authors use the same run API and publish protocol |

Do not promise arbitrary SQL can round-trip into a visual graph. Preserve opaque approved SQL steps when no faithful visual representation exists. The current `DatasetDefinition.joinPlan/filters/qualityRules` are unknown[] design fields, not an execution intermediate representation. `scripts/build.cjs` does not compile/type-check them.

Read-only query safety cannot be reduced to checking that text starts with SELECT or adding LIMIT. v2 must validate actual dialect semantics, enforce database/service permissions and bound expensive execution. Source and target SQL authorities should be different. Nothing here authorizes SQL execution or database changes.

## Actual mapping algorithm

`dataset-workflow.js:datasetNormalize/rankDatasetField` normalizes to lowercase ASCII letter/digit tokens after NFKD. For each selected metadata column it assigns:

| Evidence | Score / behavior |
|---|---|
| Exact normalized name | 100 ranking points |
| Curated alias in DATASET_ALIASES | 82 points |
| BATCH_NO/BATCH_NUMBER/BATCH_ID alias ambiguity | 58 points and explicit ambiguity message |
| Token overlap | Rounded 45 × intersection/union |
| No match | No candidate; explicit no_suitable_match |

Candidates are sorted by score then names; tied top scores are flagged ambiguous. Source/table/column/type, evidence strings and dictionaryVersion are returned. Datatype compatibility remains Unknown and join confidence Not assessed. These are **uncalibrated ranking points, not probabilities**. The declared dictionary version is starter-template-1. It is not a learned embedding model.

Name normalization discards Thai/non-ASCII letters from the matching key. Thai-only business field names may therefore yield no useful lexical match unless an explicit supported alias exists. `datasetGrainSuggestion` separately recognizes some Thai/English purpose words, but that heuristic is not multilingual semantic inference. No benchmark establishing matching accuracy was found.

## AI integration inventory

| Area | Current state | Evidence |
|---|---|---|
| LLM provider/API | NOT IMPLEMENTED | No provider import/dependency/config/route; UI says AI is not connected |
| vLLM/Ollama | NOT IMPLEMENTED; actual machine service availability Unknown | Active repository imports, requirements, realApi destinations |
| Embedding/vector search | NOT IMPLEMENTED | rankDatasetField uses name comparisons and token sets |
| Metadata retrieval | Selected cached/discovered catalogs and browser iteration | `datasetCatalogs/buildDatasetReview`; Oracle catalog routes |
| Prompt templates | None found in active runtime | No inference client or prompt artifact in application modules |
| Structured model JSON | No model output or JSON-schema validation path | `AiCandidateProvider` is a design interface only |
| Evidence/confidence | Deterministic reasons, ambiguity, explicit uncalibrated scores | rankDatasetField; compatibility/join placeholders |
| Human review | Real UI rules for approve/override/reject/no match, rationale and grain | applyDatasetReview/datasetDefinitionReadiness; browser only |
| Mapping history | No durable live history; demo revision state only | activeDatasetDecisions; P.audit; storage audit |
| Provider/model/prompt versions | Dictionary version implemented; definition stores metadata-rule-baseline provider string | No persisted model/prompt/evaluation lineage; contracts.ts modelVersion is design-only |

## Governance gaps

`applyDatasetReview` rejects revision mismatches and direct approval of ambiguous choices. `recordDatasetReview` supplies the current request revision for both arguments, so it offers local consistency rather than independent server conflict detection. `approveDatasetDefinition` checks profile revisions, but no metadata content fingerprint or immutable server snapshot is enforced at execution. Definitions remain mutable client objects; no real identity is recorded as durable approver.

`approveDatasetRelationships` records a boolean human confirmation. It does not validate executable JOIN keys, uniqueness/cardinality, null behavior or aggregation grain. The latest `renderCollectionRelationships` renders ordered load groups, not a JOIN plan, despite earlier relationship code still existing in the same file. Treat these as different concerns.

## Proposed Local LLM service boundary

**Feasible as a new isolated service; not implemented.** An authenticated control plane would submit metadata-only candidate evaluation tasks referencing an immutable source snapshot. The inference service returns schema-validated candidate objects with allowed column IDs, evidence references, ambiguity and provider/model/prompt versions. The API independently checks membership/types and records reviewable output. ETL workers consume approved definitions, not unapproved model output, and do not call the model on the data path.

Retain deterministic matching as a labelled baseline/fallback. Make inference optional for run execution after approval; approved jobs should not require GPU availability. A vector index is not automatically required; first establish catalog scale and measured retrieval quality. Keep initial metadata retrieval scoped by authorization.

| Future risk | Required boundary / acceptance |
|---|---|
| Hallucinated table/column IDs | Validate references against pinned catalog; reject missing/unauthorized IDs; no silent repair |
| Incorrect JOIN/grain | Require key/cardinality evidence and explicit owner review; test fan-out/measure behavior separately |
| Sensitive metadata/comments | Field allowlist, classification, retention and access controls even on a local model; exclude credentials and sample rows by default |
| Prompt injection in names/comments | Treat metadata as untrusted data; no tool authority or SQL execution from generated text |
| Confident but incorrect suggestions | Calibrated metrics only if measured; otherwise evidence/ranking labels and abstention |
| GPU/CPU/RAM contention | Separate inference process/service budgets, bounded concurrency/token/context limits and inference timeout/cancel |
| Model/prompt changes | Persist model artifact/version, prompt version, retrieval snapshot and evaluation lineage; invalidate only affected outputs under explicit policy |

`contracts.ts:MetadataAiPolicy/AiCandidateProvider` already expresses metadata-only policy intent. Reuse the policy idea, not as proof that enforcement exists. No external AI disclosure or existing GPU overload was established in this audit.
