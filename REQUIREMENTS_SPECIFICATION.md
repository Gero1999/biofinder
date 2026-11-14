# Biofinder requirements specification

Status: proposed implementation requirements, version 0.1.

This document specifies a dataset-discovery and technical-support agent for
biology and life sciences. It builds on the six cases in
[Technical support scenarios](TECHNICAL_SUPPORT_SCENARIOS.md). It describes
required behavior and proposed acceptance targets, not existing functionality
or measured performance.

## 1. Product goal and scope

Biofinder helps a researcher identify suitable datasets, investigate metadata or
compatibility problems, and produce a cited recommendation. It combines public
web discovery with detailed document lookup and reproducible metadata checks.

The first release must support all six scenarios using curated public or
synthetic documents. It must distinguish a dataset that meets a requirement,
one that fails it, and one whose suitability remains unresolved.

In scope:

- Research requirements, dataset discovery, study-document inspection, metadata
  reconciliation, small-table validation, and cited comparisons.
- Public repositories, associated publications, and user-authorized documents.
- Proposed troubleshooting steps and minimal reproduction plans.

Outside the first release:

- Bulk sequencing downloads, full biological analysis pipelines, model training,
  clinical diagnosis, or treatment recommendations.
- Processing real identifiable patient records, bypassing controlled access,
  submitting access applications, or contacting data providers automatically.
- Certifying legal permission, scientific validity, or regulatory compliance.

## 2. Core capabilities

“MUST” denotes a release requirement. “SHOULD” denotes a desirable capability
that may be deferred with a documented reason.

| ID | Capability | Required behavior |
| --- | --- | --- |
| CAP-01 | Requirements intake | MUST capture organism, biological question, assay, specimen, cohort constraints, required controls, intended use, and relevant timing. Distinguish mandatory criteria from preferences. |
| CAP-02 | Adaptive investigation | MUST plan an initial investigation, select tools according to the information gap, revise queries when evidence changes, and stop when the answer, a blocker, or a budget limit is reached. |
| CAP-03 | Dataset discovery | MUST discover candidates using web search and supported repository metadata. Recognize accession aliases and repository mirrors without assuming they are independent studies. |
| CAP-04 | Document-grounded assessment | MUST locate methods, sample tables, protocols, dictionaries, release notes, and terms relevant to each requirement. Follow a retrieved passage to its surrounding context before a material conclusion. |
| CAP-05 | Biological-unit reconciliation | MUST distinguish donor, visit, specimen, aliquot, library, assay, run, and cell. Track verified links separately from inferred or unresolved links. |
| CAP-06 | Compatibility diagnosis | MUST compare documented input format, processing, annotation, build, layout, and analysis assumptions against supplied pipeline requirements. Propose transformations rather than applying them silently. |
| CAP-07 | Temporal and endpoint assessment | MUST identify prediction-time leakage, baseline ambiguity, follow-up differences, censoring, and missing labels without inventing mappings. |
| CAP-08 | Access and reuse assessment | MUST distinguish technical availability, authorization requirements, dataset terms, publication licenses, and unresolved reuse questions. Record applicable versions and evidence. |
| CAP-09 | Evidence-backed comparison | MUST return a candidate-by-requirement matrix with meets/fails/unknown states, cited explanations, exclusions, and practical next steps. |
| CAP-10 | Contradiction handling | MUST retain conflicting sources, compare their authority and release context, and explain why a contradiction is resolved or left open. |
| CAP-11 | Bounded metadata calculations | MUST perform exact counts, duplicate checks, join-cardinality checks, missingness summaries, and simple timelines through deterministic table processing. Retrieved snippets alone are insufficient for whole-table counts. |
| CAP-12 | Reusable case context | MUST retain approved requirements, sources, exclusions, and investigation state within a case. Changes to requirements must invalidate affected conclusions and calculations. |

## 3. Tool integration

The names below describe logical adapters. They do not assert that any particular
browser or `file_search` implementation is already installed. Implementation
must inspect available tool schemas and map their actual operations to these
contracts. Missing capabilities must be reported rather than simulated.

### 3.1 Browser: discover and retrieve external evidence

**TOOL-01:** The browser adapter MUST support search, opening a result or URL,
following links/redirects, and retrieving permitted small documents or metadata.
It SHOULD extract readable HTML and provide stable source references. It must
handle pages requiring a real browser where supported, and identify inaccessible
content when rendering, authentication, or policy blocks it.

