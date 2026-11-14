# Biofinder support-agent optimization plan

Status: proposed design and experiments, not implemented or measured savings.

This plan applies [cache strategies](CACHE_STRATEGIES.md),
[temporary context](CONTEXT_MANAGEMENT_PLAN.md), and
[decision routing](AGENT_DECISION_TREE.md) within the
[requirements](REQUIREMENTS_SPECIFICATION.md). Correct evidence, permission,
uncertainty, and scientific-unit handling remain acceptance gates.

## 1. Optimize useful resolved gaps, not tool counts alone

Reduce unnecessary calls, bytes, parsing, and repeated model context while
preserving the answer's quality. A cheap answer based on stale terms or an
incorrect donor count is not a successful optimization. Tool choice still follows
the information gap; caching does not authorize skipping required evidence.

Use a planner record for each gap: required fact, source candidates, valid cached
evidence, expected information gain, estimated latency/cost, dependencies, and
whether resolving it could change the recommendation. Address decisive hard
criteria first, preserving unknowns until evidence resolves them.

## 2. Cost model and provisional hierarchy

Estimate total cost from actual configured providers:

```text
run cost = model input/output token charges
         + search/browser/API request charges
         + embedding and retrieval charges
         + parsing/OCR/compute charges
         + applicable storage and transfer charges
```

Track latency separately; inexpensive requests can be slow. Count bytes and
requests even when the provider bills neither directly. Revalidation requests,
retries, and cache embedding lookups are real work. Avoid double counting bundled
provider charges. Keep a dated tariff/configuration record; prices and tool
capabilities are not specified by this repository.

| Typical tier | Operation | Preferred use |
| --- | --- | --- |
| 0 | Local authorization, case-gap bookkeeping and valid exact-cache lookup | Always check scope and reusable evidence before new external work. |
| 1 | Deterministic metadata filters/calculation-cache hits, already extracted document reuse | Exact repeat questions and stable input versions. |
| 2 | Small filtered `file_search` lookup or known-ID metadata response | A targeted evidence gap with a ready index or authoritative identifier. |
| 3 | Opening a known source, conditional revalidation, batched repository lookup | Missing/current records or known source updates. |
| 4 | Broad web search, full-document extraction, embedding a new collection | Discovering sources or preparing evidence unavailable in existing material. |
| 5 | OCR, large-table processing, repeated large-context or multi-pass model synthesis | Only when the unresolved decisive gap justifies the work and budget. |

This is an initial ordering hypothesis, not a universal price ranking. A paid
retrieval call can cost more than a free metadata API call; a large join can cost
more than a search. Select using observed workload/provider costs and whether the
operation can answer the gap. Never use a cheaper source with insufficient
authority or substitute a broad search snippet for a required methods passage.

## 3. Fast paths for common support questions

### Repeated repository/download status checks

The logistics-style “carrier status” example maps here to repository health,
public dataset availability, and access-error diagnosis. Shipping integration
is not part of Biofinder's scope.

For “Is this public accession available?”:

1. Confirm the identifier and external-sharing scope. A private-file-derived ID
   still passes the context handoff gate.
2. Distinguish service health, dataset existence/release, file availability, and
   the user's authorization. A healthy homepage proves none of the other three.
3. Reuse an authorized exact status entry only within its freshness tolerance
   (proposed 30 seconds), returning the actual check timestamp and source.
4. Otherwise use the authoritative known-ID endpoint; broad web search and full
   paper retrieval are unnecessary for this narrow question.
5. Coalesce concurrent identical checks within the same appropriate scope. Store
   the result with its source and error class. A conditional request still counts
   as an upstream call even if the response body is reused.
6. If a check fails, give the observed error and next step. Do not keep polling a
   403 or equate a service outage with a dataset being unavailable permanently.

An explicit “check now,” relevant credential/settings change, release change,
or invalidation event bypasses stale reuse. Public service status may be shared
only as genuinely public source data. User authorization results remain scoped
and must be checked at use; do not cache permission grants.

For frequent monitoring, prefer documented provider events/webhooks only if
available and explicitly configured; otherwise use bounded, demand-driven checks.
Do not introduce background polling by default or invent provider webhook support.

### Other useful fast paths

- **Known accession:** resolve its record directly instead of a general discovery search.
- **Repeat document question:** reuse the exact authorized corpus/version lookup;
  fetch its evidence when needed rather than reloading an entire PDF into the model.
- **Changed cohort threshold:** reuse immutable evidence and an exact count, then
  re-evaluate the new threshold. Do not reuse the old eligibility verdict blindly.
- **Repeated failed join:** reuse unchanged input diagnostics and documented key
  definitions; rerun only calculations affected by changed keys or manifests.
- **Supplied-document-only request:** avoid browsing and explain any unresolved
  freshness limitation. Respect the user's boundary rather than optimizing it away.

## 4. Staged investigation and tool-call reduction

### Stage A: reuse and inexpensive exclusion

Load only current authorized requirements and relevant case memory. Resolve
aliases and duplicate study IDs once. Use known structured metadata to reject a
candidate only when it establishes a hard incompatibility, such as the wrong
organism. Missing metadata stays unknown; it is not a reason to silently reject.

Consult Strategy A's exact caches and Strategy C's calculation outputs before
new calls. Strategy B may supply candidate/passage leads, but all hard constraints
and evidence must be checked against the current request.

### Stage B: targeted collection

Retrieve a first wave of up to three promising candidates and their decisive
evidence, then expand if coverage remains inadequate. Batch supported accession
queries within provider limits; split failures so one bad identifier does not
hide valid results. Keep at most three external requests concurrent.

