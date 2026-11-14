"""Bounded multi-gap workflow, case memory, and extractive evidence validation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from copy import deepcopy
import csv
import hashlib
import io
import json
import math
import time

from annotation import (
    AccessDenied,
    BudgetExceeded,
    Cancelled,
    Evidence,
    Request,
    ToolError,
    TransientError,
)


@dataclass
class InvestigationState:
    revision: str = ""
    plan: list[dict] = field(default_factory=list)
    next_step: int = 0
    evidence: dict[str, Evidence] = field(default_factory=dict)
    outcomes: list[dict] = field(default_factory=list)
    unmet: list[str] = field(default_factory=list)
    model_calls: int = 0


class Investigation:
    def __init__(
        self,
        router,
        client,
        *,
        documents=None,
        tables=None,
        allow_model_context=False,
        max_steps=8,
        max_model_calls=8,
    ):
        self.router, self.client = router, client
        self.documents = dict(documents or {})
        self.tables = dict(tables or {})
        self.allow_model_context = allow_model_context
        self.max_steps, self.max_model_calls = max_steps, max_model_calls
        self.state = InvestigationState()
        self.latest_ids = ()
        self.metrics = {"tool_steps": 0, "model_calls": 0}

    def _model(self, stage, payload):
        self.router._guard()
        if getattr(self.client, "remote", False) and not self.allow_model_context:
            raise AccessDenied("Model case-context processing not approved")
        if self.state.model_calls >= self.max_model_calls:
            raise BudgetExceeded()
        if len(json.dumps(payload)) > 32000:
            raise ToolError("Model context limit exceeded; narrow the case")
        for attempt in range(3):
            self.router._guard()
            self.state.model_calls += 1
            self.metrics["model_calls"] += 1
            if self.state.model_calls > self.max_model_calls:
                raise BudgetExceeded()
            if self.router.progress:
                self.router.progress(
                    {"stage": "model:" + stage, "model_calls": self.state.model_calls}
                )
            self.router._guard()
            try:
                result = self.client.complete(stage, payload)
                self.router._guard()
                if not isinstance(result, dict):
                    raise ToolError("Expected JSON object")
                return result
            except TransientError as error:
                if attempt == 2:
                    raise
                delay = (
                    error.retry_after if error.retry_after is not None else 2**attempt
                )
                if not isinstance(delay, (int, float)) or not 0 <= delay < float("inf"):
                    raise ToolError()
                if time.monotonic() + delay >= self.router.context.deadline:
                    raise BudgetExceeded()
                self.router.wait(delay)
        raise AssertionError("unreachable")

    def _remember(self, evidence):
        for entry in evidence:
            if not entry.source_id or not entry.location or not entry.text:
                raise ToolError("Incomplete provenance")
            if entry.source_id.startswith("calculation:"):
                payload = json.loads(entry.text)
                if (
                    not isinstance(payload, dict)
                    or not payload.get("input_ids")
                    or not set(payload["input_ids"])
                    <= self.router.context.authorized_document_ids
                ):
                    raise AccessDenied()
            elif entry.source_id not in self.router.context.authorized_document_ids:
                raise AccessDenied()
            if entry not in self.state.evidence.values():
                self.state.evidence[f"E{len(self.state.evidence)+1}"] = entry

    def _ids(self, selection):
        if selection == "case":
            return tuple(self.documents.values())
        if selection == "latest":
            return self.latest_ids
        if isinstance(selection, list) and all(
            name in self.documents for name in selection
        ):
            return tuple(self.documents[name] for name in selection)
        raise ToolError("Unknown document selection")

    def _request(self, step, document_only):
        if not isinstance(step, dict) or not isinstance(step.get("query"), str):
            raise ToolError("Invalid plan step")
        intent = step.get("intent")
        if intent not in {"documents", "discovery", "source", "calculation"}:
            raise ToolError("Unsupported plan intent")
        ids = self._ids(step.get("documents", "case"))
        table_ids = ()
        verified = False
        calculation = step.get("calculation")
        if intent == "calculation":
            names = step.get("tables", [])
            if not names or any(name not in self.tables for name in names):
                raise ToolError("Unknown table input")
            table_ids = tuple(self.tables[name] for name in names)
            if not set(table_ids) <= self.router.context.authorized_document_ids:
                raise AccessDenied()
            if not calculation or not step.get("definition_quote"):
                # Plan before retrieval; choose columns only after definitions are available.
                schemas = {}
                for name, identifier in zip(names, table_ids):
                    artifact = self.router.file_search.documents[identifier]
                    delimiter = (
                        "\t"
                        if artifact.media_type == "text/tab-separated-values"
                        else ","
                    )
                    schemas[name] = next(
                        csv.reader(io.StringIO(artifact.text), delimiter=delimiter), []
                    )
                visible = {
                    key: asdict(e)
                    for key, e in self.state.evidence.items()
                    if e.source_id in self.router.context.authorized_document_ids
                }
                resolved = self._model(
                    "calculation",
                    {"step": step, "table_columns": schemas, "evidence": visible},
                )
                calculation = resolved.get("calculation")
                step = dict(step, definition_quote=resolved.get("definition_quote", ""))
            quote = step.get("definition_quote", "")
            verified = (
                isinstance(quote, str)
                and bool(quote)
                and any(
                    quote in e.text
                    and e.source_id in self.router.context.authorized_document_ids
                    for e in self.state.evidence.values()
                )
            )
        return Request(
            step["query"],
            intent=intent,
            document_ids=ids,
            reference=step.get("reference"),
            current=bool(step.get("current", False)),
            document_only=document_only,
            table_ids=table_ids,
            definitions_verified=verified,
            calculation=calculation,
        )

    def _validate(self, draft):
        claims = draft.get("claims", [])
        if not isinstance(claims, list) or len(claims) > 20:
            raise ToolError("Invalid claims")
        accepted = []
        for claim in claims:
            if not isinstance(claim, dict):
                raise ToolError("Invalid claim")
            citations = claim.get("citations", [])
            statement = claim.get("statement")
            if (
                not isinstance(citations, list)
                or not citations
                or not isinstance(statement, str)
            ):
                raise ToolError("Claim lacks citation")
            supported = False
            for citation in citations:
                if not isinstance(citation, dict):
                    raise ToolError("Invalid citation")
                evidence = self.state.evidence.get(citation.get("id"))
                quote = citation.get("quote")
                if evidence is not None:
                    inputs = (
                        json.loads(evidence.text)["input_ids"]
                        if evidence.source_id.startswith("calculation:")
                        else [evidence.source_id]
                    )
                    if not set(inputs) <= self.router.context.authorized_document_ids:
                        raise AccessDenied()
                if (
                    not evidence
                    or not isinstance(quote, str)
                    or not quote
                    or quote not in evidence.text
                ):
                    raise ToolError("Unsupported quotation/citation")
                # This MVP guarantees extractive support, not general semantic entailment.
                if statement == quote:
                    supported = True
            if not supported:
                raise ToolError(
                    "Only exactly supported extractive statements are accepted"
                )
            accepted.append(claim)
        unresolved = draft.get("unresolved", [])
        if not isinstance(unresolved, list) or not all(
            isinstance(v, str) for v in unresolved
        ):
            raise ToolError("Invalid unresolved items")
        return accepted, unresolved

    def run(self, query, *, requirements=None, document_only=False, resume=False):
        requirements = requirements or {}
        if (
            not isinstance(query, str)
            or not query.strip()
            or not isinstance(requirements, dict)
        ):
            raise ValueError("Provide a query and structured requirements")
        criteria = requirements.get("criteria", [])
        if not isinstance(criteria, list) or any(
            not isinstance(c, dict)
            or not isinstance(c.get("minimum"), (int, float))
            or isinstance(c.get("minimum"), bool)
            or not math.isfinite(c["minimum"])
            or not isinstance(c.get("operation"), str)
            or not isinstance(c.get("field"), str)
            for c in criteria
        ):
            raise ValueError(
                "Criteria require an operation, field and finite numeric minimum"
            )
        self.requirements = requirements
        revision = hashlib.sha256(
            json.dumps([query, requirements, document_only], sort_keys=True).encode()
        ).hexdigest()
        if resume and self.state.revision and self.state.revision != revision:
            raise ValueError("Requirements changed; start a new investigation")
        if not resume:
            self.state = InvestigationState(revision=revision)
        started = time.perf_counter()
        try:
            self.router._guard()
            if not self.state.plan:
                plan = self._model(
                    "plan",
                    {
                        "query": query,
                        "requirements": requirements,
                        "documents": list(self.documents),
                        "tables": list(self.tables),
                        "document_only": document_only,
                    },
                )
                steps = plan.get("steps")
                if not isinstance(steps, list) or not 1 <= len(steps) <= self.max_steps:
                    raise ToolError("Invalid step count")
                # Validate identities/shape before starting any planned tools.
                for step in steps:
                    if not isinstance(step, dict) or not step.get("id"):
                        raise ToolError("Missing step ID")
                if len({s["id"] for s in steps}) != len(steps):
                    raise ToolError("Duplicate step IDs")
                self.state.plan = steps
            while self.state.next_step < len(self.state.plan):
                self.router._guard()
                step = self.state.plan[self.state.next_step]
                outcome = self.router.route_request(self._request(step, document_only))
                self.metrics["tool_steps"] += 1
                self.state.outcomes.append(
                    {
                        "step": step["id"],
                        "status": outcome.status,
                        "route": outcome.route,
                        "message": outcome.message,
                        "trace": outcome.trace,
                    }
                )
                self._remember(outcome.evidence)
                self.state.unmet.extend(outcome.unresolved)
                if outcome.evidence:
                    self.latest_ids = tuple(
                        dict.fromkeys(
                            e.source_id
                            for e in outcome.evidence
                            if not e.source_id.startswith("calculation:")
                        )
                    )
                if outcome.status == "cancelled":
                    return self._report("cancelled", started)
                if outcome.route == "guard":
                    return self._report("partial", started)
                if outcome.status == "needs_input":
                    return self._report("needs_input", started)
                if not outcome.evidence:
                    self.state.unmet.append(f"{step['id']}: {outcome.message}")
                self.state.next_step += 1
            # Recheck source access before synthesis; revoked artifacts cannot support a report.
            for evidence in self.state.evidence.values():
                if evidence.source_id.startswith("calculation:"):
                    if (
                        not set(json.loads(evidence.text)["input_ids"])
                        <= self.router.context.authorized_document_ids
                    ):
                        raise AccessDenied()
                elif (
                    evidence.source_id
                    not in self.router.context.authorized_document_ids
                ):
                    raise AccessDenied()
            if not self.state.evidence:
                return self._report("blocked", started)
            payload = {
                "query": query,
                "requirements": requirements,
                "evidence": {
                    key: asdict(value) for key, value in self.state.evidence.items()
                },
                "unresolved": self.state.unmet,
            }
            claims, unresolved = self._validate(self._model("synthesis", payload))
            self.state.unmet.extend(unresolved)
            status = "partial" if self.state.unmet or not claims else "completed"
            return self._report(status, started, claims)
        except Cancelled:
            return self._report("cancelled", started)
        except BudgetExceeded:
            return self._report("partial", started)
        except (ToolError, ValueError, TypeError, KeyError) as error:
            # No raw provider payload, private query, or credential-bearing exception is logged.
            self.state.unmet.append(
                "Investigation could not validate an operation or source; inspect configuration and inputs."
            )
            return self._report(
                "partial" if self.state.evidence else "blocked", started
            )

    def _report(self, status, started, claims=None):
        visible = {}
        for key, value in self.state.evidence.items():
            if value.source_id.startswith("calculation:"):
                if (
                    set(json.loads(value.text)["input_ids"])
                    <= self.router.context.authorized_document_ids
                ):
                    visible[key] = value
            elif value.source_id in self.router.context.authorized_document_ids:
                visible[key] = value
        calculations = [
            json.loads(e.text)
            for e in visible.values()
            if e.source_id.startswith("calculation:")
        ]
        criteria = []
        for criterion in getattr(self, "requirements", {}).get("criteria", []):
            item = {"id": criterion.get("id"), "status": "unknown"}
            for calculation in calculations:
                if calculation["operation"] != criterion.get("operation"):
                    continue
                if (
                    "column" in criterion
                    and calculation["parameters"].get("column") != criterion["column"]
                ):
                    continue
                value = calculation["result"].get(criterion.get("field"))
                minimum = criterion.get("minimum")
                if isinstance(value, (int, float)) and isinstance(
                    minimum, (int, float)
                ):
                    item.update(
                        value=value,
                        minimum=minimum,
                        status="meets" if value >= minimum else "fails",
                    )
            criteria.append(item)
        return {
            "status": status,
            "execution_mode": getattr(
                getattr(self.client, "transport", None), "mode", "custom"
            ),
            "claims": claims or [],
            "criteria": criteria,
            "evidence": {
                key: self._evidence_record(value) for key, value in visible.items()
            },
            "calculations": calculations,
            "unresolved": list(dict.fromkeys(self.state.unmet)),
            "next_step": self.state.next_step,
            "api_usage": {
                "calls": getattr(self.client, "calls", None),
                "input_tokens": (
                    getattr(self.client, "input_tokens", None)
                    if getattr(self.client, "usage_reported", False)
                    else None
                ),
                "output_tokens": (
                    getattr(self.client, "output_tokens", None)
                    if getattr(self.client, "usage_reported", False)
                    else None
                ),
            },
            "metrics": dict(
                self.metrics,
                external_requests=self.router.context.external_requests,
                elapsed_seconds=time.perf_counter() - started,
            ),
            "steps": deepcopy(self.state.outcomes),
        }

    def _evidence_record(self, value):
        record = asdict(value)
        store = getattr(self.router.file_search, "documents", {})
        artifact = store.get(value.source_id)
        if artifact is not None:
            record["source_url"] = artifact.source.url
            record["public"] = artifact.source.public
        return record