Each result must retain title, original URL, final URL, publisher/repository,
retrieval time, and relevant publication/release date when available. Search
snippets are discovery leads; material claims require the underlying source.

Browser requests must not include private document contents, credentials, or
subject-level identifiers in search queries. Public accession IDs and approved,
non-sensitive research terms may be used. The agent must not submit forms,
contact authors, or initiate an application without explicit instruction.

### 3.2 `file_search`: inspect authorized document collections

**TOOL-02:** The document adapter MUST support semantic and exact-term retrieval,
filtering by case/source/version, and fetching surrounding passages. It must
cover Markdown/text, searchable PDFs, and documented table/config/log formats.
It must return document ID, source/version, page/section or row range, and the
supporting text. The full source must remain retrievable for verification.

A no-hit search means evidence was not found in the indexed material. It does
not prove that a study lacks a control, variable, or permission. The agent must
check indexing coverage and access status before concluding that material is
absent. Retrieval relevance scores must not be represented as scientific
confidence or eligibility probabilities.

Document access must be scoped to authorized cases/workspaces. Lookup must not
retrieve another user's documents. Versions must be separately identifiable;
replacing a file must not silently rewrite historical citations.

### 3.3 Ingestion: the bridge between browser and lookup

**TOOL-03:** Public documents fetched by the browser MUST pass through an explicit
extract-and-index step before they are searchable with `file_search`:

1. Check type, size, permission/access state, and source provenance.
2. Extract text and table structure; use OCR when available and label its output.
3. Preserve page/table/row locations, original artifact, checksum, and release.
4. Register the document under the current case and wait for indexing readiness.
5. Return its document ID and parse/index status.

The first release must support text/Markdown, HTML, searchable PDF, CSV/TSV,
JSON, and text-based YAML/config/log files. Scanned PDFs must either receive
OCR with an explicit quality flag or be reported unsupported. Encrypted or
unreadable material must not be treated as successfully indexed. Exact matching
and calculations must preserve accession strings, leading zeros, missing-value
markers, units, and date formats.

Proposed default ingestion limits are 25 MiB per file, 200 PDF pages, and 100,000
rows per table. These are configurable product limits, not evidence that every
file below a limit is parseable. Above-limit files require narrowing or an
explicitly approved larger workflow. FASTQ/BAM and archives are not automatically
expanded or indexed.

### 3.4 Structured repository metadata and table processing

**TOOL-04:** Repository connectors SHOULD retrieve authoritative structured
records from relevant sources, initially GEO and ENA/SRA-linked metadata. Source
coverage must be advertised accurately. Public APIs may be accessed through the
browser adapter or dedicated read-only connectors with equivalent provenance.
Later sources may include trial registries and multi-omics repositories.

Identifiers must preserve their hierarchy and release context. API responses
must be stored as evidence, not converted into unsupported free-text claims.
Repository aliases must support deduplication rather than inflate candidate counts.

**TOOL-05:** A deterministic table processor MUST provide read-only filtering,
counts, duplicate detection, joins with cardinality diagnostics, and temporal
checks over authorized small tables. This can be application code rather than a
model-facing tool. It must record input hashes, selected columns, filters,
normalization rules, and output counts. Arbitrary model-generated code execution
is not required for the first release.

### 3.5 Orchestration, failures, and budgets

**TOOL-06:** Every tool call must have a recorded purpose and a bounded timeout.
Independent retrievals may run concurrently; ingestion and lookup remain ordered
by readiness. The agent must not repeat the same unsuccessful query indefinitely.

Default limits: 30 external requests per investigation, at most three concurrent
external requests, and an eight-minute active investigation budget after required
inputs are ready. Return useful partial findings and an explicit reason when a
limit is reached. A user may request continuation with a stated additional budget.

Retry transient timeouts/5xx failures at most twice, with backoff. Honor
`Retry-After` within the remaining budget. Do not retry unchanged access denials,
invalid credentials, or permanent parse errors. Report the affected source and
operation, then continue independent work where useful.

## 4. Evidence and result contracts

**EVID-01:** Each material claim MUST cite a source URL or document ID, its
version/release where known, retrieval date, and a pinpoint location. A computed
claim must additionally reference its calculation and inputs. Missing dates or
versions must be labeled unknown rather than inferred.

**EVID-02:** Evidence authority is contextual: repository manifests establish file
identity; study methods establish design; dataset-specific terms establish stated
reuse conditions. A newer document is not automatically authoritative for an
older dataset release. Preserve conflicts across these sources.

**EVID-03:** The structured result MUST include:

