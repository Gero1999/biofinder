"""Decision-tree routing and bounded document-search fallbacks.

Adapters are injected; this module never invents search results or final scientific
conclusions. Each request represents the next information gap, not a whole case.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import ipaddress
import re
import time
from typing import Callable, Literal, Protocol
from urllib.parse import parse_qsl, urlsplit


Intent = Literal["auto", "documents", "discovery", "source", "calculation"]


@dataclass(frozen=True)
class Request:
    query: str
    intent: Intent = "auto"
    document_ids: tuple[str, ...] = ()
    reference: str | None = None
    version: str | None = None
    current: bool = False
    document_only: bool = False
    missing_information: tuple[str, ...] = ()
    permitted: bool = True
    private_source_missing: bool = False
    table_ids: tuple[str, ...] = ()
    definitions_verified: bool = False
    calculation: dict | None = None


def classify_query(request: Request) -> Intent | None:
    """Classify one evidence gap with transparent rules and no tool calls.

    Explicit intent takes precedence. Auto classification is only a bootstrap
    heuristic; callers should supply intent for nuanced/mixed research tasks.
    A None result requests clarification rather than guessing a tool.
    """
    words = request.query.lower()
    if request.intent != "auto":
        return request.intent
    elif re.search(r"\b(recount|deduplicate|calculate)\b|join these|cross-tabulate", words):
        return "calculation"
    elif request.current or re.search(r"\b(latest|current)\b", words):
        return "discovery"
    elif request.document_ids or request.document_only:
        return "documents"
    elif re.search(r"\b(find|discover|alternatives)\b", words):
        return "discovery"
    elif request.reference:
        return "source"
    elif re.search(r"\b(paper|document|supplement|protocol|logs?|manifest)\b", words):
        return "documents"
    else:
        return None


@dataclass(frozen=True)
class Source:
    url: str
    title: str = ""
    public: bool = True


@dataclass(frozen=True)
class Artifact:
    source: Source
    text: str
    version: str | None = None
    media_type: str = "text/plain"


@dataclass(frozen=True)
class Evidence:
    source_id: str
    location: str
    text: str
    version: str | None = None


@dataclass(frozen=True)
class Ingestion:
    case_id: str
    document_ids: tuple[str, ...]
    ready: bool


@dataclass
class CaseContext:
    """One authorized case, owned by the application; never sent to the browser."""
    case_id: str
    authorized_document_ids: set[str] = field(default_factory=set)
    approved_public_terms: tuple[str, ...] = ()
    approved_references: set[str] = field(default_factory=set)
    allowed_hosts: set[str] = field(default_factory=set)
    cancelled: bool = False
    request_limit: int = 30
    external_requests: int = 0
    deadline: float = field(default_factory=lambda: time.monotonic() + 480)
    trace: list[str] = field(default_factory=list)
    force_refresh: bool = False


@dataclass(frozen=True)
class Outcome:
    status: str
    route: str
    message: str
    evidence: tuple[Evidence, ...] = ()
    leads: tuple[Source, ...] = ()
    trace: tuple[str, ...] = ()
    unresolved: tuple[str, ...] = ()


class ToolError(Exception):
    """Permanent/unspecified failure; never blindly retry or echo private errors."""


class AccessDenied(ToolError):
    pass


class TransientError(ToolError):
    """Adapter may supply a provider Retry-After delay in seconds."""
    def __init__(self, retry_after: float | None = None):
        self.retry_after = retry_after


class BudgetExceeded(ToolError):
    pass


class Cancelled(ToolError):
    pass


class FileSearch(Protocol):
    remote: bool

    def ready(self, ids: tuple[str, ...], *, case_id: str, version: str | None,
              timeout: float) -> bool: ...

    def search(self, query: str, ids: tuple[str, ...], *, case_id: str,
               version: str | None, contextual: bool, timeout: float) -> tuple[Evidence, ...]: ...


class Browser(Protocol):
    def search(self, query: str, *, timeout: float) -> tuple[Source, ...]: ...

    def open(self, source: Source, *, timeout: float) -> Artifact: ...


class Ingestor(Protocol):
    remote: bool

    def ingest(self, artifact: Artifact, *, case_id: str, timeout: float) -> Ingestion: ...


class TableProcessor(Protocol):
    def calculate(self, query: str, ids: tuple[str, ...], *, case_id: str,
                  timeout: float) -> tuple[Evidence, ...]: ...


class BiofinderAgent:
    def __init__(self, context: CaseContext, *, file_search: FileSearch | None = None,
                 browser: Browser | None = None, ingestor: Ingestor | None = None,
                 tables: TableProcessor | None = None,
                 wait: Callable[[float], None] = time.sleep, progress: Callable | None = None):
        self.context = context
        self.file_search = file_search
        self.browser = browser
        self.ingestor = ingestor
        self.tables = tables
        self.wait = wait
        self.progress = progress

    def _outcome(self, status: str, route: str, message: str, *,
                 evidence: tuple[Evidence, ...] = (), leads: tuple[Source, ...] = (), unresolved: tuple[str, ...] = ()) -> Outcome:
        # Retrieval is not final claim validation (V0/D8); evidence stays partial.
        return Outcome(status, route, message, evidence, leads, tuple(self.context.trace), unresolved)

    def _guard(self) -> None:
        if self.context.cancelled:
            raise Cancelled()
        if time.monotonic() >= self.context.deadline:
            raise BudgetExceeded()

    def _call(self, label: str, operation: Callable, *, remote: bool, **kwargs):
        for attempt in range(3):
            self._guard()  # D3: before every underlying operation and retry.
            owner = getattr(operation, "__self__", None)
            accounted = getattr(owner, "accounts_requests", False) is True
            if remote and not accounted:
                if self.context.external_requests >= self.context.request_limit:
                    raise BudgetExceeded()
                self.context.external_requests += 1
            self.context.trace.append(label)  # No private query text or tool error body.
            if self.progress:
                self.progress({"stage": label, "external_requests": self.context.external_requests})
            self._guard()
            try:
                result = operation(timeout=min(30.0, self.context.deadline - time.monotonic()), **kwargs)
                self._guard()  # Do not accept late results from a cancelled/expired run.
                return result
            except TransientError as exc:
                delay = exc.retry_after if exc.retry_after is not None else 2 ** attempt
                if delay < 0 or not float(delay) < float("inf"):
                    raise ToolError() from exc
                if attempt == 2:
                    raise
                self._guard()
                if time.monotonic() + delay >= self.context.deadline:
                    raise BudgetExceeded() from exc
                self.wait(delay)
        raise AssertionError("unreachable")

    def _public_query(self, request: Request) -> str | None:
        # Never derive outgoing terms from the raw query or a private search hit.
        if request.document_only or not self.context.approved_public_terms:
            return None
        return " ".join(self.context.approved_public_terms)

    def _safe_source(self, source: Source) -> bool:
        try:
            parsed = urlsplit(source.url)
            host = (parsed.hostname or "").lower()
        except ValueError:
            return False
        sensitive = {"token", "key", "api_key", "signature", "credential", "password", "auth"}
        if (not source.public or parsed.scheme not in {"https", "http"} or
                parsed.username or parsed.password or host not in self.context.allowed_hosts or
                any(any(part in k.lower() for part in sensitive) or k.lower().startswith("x-amz-")
                    for k, _ in parse_qsl(parsed.query))):
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            return "." in host and not host.endswith((".local", ".localhost"))

    def route_request(self, request: Request) -> Outcome:
        """P0/D0/D1/D3/D4: choose a route with explicit if/elif/else logic."""
        self.context.trace.clear()
        self.context.force_refresh = request.current or bool(
            request.intent == "auto" and re.search(r"\b(latest|current)\b", request.query.lower()))
        try:
            self._guard()
            if not request.permitted:
                return self._outcome("blocked", "scope", "This information gap is outside the permitted scope.")
            elif not request.query.strip():
                return self._outcome("needs_input", "intake", "Provide a research question or support request.")
            elif request.missing_information:
                return self._outcome("needs_input", "intake", "Clarify: " + "; ".join(request.missing_information))
            elif request.intent not in {"auto", "documents", "discovery", "source", "calculation"}:
                return self._outcome("needs_input", "intake", "Select a supported intent.")

            intent = classify_query(request)
            if intent is None:
                return self._outcome("needs_input", "intake", "Specify documents, a public source, or a dataset-discovery goal.")

            freshness_requested = request.current or (
                request.intent == "auto" and bool(re.search(r"\b(latest|current)\b", request.query.lower()))
            )
            if freshness_requested:
                # A currentness claim cannot be established from an old indexed copy.
                if request.document_only:
                    return self._outcome("blocked", "freshness", "Currentness requires an external check; document-only scope prevents it.")
                elif request.reference:
                    return self._source_handle(request)
                else:
                    return self._web_handle(request)
            elif request.document_only and intent in {"discovery", "source"}:
                return self.file_search_handle(request, allow_web_fallback=False)
            elif intent == "calculation":
                return self._table_handle(request)
            elif intent == "documents":
                return self.file_search_handle(request)
            elif intent == "source":
                return self._source_handle(request)
            else:
                return self._web_handle(request)
        except Cancelled:
            return self._outcome("cancelled", "guard", "Cancelled; no further calls started.")
        except BudgetExceeded:
            return self._outcome("partial", "guard", "Budget exhausted; preserve context and request continuation.")
        except AccessDenied:
            return self._outcome("blocked", "access", "Access denied. Resolve authorization before retrying this source.")
        except ToolError:
            return self._outcome("blocked", "tool", "A tool failed. Check its capability or source; no result was assumed.")

    def file_search_handle(self, request: Request, *, allow_web_fallback: bool = True) -> Outcome:
        """D5-D7/A3/A4/A8: ready lookup, one contextual retry, then safe fallback.

        Public callers normally enter through route_request(), which translates
        cancellation/budget/tool exceptions into outcomes.
        """
        self._guard()
        if not request.permitted:
            return self._outcome("blocked", "scope", "This gap is outside the permitted scope.")
        if request.current:
            if request.document_only:
                return self._outcome("blocked", "freshness", "An external check is outside document-only scope.")
            return self._source_handle(request) if request.reference else self._web_handle(request)
        ids = request.document_ids
        if not set(ids) <= self.context.authorized_document_ids:
            raise AccessDenied()
        elif not ids:
            if request.private_source_missing or request.document_only:
                return self._outcome("needs_input", "documents", "Supply the authorized document; nothing was searched online.")
            elif request.reference:
                return self._source_handle(request)
            elif allow_web_fallback:
                return self._web_handle(request)
            else:
                return self._outcome("partial", "documents", "No searchable document was obtained.")
        elif self.file_search is None:
            return self._outcome("blocked", "documents", "A file_search adapter is required for these documents.")
        else:
            ready = self._call("D5:index_readiness", self.file_search.ready,
                               remote=self.file_search.remote, ids=ids,
                               case_id=self.context.case_id, version=request.version)
            if not ready:
                return self._outcome("partial", "documents", "Index/version is not ready. Complete ingestion before retrying; absence is not established.")
            hits = self._call("A3:file_search", self.file_search.search,
                              remote=self.file_search.remote, query=request.query, ids=ids,
                              case_id=self.context.case_id, version=request.version, contextual=False)
            self._validate_hits(hits, ids, request.version)
            if hits:
                return self._outcome("partial", "documents", "Evidence retrieved; final claim validation is still required.", evidence=hits)
            else:
                # One distinct contextual lookup, not an unbounded identical query loop.
                hits = self._call("R1:contextual_file_search", self.file_search.search,
                                  remote=self.file_search.remote, query=request.query, ids=ids,
                                  case_id=self.context.case_id, version=request.version, contextual=True)
                self._validate_hits(hits, ids, request.version)
                if hits:
                    return self._outcome("partial", "documents", "Contextual evidence retrieved; validate its qualifiers.", evidence=hits)
                elif request.document_only or request.private_source_missing or not allow_web_fallback:
                    return self._outcome("partial", "documents", "No supporting passage found; do not infer absence. Check source coverage.")
                else:
                    # Only preapproved public terms cross this boundary, never hit text.
                    return self._web_handle(request)

    def _validate_hits(self, hits, ids, version):
        for hit in hits:
            if not isinstance(hit, Evidence) or hit.source_id not in ids:
                raise AccessDenied()
            if not hit.text or not hit.location or (version is not None and hit.version != version):
                raise ToolError()

    def _web_handle(self, request: Request) -> Outcome:
        query = self._public_query(request)
        if query is None:
            return self._outcome("needs_input", "sharing", "Approve safe public search terms or retain document-only scope.")
        elif self.browser is None:
            return self._outcome("blocked", "browser", "No browser search adapter is configured.")
        else:
            leads = self._call("A5:browser_search", self.browser.search, remote=True, query=query)
            safe = tuple(source for source in leads if self._safe_source(source))
            if not safe:
                return self._outcome("partial", "browser", "No permitted source found. Results are not proof of absence.")
            elif self.ingestor is None or self.file_search is None:
                return self._outcome("partial", "browser", "Sources discovered; configure ingestion and file_search to inspect them.", leads=safe)
            else:
                collected = []
                last_outcome = None
                errors = []
                unavailable = []
                for source in safe[:3]:
                    try:
                        outcome = self._open_and_lookup(request, source, safe)
                        last_outcome = outcome
                        collected.extend(outcome.evidence)
                    except (AccessDenied, ToolError) as error:
                        if isinstance(error, (Cancelled, BudgetExceeded)):
                            raise
                        errors.append(error)
                        unavailable.append("Source unavailable: " + source.url)
                        self.context.trace.append("A8:source_unavailable")
                unique = tuple(dict.fromkeys(collected))
                if unique:
                    return self._outcome("partial", "browser", "Sources inspected; validate evidence and unresolved sources.",
                                         evidence=unique, leads=safe, unresolved=tuple(unavailable))
                elif last_outcome is not None:
                    return last_outcome
                elif any(isinstance(error, AccessDenied) for error in errors):
                    raise AccessDenied()
                else:
                    raise ToolError()

    def _source_handle(self, request: Request) -> Outcome:
        if request.document_only:
            return self._outcome("blocked", "source", "Document-only scope prevents external source lookup.")
        elif not request.reference or request.reference not in self.context.approved_references:
            return self._outcome("needs_input", "sharing", "Approve the public reference before sending it externally.")
        elif not self._safe_source(Source(request.reference)):
            return self._outcome("blocked", "source", "Reference must be a permitted public URL without embedded credentials.")
        elif self.browser is None:
            return self._outcome("blocked", "source", "No browser adapter is configured.")
        else:
            return self._open_and_lookup(request, Source(request.reference), ())

    def _open_and_lookup(self, request: Request, source: Source, leads: tuple[Source, ...]) -> Outcome:
        artifact = self._call("A6:browser_open", self.browser.open, remote=True, source=source)
        # Adapters must also enforce redirect/DNS policy before transmitting requests.
        if not self._safe_source(artifact.source):
            raise AccessDenied()
        elif request.version is not None and artifact.version != request.version:
            return self._outcome("partial", "source", "Retrieved source version does not match the requested version; no substitution was made.", leads=leads)
        elif self.ingestor is None or self.file_search is None:
            return self._outcome("partial", "ingestion", "Source opened; ingestion/file_search is required before document lookup.", leads=leads)
        else:
            indexed = self._call("A4:ingest", self.ingestor.ingest, remote=self.ingestor.remote,
                                 artifact=artifact, case_id=self.context.case_id)
            if indexed.case_id != self.context.case_id:
                raise AccessDenied()
            self.context.authorized_document_ids.update(indexed.document_ids)
            if not indexed.ready:
                return self._outcome("partial", "ingestion", "Indexing is pending; resume after readiness changes.", leads=leads)
            lookup = Request(query=request.query, intent="documents", document_ids=indexed.document_ids,
                             version=artifact.version, document_only=request.document_only)
            # Never recurse from an empty newly ingested document back to the same web search.
            return self.file_search_handle(lookup, allow_web_fallback=False)

    def _table_handle(self, request: Request) -> Outcome:
        if not request.table_ids or not request.definitions_verified:
            return self._outcome("needs_input", "calculation", "Obtain complete tables and verified row/key definitions; snippets cannot establish counts.")
        elif not set(request.table_ids) <= self.context.authorized_document_ids:
            raise AccessDenied()
        elif self.tables is None:
            return self._outcome("blocked", "calculation", "Configure a deterministic table processor.")
        else:
            arguments = dict(query=request.query, ids=request.table_ids, case_id=self.context.case_id)
            if request.calculation is not None:
                arguments["specification"] = request.calculation
            evidence = self._call("A7:table_processing", self.tables.calculate, remote=False, **arguments)
            return self._outcome("partial", "calculation", "Calculation returned; validate the operation and input provenance.", evidence=evidence)
