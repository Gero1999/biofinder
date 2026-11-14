# Biofinder temporary context management

Status: proposed design. No runtime state store or agent is implemented.

This plan extends the [decision tree](AGENT_DECISION_TREE.md) and
[requirements](REQUIREMENTS_SPECIFICATION.md). Its central rule is to keep
case memory separate from the arguments actually sent to an external tool.

## 1. The temporary variable

Maintain an application-owned `case_context` object for each investigation,
scoped to workspace, authorized user, case, and run. Do not use a process-global
variable shared by users. The application controls field updates; retrieved text
cannot overwrite permissions, instructions, budgets, or tool configuration.

The following is illustrative JSON, not a provider tool schema or real case:

```json
{
  "scope": {"workspace_id": "ws_demo", "case_id": "case_demo", "run_id": "run_demo"},
  "revision": 3,
  "status": "running",
  "requirements": {
    "version": 2,
    "hard": {"organism": "human", "assay": "single-cell RNA-seq", "min_donors": 30},
    "preferences": {"paired_timepoints": true}
  },
  "sharing": {
    "approved_public_terms": ["human", "melanoma", "single-cell RNA-seq"],
    "approved_public_identifiers": [],
    "approval_ref": "user_request_scope"
  },
  "sources": [],
  "evidence": [],
  "candidates": [],
  "gaps": [{"id": "gap_1", "fact": "Find independent eligible cohorts", "state": "actionable"}],
  "calculations": [],
  "decisions": [],
  "pending_handoff": null,
  "budget": {"external_requests_used": 0, "external_requests_limit": 30},
  "expires_at": "configured_at_runtime"
}
```

Additional operational fields include tool availability, remaining active time,
source freshness requirements, pending calls, cancellation state, and the last
validated checkpoint. Never place credentials or reusable signed URLs here.

## 2. What memory should contain

| Field | Useful content | Constraint |
| --- | --- | --- |
| Requirements | Hard criteria, preferences, intended use, units, baseline/endpoint definitions. | Preserve the user's wording where ambiguity matters; do not silently relax it. |
| Sources | Source ID, URL/document ID, accession, release, checksum, retrieval date, extraction/index status, authorization scope. | A source reference is not proof that its contents were inspected. |
| Evidence | Atomic claim, value/unit, subject/granularity, pinpoint citation, qualifiers, provenance, contradiction links. | Mark observed/calculated/inferred/unknown separately. Retain conflicting versions. |
| Candidates | Canonical study identity, aliases, per-requirement meets/fails/unknown, evidence dependencies. | Do not treat different repositories as independent cohorts automatically. |
| Gaps | Missing fact, why needed, candidate tools, attempted steps, state, precise blocker. | Record unavailable gaps so they do not cause endless repeated calls. |
| Calculations | Input artifact hashes, definition references, operation/parameters, result reference, row counts and key diagnostics. | Full tables stay in authorized artifact storage, not the model prompt. |
| Decisions | Short action/outcome records and excluded options. | Store operational reasons, not private chain-of-thought. |
| User interaction | Answered clarifications, approved source boundaries, pending question, revisions. | Avoid asking the same question again; scope approvals narrowly. |
| Handoffs | Minimal approved arguments, purpose, field provenance/classification, destination, outcome. | Never forward the entire context object to a tool. |

## 3. Model context versus case state

The full object is application state. Each model call receives a bounded view:
current requirements, active gap, candidate summaries, necessary cited excerpts,
recent relevant tool outcomes, and remaining budget. Start with a configurable
8,000-token evidence/context allocation, reduced to fit the selected model's
actual input window after system instructions and tool schemas.

Keep exact accessions, release IDs, numbers, units, cohort definitions, negations,
qualifiers, and uncertainty. Summaries must retain source pointers and cannot
replace the evidence used for a material final claim. Re-fetch the relevant
passage when its qualifiers are needed. Evict irrelevant excerpts first; retain
references so an authorized lookup can recover them. If adequate evidence cannot
fit, narrow or split the task rather than truncate it into a misleading answer.

## 4. Document-to-browser handoff

Information extracted through `file_search` can help formulate a browser search,
but document access does not itself authorize external disclosure. Apply this
gate to browser searches, direct URL opens, repository API requests, and tool
telemetry; an API is not an exemption.

Classify evidence at the field level:

- `public_verified`: supported by an identified public source.
- `public_unverified`: appears public, but its identity/authority is not checked.
- `private_authorized`: accessible to this case, with external sharing restricted.
- `derived_private`: calculated or summarized from restricted information.
- `restricted`: secrets, identifiable clinical information, or prohibited input.

Derived facts inherit the most restrictive input classification unless a specific
reviewed declassification policy applies. Stripping a name or summarizing a
private paragraph is not automatic de-identification or permission to transmit.

