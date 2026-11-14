# Biofinder cache strategies

Status: proposed design; no caches or measured savings exist yet. This plan
extends [temporary context](CONTEXT_MANAGEMENT_PLAN.md),
[decision routing](AGENT_DECISION_TREE.md), and the
[requirements](REQUIREMENTS_SPECIFICATION.md).

`case_context` is live investigation memory. A cache stores reusable outputs
with identity, provenance, freshness, and invalidation rules. Neither replaces
authorization checks or the authoritative source.

## 1. Strategy A: exact, layered evidence caching

Cache source retrieval, extraction/indexing artifacts, and exact document queries
separately. A repeated public accession or source version should not require a
new discovery search or repeated PDF parsing when a valid artifact is reusable.

Example key components:

```text
source:       connector + canonical public ID/URL + release + representation
extraction:   content checksum + parser/OCR version + extraction settings
lookup:       workspace/ACL scope + authorized corpus snapshot + document versions
              + normalized query + filters + retrieval settings/model version
```

Canonicalization must preserve query meaning, URL query parameters that identify
releases, and accession versions. Reject credential-bearing URLs as reusable
public keys. Normalize only documented aliases; two repositories may expose
one study but different artifacts.

| Cache layer | Reuse rule | Initial expiry/revalidation policy |
| --- | --- | --- |
| Versioned source artifact | Exact release and checksum; retain provenance and permitted storage scope. | Up to 7 days storage TTL; this never makes the version the latest. Apply observed withdrawal/deletion promptly. |
| Current unversioned metadata | Matching ID/representation, recent validation, and a query whose freshness tolerance permits reuse. | 10-minute TTL; explicitly current requests require source revalidation. |
| Extracted/indexed document | Same content hash, parser/OCR/index versions, current authorization and retention. | Reuse while source and index are valid; delete with the source or retention expiry. |
| Exact `file_search` result | Same authorized corpus snapshot, query, filters and retrieval configuration. | 15-minute TTL; document/ACL changes invalidate immediately when received. |
| Public repository/service status | Same approved endpoint, request purpose and visibility; timestamp shown. | 30-second TTL; never a substitute for dataset access authorization. |
| Not-found/empty response | Preserve whether the outcome was no hit, no index, 404, or transient failure. | At most 60 seconds for repeated checks; refresh after a relevant state change. |

These are initial configurable policies to validate. A storage TTL is not a
freshness guarantee, and cached status is not evidence that a user has permission.
An explicit “check now” request bypasses time-based reuse or conditionally
revalidates at the source. Terms and access decisions require the applicable
source/version and current authorization; old terms may answer a historical
question but cannot establish today's permission.

Use ETag/Last-Modified conditional requests when supported. A 304 can save bytes
and parsing, but still consumes a network request and provider quota. Do not
claim it reduced the number of API calls.

**Best fit:** repeat source visits, large supplements, stable release metadata,
known accessions, and repeated lookups within one case.

**Trade-offs:** strong identity and reproducibility; limited reuse for differently
phrased questions, and careful corpus/version invalidation is required.

## 2. Strategy B: scoped semantic retrieval caching

Reuse retrieval leads for semantically similar research questions after strict
scope and dependency checks. Cache candidate IDs, source references and useful
passage locations, rather than declaring a previous generated answer correct for
a new query.

The lookup has two gates:

1. Exact filters: workspace/authorization, organism, assay, specimen, intended use,
   timing/endpoint constraints, source restrictions, corpus snapshot and versions.
2. Semantic similarity inside that eligible partition, followed by verification
   against the new requirements and underlying evidence.

A similarity score is not a donor-count check, permission decision, or scientific
confidence. “At least 30 patients” and “30 samples” must not share an eligibility
answer merely because their embeddings are similar. Even an apparently identical
question must re-evaluate numeric constraints, release context and calculations.

Start with a one-hour maximum TTL and source-dependent shorter limits. Changed
requirements invalidate assessments; changed documents invalidate supporting
leads. A hit can seed the next investigation, but missing/new requirements still
create evidence gaps. When the corpus is small, semantic caching may cost more
than direct indexed retrieval; measure before enabling it broadly.

**Best fit:** repeated dataset-discovery questions, related support investigations,
and locating previously useful passages across a permitted document collection.

**Trade-offs:** broader reuse, with embedding overhead and higher false-hit risk.
Never use this as a shared cache of private conversational answers.

## 3. Strategy C: deterministic calculation and diagnosis caching

Cache exact metadata calculations and reusable diagnostic procedures independently
of natural-language answers.

