"""Brave Search plus bounded public HTML/text retrieval; all transport is injectable."""

import json
import os
from html.parser import HTMLParser
from urllib.parse import urlencode, urljoin, urlsplit

from annotation import AccessDenied, Artifact, Source, ToolError
from cache import ExactCache


class ReadableHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hidden = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag in {"p", "div", "br", "tr", "h1", "h2", "li"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


class WebBrowser:
    accounts_requests = True

    def __init__(self, transport, context, *, api_key=None, cache=None):
        self.transport, self.context = transport, context
        self.api_key = api_key or os.environ.get("BRAVE_SEARCH_API_KEY")
        self.cache = cache or ExactCache()
        self.source_policy = None  # Set by runtime to the router's public URL policy.

    def _scope(self):
        return (
            self.context.case_id,
            tuple(sorted(self.context.allowed_hosts)),
            tuple(sorted(self.context.approved_references)),
            self.context.approved_public_terms,
        )

    def search(self, query, *, timeout):
        if not self.api_key:
            raise ToolError("Configure a browser search provider")
        key = ("search", self._scope(), query)
        cached = None if self.context.force_refresh else self.cache.get(key)
        if cached is not None:
            return cached
        status, _, body = self.transport.send(
            "GET",
            "https://api.search.brave.com/res/v1/web/search?"
            + urlencode({"q": query, "count": 3}),
            headers={"X-Subscription-Token": self.api_key},
            timeout=timeout,
        )
        if status != 200:
            raise ToolError("Search failed")
        try:
            data = json.loads(body)
            results = tuple(
                Source(item["url"], item.get("title", ""))
                for item in data.get("web", {}).get("results", [])
            )
        except (ValueError, TypeError, KeyError):
            raise ToolError("Malformed search response") from None
        # Cache only policy-accepted public results, never raw model/case answers.
        results = tuple(
            s for s in results if self.source_policy and self.source_policy(s)
        )
        self.cache.put(key, results, 30)
        return results

    def open(self, source, *, timeout):
        if not self.source_policy or not self.source_policy(source):
            raise AccessDenied()
        key = ("artifact", self._scope(), source.url)
        cached = None if self.context.force_refresh else self.cache.get(key)
        if cached is not None:
            return cached
        current = source
        for redirect in range(4):
            if not self.source_policy(current):
                raise AccessDenied()
            validator = getattr(self.transport, "validate_public_destination", None)
            if validator:
                validator(current.url)
            status, headers, body = self.transport.send(
                "GET", current.url, timeout=timeout
            )
            headers = {k.lower(): v for k, v in headers.items()}
            if 300 <= status < 400:
                location = headers.get("location")
                if not location:
                    raise ToolError("Redirect missing destination")
                current = Source(urljoin(current.url, location), source.title)
                continue
            if status != 200:
                raise ToolError("Source unavailable")
            media = headers.get("content-type", "text/plain").split(";")[0]
            if media == "application/pdf":
                try:
                    import io
                    from pypdf import PdfReader

                    reader = PdfReader(io.BytesIO(body))
                    if reader.is_encrypted or len(reader.pages) > 200:
                        raise ToolError("Unsupported PDF")
                    pages = [page.extract_text() or "" for page in reader.pages]
                    if not any(page.strip() for page in pages):
                        raise ToolError("OCR required")
                    text = "\n".join(
                        f"[page {i+1}]\n" + page for i, page in enumerate(pages)
                    )
                except ImportError:
                    raise ToolError("Install the PDF extra to read PDFs") from None
                except ToolError:
                    raise
                except Exception:
                    raise ToolError("PDF extraction failed") from None
            elif media in {
                "text/html",
                "text/plain",
                "text/markdown",
                "text/csv",
                "text/tab-separated-values",
                "application/json",
            }:
                try:
                    text = body.decode("utf-8")
                except UnicodeError:
                    raise ToolError("Unsupported text encoding") from None
                if media == "text/html":
                    parser = ReadableHTML()
                    parser.feed(text)
                    text = "".join(parser.parts)
            else:
                raise ToolError("Unsupported source format")
            import hashlib

            artifact = Artifact(current, text, hashlib.sha256(body).hexdigest(), media)
            self.cache.put(key, artifact, 600)
            return artifact
        raise ToolError("Redirect limit exceeded")