- Case ID, requirements/version, investigation status, and source cutoff.
- Candidate accessions/releases and the biological units they represent.
- Requirement matrix with meets/fails/unknown, evidence references, and reasons.
- Relevant count, crosswalk, timeline, or compatibility artifacts.
- Contradictions, exclusions, missing inputs, access blockers, and next steps.

Allowed investigation statuses are `needs_input`, `running`, `completed`,
`partial`, `blocked`, and `cancelled`. A completed investigation may conclude
that no dataset fits; this does not mean a successful match was found.

**EVID-04:** Recommendations MUST differentiate observed facts, calculations,
inferences, and hypotheses. A missing artifact, unresolved identifier mapping,
or inaccessible agreement must remain visible in the final answer.

## 5. User interaction patterns

| ID | Pattern | Behavior |
| --- | --- | --- |
| UX-01 | Guided intake | Accept a natural-language question plus optional files/accessions. Ask focused questions only when missing information prevents useful work; begin independent discovery otherwise. |
| UX-02 | Investigation preview | State the interpreted goal, mandatory criteria, intended sources, and approximate budget. Routine public read-only research proceeds without repeated confirmation. |
| UX-03 | Visible progress | Acknowledge the request, show the current stage, and report meaningful changes: discovered candidates, a contradiction, indexing, or an access blocker. Do not expose private reasoning traces. |
| UX-04 | Clarification at a decision point | Ask a concrete question such as “Do technical replicates count toward your minimum?” Explain the consequence; never silently relax a mandatory criterion. |
| UX-05 | Evidence inspection | Let users open the source passage or calculation behind a recommendation and see which release it supports. |
| UX-06 | Result and refinement | Lead with the recommendation and limitations, then a comparison table. Support follow-ups such as “exclude this cohort,” “require paired donors,” or “find alternatives.” Recompute affected results. |
| UX-07 | Pause, cancel, resume | Stop new calls on cancellation, preserve authorized checkpoints, and resume after requirements or access change. Report already-running calls that cannot be interrupted. |
| UX-08 | Export | Offer Markdown plus CSV/JSON for comparison tables and provenance. Redact secrets and preserve unresolved states in exports. |

The proposed primary interface is conversational, with optional evidence and
comparison panels. A command-line client may consume the same case/result
contracts. No particular UI framework is required by this specification.

## 6. Performance and quality targets

These are **proposed acceptance targets**, not benchmarks already achieved.
Instrument model, network, parsing, indexing, search, and calculation time
separately so the bottleneck can be identified.

### Reference measurement conditions

Measure on a documented reference deployment with at least four vCPUs and 8 GiB
RAM, up to three concurrent investigations, and a case collection of 100 indexed
documents/10,000 text chunks plus tables within the ingestion limits. Record
provider/model versions, network conditions, cache state, and fixture versions.
Use at least 30 runs per workload to report median and p95 latency; report warm
and cold retrieval separately. Live-provider and replayed-fixture results must
not be combined into one latency claim.

| ID | Measure | Initial target |
| --- | --- | --- |
| PERF-01 | Request acknowledgement | p95 within 2 seconds, independently of whether research is complete. |
| PERF-02 | Progress heartbeat | A stage/status update at least every 30 seconds while an investigation is active. |
| PERF-03 | Indexed lookup | p95 within 3 seconds for retrieval from a ready collection; excludes model synthesis. |
| PERF-04 | Small-table checks | p95 within 5 seconds for one supported operation on a 100,000-row fixture, with its actual schema documented. |
| PERF-05 | First useful candidates | p95 within 120 seconds for a discovery request with complete inputs and healthy upstream sources. Candidate suitability may still be unresolved. |
| PERF-06 | Full scenario response | p95 within 6 minutes on the curated end-to-end fixtures after required documents are indexed; stop or checkpoint by the eight-minute run budget. Report live investigations separately. |
| PERF-07 | Document readiness | p95 within 60 seconds for a supported searchable PDF of up to 50 pages/10 MiB under reference conditions. OCR, unsupported files, and larger documents require separate measurements. |
| QUAL-01 | Evidence coverage | 100% of material eligibility, count, processing, timing, and reuse claims have source/calculation references in the scenario fixtures. |
| QUAL-02 | Citation support | At least 95% of sampled material claims are actually supported by their cited passage or record, assessed by a human reviewer; zero fabricated sources/accessions. |
| QUAL-03 | Reconciliation accuracy | Exact expected donor counts, deterministic joins, and endpoint classifications on the curated fixtures; unresolved cases must match their annotated unknown state. |
| QUAL-04 | Retrieval coverage | At least 90% recall of the annotated decisive passages across the six fixture sets within the configured retrieval budget. |
| QUAL-05 | Permission/visibility | Zero cross-case document leaks, unauthorized submissions, access-control bypasses, or private-content search-query disclosures in the release test suite. |

