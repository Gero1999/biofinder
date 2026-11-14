"""Application wiring for live clients or zero-cost predefined scenario responses."""

import hashlib
from annotation import Artifact, BiofinderAgent, CaseContext, Source
from api_client import HTTPTransport, OpenAIClient
from browser import WebBrowser
from cache import ExactCache
from fixtures import FixtureTransport, load_scenario
from integration import LocalFileSearch, LocalIngestor
from table_processing import TableProcessor
from workflow import Investigation


def build_investigation(
    *,
    case_id,
    public_terms=(),
    allowed_hosts=(),
    approved_references=(),
    documents=None,
    tables=None,
    transport_factory=HTTPTransport,
    cache=None,
    model=None,
    model_key=None,
    search_key=None,
    allow_model_context=False,
):
    context = CaseContext(
        case_id,
        approved_public_terms=tuple(public_terms),
        allowed_hosts=set(allowed_hosts),
        approved_references=set(approved_references),
    )
    transport = transport_factory(context)
    store = LocalFileSearch(case_id)
    ingestion = LocalIngestor(store)
    document_map = {}
    table_map = {}
    for target, items in ((document_map, documents or {}), (table_map, tables or {})):
        for name, value in items.items():
            text, media = value if isinstance(value, tuple) else (value, "text/plain")
            version = hashlib.sha256(text.encode()).hexdigest()
            artifact = Artifact(
                Source("case:" + name, public=False), text, version, media
            )
            identifier = ingestion.ingest(
                artifact, case_id=case_id, timeout=30
            ).document_ids[0]
            context.authorized_document_ids.add(identifier)
            target[name] = identifier
    browser = WebBrowser(transport, context, api_key=search_key, cache=cache)
    router = BiofinderAgent(
        context,
        file_search=store,
        browser=browser,
        ingestor=ingestion,
        tables=TableProcessor(store, cache=cache),
        wait=lambda delay: __import__("time").sleep(delay),
    )
    browser.source_policy = router._safe_source
    client = OpenAIClient(
        transport,
        api_key=model_key,
        model=model,
        allow_private_context=allow_model_context,
    )
    investigation = Investigation(
        router,
        client,
        documents=document_map,
        tables=table_map,
        allow_model_context=allow_model_context,
    )
    return investigation, transport


def scenario_investigation(number, cache=None):
    fixture = load_scenario(number)
    investigation, transport = build_investigation(
        case_id="synthetic-" + str(number),
        public_terms=fixture["public_terms"],
        allowed_hosts=("data.example.org",),
        documents=fixture["documents"],
        tables={name: (text, "text/csv") for name, text in fixture["tables"].items()},
        transport_factory=lambda context: FixtureTransport(context, fixture),
        cache=cache,
        model="fixture-model",
        model_key="fixture-only",
        search_key="fixture-only",
        allow_model_context=True,
    )
    return investigation, transport, fixture


def load_document(path):
    """Read a bounded user-selected artifact; PDF text retains page markers."""
    if path.stat().st_size > 25 * 1024 * 1024:
        raise ValueError("Input file too large")
    if path.suffix.lower() == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(path)
        if reader.is_encrypted or len(reader.pages) > 200:
            raise ValueError("Unsupported PDF")
        pages = [page.extract_text() or "" for page in reader.pages]
        if not any(page.strip() for page in pages):
            raise ValueError("OCR is required")
        return (
            "\n".join(f"[page {i+1}]\n" + text for i, text in enumerate(pages)),
            "application/pdf",
        )
    allowed = {
        ".txt": "text/plain",
        ".md": "text/markdown",
        ".json": "application/json",
        ".yaml": "text/plain",
        ".yml": "text/plain",
        ".log": "text/plain",
        ".csv": "text/csv",
        ".tsv": "text/tab-separated-values",
    }
    if path.suffix.lower() not in allowed:
        raise ValueError("Unsupported document type")
    return path.read_text(encoding="utf-8"), allowed[path.suffix.lower()]
