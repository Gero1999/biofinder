import contextlib
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from helpers import OfflineTest, run_case
from annotation import AccessDenied, Source, TransientError
from agent_cli import main
from cache import ExactCache
from config import load_env
from runtime import scenario_investigation, load_document


class IntegrationTests(OfflineTest):
    def test_transient_model_retry_and_request_budget_preserve_partial_evidence(self):
        agent, transport, fixture = scenario_investigation(1)
        original = transport.send
        failed = [False]

        def send(method, url, **kwargs):
            result = original(method, url, **kwargs)
            if method == "POST" and not failed[0]:
                failed[0] = True
                raise TransientError(0)
            return result

        transport.send = send
        agent.router.wait = lambda _: None
        agent.router.context.request_limit = 4
        report = agent.run(fixture["query"])
        self.assertEqual(transport.calls, 4)
        self.assertEqual(report["status"], "partial")
        self.assertTrue(report["evidence"])
        self.assertFalse(report["claims"])

    def test_cli_demo_and_markdown_are_offline(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["--scenario", "1"]), 0)
        report = json.loads(output.getvalue())
        self.assertEqual(report["calculations"][0]["result"]["distinct"], 18)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["--scenario", "4", "--format", "markdown"]), 2)
        self.assertIn("Commercial reuse", output.getvalue())
        self.assertIn("https://data.example.org/", output.getvalue())

    def test_cache_reuse_then_freshness_and_scope_changes(self):
        cache = ExactCache()
        _, cold, _, first = run_case(1, cache)
        agent, warm, fixture, second = run_case(1, cache)
        self.assertEqual(cold.calls, 4)
        self.assertEqual(warm.calls, 2)  # Two model calls remain; no cached answers.
        self.assertEqual(first["claims"], second["claims"])
        agent, transport, fixture = scenario_investigation(1, cache)
        fixture["model"]["plan"]["steps"][1]["current"] = True
        fresh = agent.run(fixture["query"])
        self.assertEqual(transport.calls, 4)
        agent.router.context.allowed_hosts.clear()
        with self.assertRaises(AccessDenied):
            agent.router.browser.open(Source(fixture["sources"][0]), timeout=1)

    def test_revocation_during_synthesis_cannot_leave_cited_private_claims(self):
        agent, transport, fixture = scenario_investigation(1)
        original = transport.send

        def send(method, url, **kwargs):
            response = original(method, url, **kwargs)
            if method == "POST" and json.loads(kwargs["body"])["messages"][0][
                "content"
            ].startswith("Return JSON"):
                agent.router.context.authorized_document_ids.clear()
            return response

        transport.send = send
        report = agent.run(fixture["query"])
        self.assertFalse(report["claims"])
        self.assertFalse(report["evidence"])
        self.assertFalse(report["calculations"])

    def test_resume_after_cancellation_retains_validated_steps(self):
        agent, transport, fixture = scenario_investigation(1)
        fired = [False]

        def progress(event):
            if event["stage"] == "A5:browser_search" and not fired[0]:
                fired[0] = True
                agent.router.context.cancelled = True

        agent.router.progress = progress
        first = agent.run(fixture["query"])
        self.assertEqual(first["status"], "cancelled")
        self.assertEqual(first["next_step"], 1)
        first_steps = deepcopy(first["steps"])
        agent.router.context.cancelled = False
        agent.router.progress = None
        resumed = agent.run(fixture["query"], resume=True)
        self.assertEqual(resumed["status"], "completed")
        self.assertEqual(first["steps"], first_steps)
        with self.assertRaises(ValueError):
            agent.run(fixture["query"], requirements={"changed": True}, resume=True)

    def test_calculation_is_resolved_after_document_definitions_are_retrieved(self):
        agent, transport, fixture = scenario_investigation(1)
        step = fixture["model"]["plan"]["steps"][-1]
        fixture["model"]["calculation"] = {
            "calculation": step.pop("calculation"),
            "definition_quote": step.pop("definition_quote"),
        }
        report = agent.run(fixture["query"], requirements=fixture["requirements"])
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["calculations"][0]["result"]["distinct"], 18)
        self.assertEqual(report["api_usage"]["calls"], 3)
        self.assertEqual(transport.calls, 5)

    def test_dotenv_preserves_injected_environment_and_never_executes_shell(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text(
                'OPENAI_API_KEY="test-only"\nBIOFINDER_MODEL="$(touch forbidden)"\n'
            )
            with patch.dict(
                "os.environ", {"OPENAI_API_KEY": "injected-test"}, clear=True
            ):
                load_env(path)
                import os

                self.assertEqual(os.environ["OPENAI_API_KEY"], "injected-test")
                self.assertEqual(os.environ["BIOFINDER_MODEL"], "$(touch forbidden)")
            self.assertFalse((Path(directory) / "forbidden").exists())

    def test_pdf_text_and_unreadable_pdf(self):
        from pypdf import PdfWriter
        from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "study.pdf"
            writer = PdfWriter()
            page = writer.add_blank_page(width=200, height=200)
            font = DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/Type1"),
                    NameObject("/BaseFont"): NameObject("/Helvetica"),
                }
            )
            page[NameObject("/Resources")] = DictionaryObject(
                {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
            )
            stream = DecodedStreamObject()
            stream.set_data(
                b"BT /F1 12 Tf 10 100 Td (Synthetic study has 18 donors.) Tj ET"
            )
            page[NameObject("/Contents")] = writer._add_object(stream)
            writer.write(path)
            text, media = load_document(path)
            self.assertIn("18 donors", text)
            self.assertIn("[page 1]", text)
            writer = PdfWriter()
            writer.add_blank_page(width=200, height=200)
            writer.write(path)
            with self.assertRaises(ValueError):
                load_document(path)
