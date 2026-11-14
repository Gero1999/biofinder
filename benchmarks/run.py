"""Measure synthetic cold/warm runs without network access or API expenditure."""

import argparse
from contextlib import ExitStack
import json
import math
from pathlib import Path
import statistics
import time
from unittest.mock import patch

from cache import ExactCache
from runtime import scenario_investigation


def summarize(samples):
    durations = sorted(sample["seconds"] for sample in samples)
    return {
        "runs": len(samples),
        "median_ms": round(statistics.median(durations) * 1000, 3),
        "p95_ms": round(durations[math.ceil(len(durations) * 0.95) - 1] * 1000, 3),
        "external_requests_per_run": sorted({sample["requests"] for sample in samples}),
        "model_calls_per_run": sorted({sample["model_calls"] for sample in samples}),
    }


def measure(number, cache):
    started = time.perf_counter()
    agent, transport, fixture = scenario_investigation(number, cache)
    report = agent.run(fixture["query"], requirements=fixture["requirements"])
    elapsed = time.perf_counter() - started
    if report["status"] not in {"completed", "partial"} or not report["claims"]:
        raise RuntimeError("Scenario did not produce validated fixture claims")
    return {
        "seconds": elapsed,
        "requests": transport.calls,
        "model_calls": report["api_usage"]["calls"],
    }, report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=30)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.runs < 1:
        parser.error("--runs must be positive")
    results = []
    with ExitStack() as guards:
        for target in (
            "socket.socket.connect",
            "socket.socket.connect_ex",
            "socket.socket.sendto",
            "socket.getaddrinfo",
        ):
            guards.enter_context(
                patch(
                    target, side_effect=AssertionError("Network forbidden in benchmark")
                )
            )
        for number in range(1, 7):
            cold, warm = [], []
            for _ in range(args.runs):
                cache = ExactCache()
                sample, first = measure(number, cache)
                cold.append(sample)
                sample, second = measure(number, cache)
                warm.append(sample)
                for field in ("status", "claims", "calculations", "criteria"):
                    if first[field] != second[field]:
                        raise AssertionError("Cache changed fixture findings")
            results.append(
                {"scenario": number, "cold": summarize(cold), "warm": summarize(warm)}
            )
    report = {
        "execution_mode": "fixture",
        "paid_api_calls": 0,
        "note": "Local synthetic latency only; mocked token usage is not a cost estimate or live SLA.",
        "scenarios": results,
    }
    rendered = json.dumps(report, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