Fetch a methods section or a relevant supplement before a whole document set.
Index a source once and reuse its versioned extraction. Keep public API records
small and avoid raw sequencing downloads. For OCR, first establish that the
needed evidence is absent from a usable text/table representation.

### Stage C: bounded retrieval and reasoning

Use exact identifiers and source/version filters to narrow `file_search`; expand
the search only if coverage is inadequate. Retrieve neighboring context and
footnotes before relying on a small hit. Deduplicate passages and compact model
context using the context plan, retaining evidence pointers and qualifiers.

Use deterministic table operations for exact numerical work. A model may choose
and explain a calculation, but repeating reasoning is not a substitute for it.
Use a small structured routing step when sufficient; use more capable reasoning
for contradictory methods, endpoint definitions, or uncertain biological mappings.
Model selection must be evaluated rather than assumed safe from task names alone.

### Stage D: final evidence verification

Validate material claims and calculations once against their dependencies.
Perform additional retrieval only for a specific unsupported claim. If evidence
cannot be obtained within the budget, withdraw the claim or state the limitation.
Do not repeat a full investigation merely to generate a more polished answer.

## 5. Budget and failure controls

Preserve the parent defaults: 30 external requests, three concurrent external
requests, and eight minutes of active investigation after inputs are ready.
Every retry, source validation, search and open consumes its actual request
budget. Count provider-internal requests where observable; otherwise explicitly
report adapter calls and the upstream count as unknown, never as zero.

Add configurable per-call token and total model-spend limits, validated against
the selected model's actual context window and provider billing units. Begin with
the context plan's 8,000-token evidence allocation where supported. Do not assert
a universal dollar budget or an arbitrary model-call limit without measurement.

Reject duplicate in-flight work with bounded single-flight coordination. Cache
short-lived negative observations to avoid repeated doomed requests, while
preserving 404/no-hit/not-indexed/transient-error distinctions. Retry only
transient failures, at most twice with backoff and applicable Retry-After.

On budget exhaustion return useful partial results and a checkpoint. A user can
approve a stated additional budget; elapsed time is not approval. Do not reduce
mandatory criteria, weaken privacy, or omit uncertainty to meet a latency target.

## 6. Optimization opportunities by support scenario

| Scenario | Avoidable work | Preferred optimization | Guardrail |
| --- | --- | --- | --- |
| 1. Donor/atlas overlap | Rediscovering alias studies; repeated supplement parsing and counts. | Canonical study IDs, versioned evidence cache, exact crosswalk/count reuse. | Never assume donor identity or reuse independence from semantic similarity. |
| 2. RNA-seq mismatch | Broad searches for a known version; repeated log and matrix inspection. | Query official version docs directly; cache compatibility definitions and unchanged identifier summaries. | A proposed transformation still needs justification; normalized data cannot silently become counts. |
| 3. Longitudinal labels | Reloading protocols; recomputing unaffected visit mappings. | Cache protocol versions and parameterized timelines; invalidate only affected dependencies. | New baseline/endpoint/censoring rules require reassessment. |
| 4. Access/reuse | Repeated availability requests; downloading unchanged agreements; polling denials. | Short-lived scoped status cache, conditional retrieval, exact versioned clause lookup. | Availability is not permission; currentness and authorization override cache reuse. |
| 5. Multi-omics joins | Re-fetching manifests and repeating identical joins. | Hash/version manifests and key definitions; cache deterministic cardinality and match outputs. | Never reuse a result for changed tissue, episode, release or key semantics. |
| 6. Microbiome QC | Repeated database/protocol discovery; reading every raw run. | Cache version documentation and compute bounded QC/design summaries first. | Do not claim computation resolves missing controls or perfect confounding. |

## 7. Measurement and rollout

Establish an uncached baseline before optimization. Use identical fixture
versions, requirements, provider/model configuration, and allowed sources when
comparing approaches. Measure cold and warm cases separately, with at least
30 runs per workload and the reference conditions in the requirements.

Compare: baseline; Strategy A; A+C; and optional A+C+B. Include paraphrases,
requirement changes, source updates, deleted documents, changed permissions,
outages, concurrent duplicate requests, and explicit fresh-check requests.
Separate replayed-tool evaluation from live-provider measurements.

Proposed pilot goals, subject to baseline measurement:

| Workload | Candidate goal | Quality condition |
| --- | --- | --- |
| Repeated same-endpoint status checks in a permitted 30-second window | At least 80% fewer upstream requests than one request per user check, when request volume permits reuse. | Correct source/age shown; fresh-check requests and auth boundaries respected. |
| Repeated evidence-heavy cases with unchanged sources | At least 40% fewer external requests and 25% fewer model input tokens. | Same supported claims, exact counts and valid citations as baseline. |
| Warm repeated cases | At least 20% lower p95 response latency. | No regression against the requirements' quality and safety gates. |

These goals are experiments, not promises. Low-repetition workloads may not
benefit; cache maintenance and semantic lookup can add cost. Report misses and
worst-case overhead as well as savings. Quality gates take precedence over
aggregate averages: zero cross-case leaks, no fabricated identifiers/citations,
and correct fixture counts remain required.

Release A+C first behind configurable policies. Add semantic lead caching only
when measured gains justify its complexity. Publish a report with actual call
counts, tokens, bytes, CPU/OCR time, storage, median/p95 latency, cost attribution,
and correctness/freshness failures before claiming an optimized support agent.
