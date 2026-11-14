"""Predefined synthetic API responses; no network, paid calls or actual datasets."""

import json
import time
from pathlib import Path
from urllib.parse import urlsplit

from annotation import AccessDenied, BudgetExceeded, Cancelled, ToolError


def load_scenario(number):
    if str(number) not in {str(i) for i in range(1, 7)}:
        raise ValueError("Choose scenario 1-6")
    return json.loads(
        (
            Path(__file__).parent / "tests" / "fixtures" / f"scenario_{number}.json"
        ).read_text()
    )


class FixtureTransport:
    """Exercise real client parsing using canned provider-level response envelopes."""

    mode = "fixture"

    def __init__(self, context, fixture):
        self.context, self.fixture = context, fixture
        self.calls = 0
        self.requests = []

    def send(
        self,
        method,
        url,
        *,
        headers=None,
        body=None,
        timeout=30,
        max_bytes=25 * 1024 * 1024,
    ):
        if self.context.cancelled:
            raise Cancelled()
        if (
            self.context.external_requests >= self.context.request_limit
            or time.monotonic() >= self.context.deadline
        ):
            raise BudgetExceeded()
        self.context.external_requests += 1
        self.calls += 1
        # Do not record auth headers or model request bodies in routine mock traces.
        self.requests.append({"method": method, "url": url})
        if url == "https://api.openai.com/v1/chat/completions":
            request = json.loads(body)
            instruction = request["messages"][0]["content"]
            stage = (
                "plan"
                if instruction.startswith("You plan")
                else (
                    "calculation"
                    if instruction.startswith("Return JSON with calculation")
                    else "synthesis"
                )
            )
            response = {
                "choices": [
                    {"message": {"content": json.dumps(self.fixture["model"][stage])}}
                ],
                "usage": {"prompt_tokens": 100, "completion_tokens": 50},
            }
            return (
                200,
                {"content-type": "application/json"},
                json.dumps(response).encode(),
            )
        if urlsplit(url).hostname == "api.search.brave.com":
            response = {
                "web": {
                    "results": [
                        {"url": u, "title": "Synthetic study"}
                        for u in self.fixture["sources"]
                    ]
                }
            }
            return (
                200,
                {"content-type": "application/json"},
                json.dumps(response).encode(),
            )
        if url.endswith("/restricted"):
            raise AccessDenied()
        if url in self.fixture["sources"]:
            return (
                200,
                {"content-type": "text/html"},
                ("<p>" + self.fixture["public_text"] + "</p>").encode(),
            )
        raise ToolError("No predefined response for this request")