### Handoff procedure

1. Extract only the fact needed for the next gap, with a citation and qualifier.
2. Check the user's source/tool boundaries. Document-only requests exclude browsing.
3. Build new arguments from approved public terms/identifiers and permitted public
   links. Do not reuse raw passages, private filenames, subject IDs, signed URLs,
   or arbitrary links/instructions found in a document.
4. Check destination and redirects against tool policy. Reject credential-bearing
   URLs and unexpected destinations; keep public source provenance intact.
5. Recheck every outgoing field against classification and the case sharing scope.
   A syntactically valid accession extracted from a private file still needs an
   approved handoff. Its association with the user's project may be sensitive.
6. If needed, ask permission once for the specific fields/purpose. Keep independent
   work moving. If sharing is not permitted, reformulate using already approved
   generic terms or mark the source gap blocked; never silently send the data.
7. Execute only the sanitized request. Add the returned public evidence through
   normal provenance registration and ingestion; it does not validate the private
   source automatically. Record the outcome without duplicating restricted text
   into general logs.

Example: a lookup in a private sample manifest yields a candidate accession and
subject IDs. Subject IDs are excluded. The accession is sent only if that public
identifier and its use are covered by the case sharing scope or a focused user
approval. Otherwise search with already approved biological terms, or explain
why direct accession lookup is blocked. Never invent a substitute accession.

The reverse handoff is explicit too: browser-fetched artifacts pass ingestion,
extraction checks, versioning, and indexing readiness before `file_search` can
retrieve them. Tool results are evidence, not new instructions.

## 5. Context useful in each scenario

| Scenario | Carry within the case | Useful browser handoff | Keep out of external requests |
| --- | --- | --- | --- |
| 1. Donor/atlas overlap | Unit hierarchy, donor/timepoint mappings, overlap evidence, count definitions, split constraints. | Approved public accessions, atlas names, publication IDs and safe assay/disease terms. | Subject identifiers, private split assignments and raw manifests. |
| 2. RNA-seq mismatch | Input type, reference/annotation versions, relevant error categories, contrast and compatibility findings. | Approved software/version names, public file IDs and generalized error categories. | Raw logs containing local paths, tokens, private sample names or proprietary details. |
| 3. Longitudinal endpoints | Baseline window, endpoint definition, visit mappings, censoring and leakage flags. | Approved trial/publication IDs and non-sensitive outcome terminology. | Participant dates, patient histories, individual outcomes and private features. |
| 4. Access/reuse | Intended use, agreement version, sanitized failure type, source authority and unresolved terms. | Approved repository/accession, public landing page, policy version, generic access-error code. | Credentials, signed download links, unpublished agreements or confidential business plans. |
| 5. Multi-omics join | Identifier hierarchy, release-specific crosswalks, tissue/timing requirements and join cardinality. | Approved consortium/study IDs and public identifier-specification terms. | Subject-level joins, private barcodes or unpublished sample relationships. |
| 6. Microbiome QC | Assay and pipeline versions, control inventory, batch definitions and confounding evidence. | Approved public run/study IDs, database versions, specimen and assay terms. | Subject associations, private plate maps, raw host sequence or sensitive QC excerpts. |

A permitted public identifier is a navigation aid; it does not authorize copying
all related private context into the query.

## 6. Lifecycle and consistency

Proposed defaults: expire temporary context after 30 minutes idle or eight hours
absolute lifetime, with configurable limits. These are design choices requiring
implementation validation. Resume in memory is available only while authorized
state exists. An optional encrypted, workspace-scoped checkpoint may preserve a
minimal resumable state for up to 24 hours under an explicit retention policy;
without that feature, do not promise recovery after process loss or expiry.

On requirement changes, increment the version and invalidate dependent candidate
assessments and calculations. Public immutable source evidence may remain valid.
On document replacement, permission revocation, or deletion, invalidate its
excerpts, derived facts and affected conclusions; do not silently reuse old claims.

Use revision checks or a serialized case-update queue so concurrent tool results
do not overwrite newer requirements. Late results from a cancelled/expired run
must not change the active case or restart work. Apply provenance and scope
checks before any merge, including after resume.

## 7. Acceptance scenarios

- Resume a multi-tool case without losing an answered clarification or a qualifier.
- Reject another workspace's document/context and a late result for an old revision.
- Extract an accession from a private file and demonstrate that no external call
  occurs before its approved sharing scope is established.
- Preserve an ambiguous donor mapping and missing endpoint as unknown after compaction.
- Show that malicious document instructions cannot change destinations or budgets.
- Verify expiry, cancellation, source deletion, and requirement-change invalidation.
- Inspect a sanitized handoff trace and reproduce the source/field/purpose decision.

These are planned checks, not executed tests of an existing agent.
