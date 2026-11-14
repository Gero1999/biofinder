"""Runnable starter integration; production browser/file_search remain injectable.

The local example performs lexical lookup of UTF-8 text, not semantic retrieval,
PDF parsing, scientific synthesis, or a complete implementation of the design.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re
import uuid

from annotation import (AccessDenied, Artifact, BiofinderAgent, Browser, CaseContext,
                        Evidence, Ingestion, Request, Source, ToolError)


class LocalFileSearch:
    """One-case demonstration store. Production adapters must enforce real ACLs."""
    remote = False

    def __init__(self, case_id: str):
        self.case_id = case_id
        self.documents: dict[str, Artifact] = {}

    def _scope(self, case_id: str) -> None:
        if case_id != self.case_id:
            raise AccessDenied()

    def register(self, artifact: Artifact, *, case_id: str) -> str:
        self._scope(case_id)
        if artifact.media_type not in {"text/plain", "text/markdown", "text/html", "text/csv", "text/tab-separated-values", "application/json", "application/pdf"}:
            raise ToolError()
        if len(artifact.text.encode("utf-8")) > 25 * 1024 * 1024:
            raise ToolError()
        digest = hashlib.sha256((case_id + artifact.source.url + artifact.text).encode()).hexdigest()
        document_id = "doc_" + digest[:20]
        self.documents[document_id] = artifact
        return document_id

    def ready(self, ids: tuple[str, ...], *, case_id: str, version: str | None,
              timeout: float) -> bool:
        self._scope(case_id)
        return bool(ids) and all(i in self.documents and
            (version is None or self.documents[i].version == version) for i in ids)

    def search(self, query: str, ids: tuple[str, ...], *, case_id: str,
               version: str | None, contextual: bool, timeout: float) -> tuple[Evidence, ...]:
        self._scope(case_id)
        if not self.ready(ids, case_id=case_id, version=version, timeout=timeout):
            raise ToolError()
        stopwords = {"the", "this", "that", "with", "from", "what", "which", "were", "does", "find"}
        terms = set(re.findall(r"[\w-]+", query.lower())) - stopwords
        terms = {term for term in terms if len(term) > 2}
        hits: list[tuple[int, Evidence]] = []
        for document_id in ids:
            artifact = self.documents[document_id]
            lines = artifact.text.splitlines()
            for index, line in enumerate(lines):
                score = len(terms.intersection(re.findall(r"[\w-]+", line.lower())))
                if score:
                    margin = 3 if contextual else 1
                    start, end = max(0, index - margin), min(len(lines), index + margin + 1)
                    hits.append((score, Evidence(document_id, f"lines {start + 1}-{end}",
                        "\n".join(lines[start:end]), artifact.version)))
        hits.sort(key=lambda hit: hit[0], reverse=True)
        unique: dict[tuple[str, str], Evidence] = {}
        for _, evidence in hits:
            unique.setdefault((evidence.source_id, evidence.location), evidence)
        return tuple(list(unique.values())[:3])


class LocalIngestor:
    remote = False

    def __init__(self, store: LocalFileSearch):
        self.store = store

    def ingest(self, artifact: Artifact, *, case_id: str, timeout: float) -> Ingestion:
        document_id = self.store.register(artifact, case_id=case_id)
        return Ingestion(case_id, (document_id,), ready=True)


def create_agent(*, case_id: str | None = None, browser: Browser | None = None,
                 public_terms: tuple[str, ...] = (), allowed_hosts: set[str] | None = None,
                 approved_references: set[str] | None = None) -> BiofinderAgent:
    """Wire a local demonstration or inject a real, policy-enforcing browser.

    A production FileSearch/Ingestor implementation can be passed directly to
    BiofinderAgent instead. Browser implementations must enforce redirect/DNS
    restrictions, transport timeouts, and their provider's actual tool schema.
    """
    case_id = case_id or str(uuid.uuid4())
    context = CaseContext(case_id, approved_public_terms=public_terms,
                          allowed_hosts=set(allowed_hosts or ()),
                          approved_references=set(approved_references or ()))
    search = LocalFileSearch(case_id)
    return BiofinderAgent(context, file_search=search, browser=browser,
                          ingestor=LocalIngestor(search))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Biofinder starter: route one evidence gap.")
    parser.add_argument("query")
    parser.add_argument("--document", action="append", type=Path, default=[])
    parser.add_argument("--intent", choices=["auto", "documents", "discovery", "source", "calculation"], default="auto")
    parser.add_argument("--document-only", action="store_true")
    parser.add_argument("--current", action="store_true")
    parser.add_argument("--public-term", action="append", default=[])
    args = parser.parse_args(argv)
    agent = create_agent(public_terms=tuple(args.public_term))
    ids = []
    for path in args.document:
        if path.suffix.lower() not in {".md", ".txt"}:
            parser.error("The local demo supports .md and .txt files only.")
        try:
            if path.stat().st_size > 25 * 1024 * 1024:
                parser.error("Document exceeds the 25 MiB demo limit.")
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            parser.error("Could not read the supplied UTF-8 document.")
        version = hashlib.sha256(text.encode()).hexdigest()
        artifact = Artifact(Source(path.resolve().as_uri(), public=False), text, version)
        indexed = agent.ingestor.ingest(artifact, case_id=agent.context.case_id, timeout=30)
        ids.extend(indexed.document_ids)
    agent.context.authorized_document_ids.update(ids)
    outcome = agent.route_request(Request(args.query, intent=args.intent, document_ids=tuple(ids),
        document_only=args.document_only, current=args.current))
    print(json.dumps(asdict(outcome), ensure_ascii=False, indent=2))
    return 0 if outcome.evidence else 2


if __name__ == "__main__":
    raise SystemExit(main())