A calculation key includes input file hashes and order where relevant, parsing
schema/version, identifier definitions, operation version, selected columns,
filters, date/unit interpretation, join keys/cardinality policy, and all parameters.
A hit is valid only if every dependency is unchanged and authorized.

Store outputs plus row counts, exclusions, warnings and provenance. Changing a
baseline window, minimum cohort size, key mapping, or intended-use restriction
invalidates the dependent result. Private input tables produce private outputs;
a derived count is not automatically safe for a public query or shared cache.

A diagnostic procedure can suggest steps, such as checking annotation versions
for unmatched gene IDs. It cannot reuse the previous case's diagnosis as a fact.

**Best fit:** donor recounts, multi-omics joins, visit timelines, QC summaries,
and repeated filters on the same versioned manifests.

**Trade-offs:** exact reuse and low inference cost, but schema/operation changes
must invalidate entries and output joins need resource limits.

## 4. Recommended rollout

Start with **A plus C**: source/extraction reuse, scoped exact lookup caching,
and deterministic calculation caching. Add B as a candidate/passage-lead cache
only after evaluation demonstrates useful savings without degraded eligibility
or citation quality. No single strategy is declared best without measurement.

For the six scenarios:

| Scenario | Priority layers | Critical invalidation |
| --- | --- | --- |
| 1. Donor/atlas overlap | A: study/supplement versions; C: crosswalks/counts; B: alternative cohort leads. | Donor mapping, split rules, atlas provenance or requirements change. |
| 2. RNA-seq mismatch | A: official file/version documentation; C: compatibility checks and identifier summaries. | Matrix, annotation, processing or contrast version changes. |
| 3. Longitudinal endpoints | A: protocol amendments; C: timelines/labels; B: validation-cohort leads. | Baseline, endpoint, censoring rule or trial/document version changes. |
| 4. Access/reuse | A: historical agreements and short-lived status checks; B only for alternative leads. | Currentness request, credentials/scope, terms update or access-policy change. |
| 5. Multi-omics joining | A: release/crosswalk documents; C: exact joins and pair counts. | Either manifest, tissue constraint, key definition or release changes. |
| 6. Microbiome QC | A: protocols/database documentation; C: controls/batch summaries; B: alternative leads. | Control manifest, QC inputs, case/batch labels or pipeline/database versions change. |

## 5. Isolation and invalidation

- Re-authorize every cache read. Never cache a grant as proof of continued access.
- Partition private entries by workspace and effective ACL; a cache key alone is
  not enforcement. Shared public artifacts require confirmed public provenance
  and permitted storage/reuse; exclude case-private query terms and associations.
- Keep raw source and derived-output classifications from the context plan.
  A hit still passes the document-to-browser disclosure gate before external use.
- Purge searchable derivatives and excerpts on authorized deletion/expiry; mark
  old report references unavailable rather than silently substituting another file.
- Cache 401/403 only as a short-lived, scope-specific error observation, never as
  a reusable permission decision. Retry after a meaningful auth/settings change.
- Do not reuse cancelled/partial generations as final answers. Verified source
  artifacts from those runs may be reusable after ordinary dependency checks.
- Use bounded storage, LRU eviction within TTL, and per-workspace quotas. A proposed
  pilot cap is 100 MiB for per-case transient artifacts and 1 GiB per workspace;
  source ingestion and deployment capacity may require different values.

## 6. Concurrency and observability

Coalesce identical in-flight public requests or same-scope private requests with
single-flight keys. Do not combine different ACLs or use a shared lock to reveal
private query activity. Give locks a timeout and propagate the producer's failure;
cancellation of one waiter must not cancel another case's authorized work.

Record hits, misses, revalidations, stale rejections, invalidations, storage,
bytes, saved parsing work, latency and actual upstream requests. Attribute cost
savings to the layer that avoided work. Report origin retrieval time and last
validation time on cached evidence so users can inspect its age.

## 7. Acceptance checks

Evaluate each strategy separately and in combination on all six curated scenarios:

- Exact repeated query; paraphrase; changed donor threshold; changed endpoint.
- Same accession with a new release; document replacement/deletion; changed ACL.
- Current status request during a provider outage and after recovery.
- Negative lookup before indexing, then after indexing becomes ready.
- Duplicate concurrent requests; producer failure; a cancelled waiting case.
- A private cached passage whose extracted identifier is not approved for browsing.

Measure hit rate and avoided calls alongside supported-claim accuracy, exact
counts, citation freshness and cross-case isolation. Cache savings must not be
achieved by serving stale or unauthorized conclusions. These checks and policies
remain unimplemented proposals.
