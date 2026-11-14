"""End-to-end CLI. Mock scenarios are free; --live is an explicit opt-in."""

import argparse
import json
import os
from config import load_env, csv_setting
from pathlib import Path

from runtime import build_investigation, scenario_investigation, load_document


def markdown(report):
    lines = ["# Biofinder findings", "", f"Status: {report['status']}", ""]
    for claim in report["claims"]:
        ids = ", ".join(c["id"] for c in claim["citations"])
        lines.append(f"- {claim['statement']} [{ids}]")
    if report["calculations"]:
        lines += [
            "",
            "## Calculations",
            "",
            "```json",
            json.dumps(report["calculations"], indent=2),
            "```",
        ]
    if report["unresolved"]:
        lines += ["", "## Unresolved", ""] + [
            "- " + item for item in report["unresolved"]
        ]
    lines += ["", "## Evidence", ""]
    for key, evidence in report["evidence"].items():
        lines.append(
            f"- {key}: {evidence.get('source_url',evidence['source_id'])}, {evidence['location']}, version {evidence['version']}"
        )
    return "\n".join(lines)


def main(argv=None):
    try:
        load_env()
    except (OSError, UnicodeError, ValueError) as error:
        raise SystemExit(
            "Check the local .env syntax; configuration values were withheld"
        ) from None
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--scenario", type=int, choices=range(1, 7))
    mode.add_argument("--live", action="store_true")
    parser.add_argument("--query")
    parser.add_argument("--document", action="append", type=Path, default=[])
    parser.add_argument("--table", action="append", type=Path, default=[])
    parser.add_argument(
        "--public-term", action="append", default=csv_setting("BIOFINDER_PUBLIC_TERMS")
    )
    parser.add_argument(
        "--allowed-host",
        action="append",
        default=csv_setting("BIOFINDER_ALLOWED_HOSTS"),
    )
    parser.add_argument("--reference", action="append", default=[])
    parser.add_argument("--allow-model-context", action="store_true")
    parser.add_argument("--format", choices=["json", "markdown"], default="json")
    args = parser.parse_args(argv)
    if args.scenario:
        investigation, _, fixture = scenario_investigation(args.scenario)
        report = investigation.run(
            fixture["query"], requirements=fixture["requirements"]
        )
    else:
        if not args.query or not args.allow_model_context:
            parser.error("--live requires --query and explicit --allow-model-context")
        try:
            if len({p.stem for p in args.document + args.table}) != len(
                args.document + args.table
            ):
                parser.error("Input names must be unique")
            documents = {p.stem: load_document(p) for p in args.document}
            tables = {p.stem: load_document(p) for p in args.table}
            investigation, _ = build_investigation(
                case_id=__import__("uuid").uuid4().hex,
                public_terms=args.public_term,
                allowed_hosts=args.allowed_host,
                approved_references=args.reference,
                documents=documents,
                tables=tables,
                allow_model_context=True,
            )
        except (OSError, UnicodeError, ValueError):
            parser.error("Check UTF-8 inputs and secure API configuration")
        try:
            request_limit = int(os.environ.get("BIOFINDER_REQUEST_LIMIT", "30"))
            model_limit = int(os.environ.get("BIOFINDER_MODEL_CALL_LIMIT", "8"))
            if not 1 <= request_limit <= 1000 or not 1 <= model_limit <= 100:
                raise ValueError()
        except ValueError:
            parser.error("Invalid request/model budget")
        investigation.router.context.request_limit = request_limit
        investigation.max_model_calls = model_limit
        report = investigation.run(args.query)
    print(
        markdown(report) if args.format == "markdown" else json.dumps(report, indent=2)
    )
    return 0 if report["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