Report denominators and failures, including parse/OCR failures and blocked access.
Do not remove difficult cases merely to meet targets. A timeout can correctly
produce a partial result, but it does not count as meeting the full-response
latency or successful scenario-completion target.

## 7. Privacy, provenance, and operational requirements

**OPS-01:** The prototype must use public or synthetic/de-identified evaluation
material approved for the case. It must reject or route identifiable clinical
records outside the prototype workflow; it must not claim HIPAA/GDPR compliance.

**OPS-02:** Retrieved web pages and documents are untrusted evidence. Embedded
instructions must not change tool permissions, trigger external actions, reveal
other documents, or override the user's requirements.

**OPS-03:** Store tool names, sanitized arguments, timing, source IDs, provenance,
errors, budgets, and calculation versions for reproducibility. Do not put
credentials, signed URLs, or whole private documents in routine logs. Credential
bindings belong in environment/provider settings, not conversation text.

**OPS-04:** Make document retention and deletion explicit per workspace. Deleting
a document must remove its searchable index entries and derived cached excerpts;
retained reports must mark citations unavailable according to the retention policy.
Authorized public-source caching must preserve retrieval dates and freshness.

**OPS-05:** Authentication and provider capabilities must be checked before use.
If a browser, file index, parser, or repository endpoint is unavailable, identify
that capability gap and offer an appropriate next action. No result may describe
an unexecuted lookup, calculation, download, or analysis as successful.

## 8. Scenario traceability and release acceptance

Tool sequence notation:

- **F:** `file_search` over authorized, ready documents.
- **B:** browser search/open/follow to discover external sources.
- **I:** permitted fetch, extraction, provenance registration, and indexing.
- **M:** authoritative structured metadata retrieval via connector/API.
- **T:** deterministic whole-table checks, separate from text retrieval.

The initial F step uses customer fixtures already ingested at intake. Each I
step must finish before F searches the newly fetched material. Sequences are
initial plans; contradictions can require a bounded B → I → F loop.

| Scenario | Initial tool order | Key requirements | Required output |
| --- | --- | --- | --- |
| 1. Donor inflation and atlas reuse | F → B → M → I → F → T | CAP-03/04/05/09, EVID-01/04 | Donor/specimen/run crosswalk, deduplicated counts, overlap flags, independent alternatives. |
| 2. RNA-seq input incompatibility | F → B → M → I → F → T | CAP-04/06/10, TOOL-05 | File/pipeline compatibility matrix, supported causes, bounded reproduction plan. |
| 3. Longitudinal endpoint mismatch | F → B → M → I → F → T | CAP-04/07/09/10 | Event timeline, endpoint mapping, leakage flags, compatible validation candidates. |
| 4. Access and reuse uncertainty | F → B → I → F → B → I → F | CAP-08/09/10, OPS-01/03 | Access diagnosis, versioned terms evidence, unresolved permission questions, alternatives. |
| 5. Multi-omics join failure | F → B → M → I → F → T | CAP-05/09/11, EVID-01 | Versioned crosswalk, join-cardinality diagnostics, verified paired-tumor count. |
| 6. Microbiome confounding | F → B → M → I → F → T | CAP-04/06/09/10/11 | Control inventory, batch/design assessment, unresolved confounding and alternative cohorts. |

Before declaring the first release ready:

1. Create the proposed customer fixtures and external-source snapshots for all
   six scenarios, with annotated expected facts, unknowns, calculations, and
   decisive evidence. These fixtures do not yet exist in the repository.
2. Execute each case with traces showing substantive use of both browser and
   `file_search`. A no-op tool call added to satisfy a checklist is insufficient.
3. Verify scenario-specific acceptance criteria from the scenario document,
   exact table results, citation correctness, and the quality targets above.
4. Exercise contradictions, empty retrievals, unsupported/scanned documents,
   missing supplements, API failures, restricted access, and budget exhaustion.
5. Test cancel/resume, requirement changes, document-version changes, deletion,
   tool unavailability, and malicious instructions embedded in source material.
6. Publish measured performance against the stated conditions, including misses
   and blocked/unrun checks. No implementation or readiness claim follows from
   this specification alone.
