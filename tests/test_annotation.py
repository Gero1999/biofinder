import time
import unittest
from unittest.mock import Mock

from annotation import (AccessDenied, Artifact, BiofinderAgent, CaseContext,
                        Evidence, Ingestion, Request, Source, TransientError, classify_query)
from integration import create_agent


PUBLIC = Source("https://example.org/study")
HIT = Evidence("doc", "page 2", "Study includes paired baseline visits.", "v1")


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.context = CaseContext("case", authorized_document_ids={"doc"},
            approved_public_terms=("human", "melanoma"),
            approved_references={PUBLIC.url}, allowed_hosts={"example.org"})
        self.search = Mock(remote=True)
        self.search.ready.return_value = True
        self.search.search.return_value = (HIT,)
        self.browser = Mock()
        self.browser.search.return_value = (PUBLIC,)
        self.browser.open.return_value = Artifact(PUBLIC, "Study includes paired visits.", "v1")
        self.ingestor = Mock(remote=False)
        self.ingestor.ingest.return_value = Ingestion("case", ("doc",), True)
        self.agent = BiofinderAgent(self.context, file_search=self.search,
            browser=self.browser, ingestor=self.ingestor, wait=lambda _: None)

    def test_ready_document_uses_no_browser(self):
        result = self.agent.route_request(Request("Find baseline visits in this paper", document_ids=("doc",)))
        self.assertEqual(result.evidence, (HIT,))
        self.assertEqual(result.status, "partial")
        self.browser.search.assert_not_called()
        self.browser.open.assert_not_called()

    def test_empty_document_retries_once_then_uses_only_approved_terms(self):
        self.search.search.side_effect = [(), (), (HIT,)]
        result = self.agent.route_request(Request("private subject ALPHA-123", document_ids=("doc",)))
        self.assertTrue(result.evidence)
        self.assertEqual(self.search.search.call_count, 3)
        self.browser.search.assert_called_once()
        self.assertEqual(self.browser.search.call_args.args, ())
        self.assertEqual(self.browser.search.call_args.kwargs["query"], "human melanoma")
        self.assertNotIn("ALPHA-123", repr(result.trace))
        self.ingestor.ingest.assert_called_once()

    def test_contextual_success_skips_web(self):
        self.search.search.side_effect = [(), (HIT,)]
        self.agent.route_request(Request("baseline", document_ids=("doc",)))
        self.assertTrue(self.search.search.call_args.kwargs["contextual"])
        self.browser.search.assert_not_called()

    def test_document_only_miss_never_browses(self):
        self.search.search.return_value = ()
        result = self.agent.route_request(Request("baseline", document_ids=("doc",), document_only=True))
        self.assertEqual(result.status, "partial")
        self.assertIn("do not infer absence", result.message)
        self.browser.search.assert_not_called()

    def test_not_ready_version_does_not_infer_absence_or_search(self):
        self.search.ready.return_value = False
        result = self.agent.route_request(Request("baseline", document_ids=("doc",), version="v2"))
        self.assertIn("not ready", result.message)
        self.search.search.assert_not_called()
        self.browser.search.assert_not_called()

    def test_discovery_opens_ingests_then_searches(self):
        result = self.agent.route_request(Request("Find cohorts"))
        self.assertEqual(result.evidence, (HIT,))
        self.assertLess(result.trace.index("A4:ingest"), result.trace.index("A3:file_search"))

    def test_known_source_opens_without_discovery(self):
        self.agent.route_request(Request("Inspect source", reference=PUBLIC.url))
        self.browser.open.assert_called_once()
        self.browser.search.assert_not_called()

    def test_current_source_cannot_use_stale_index_directly(self):
        self.agent.route_request(Request("Latest terms", document_ids=("doc",), reference=PUBLIC.url, current=True))
        self.assertIn("A6:browser_open", self.context.trace)
        denied = self.agent.route_request(Request("Latest terms", current=True, document_only=True))
        self.assertEqual(denied.status, "blocked")

    def test_no_evidence_does_not_recursively_search_web(self):
        self.search.search.return_value = ()
        result = self.agent.route_request(Request("Find cohorts"))
        self.assertEqual(result.status, "partial")
        self.browser.search.assert_called_once()
        self.browser.open.assert_called_once()
        self.assertEqual(self.search.search.call_count, 2)

    def test_private_missing_source_and_unapproved_handoffs(self):
        result = self.agent.route_request(Request("Read private paper", private_source_missing=True))
        self.assertEqual(result.status, "needs_input")
        self.browser.search.assert_not_called()
        self.context.approved_public_terms = ()
        result = self.agent.route_request(Request("Find ALPHA-123"))
        self.assertEqual(result.route, "sharing")
        result = self.agent.route_request(Request("Inspect source", reference="https://example.org/private"))
        self.assertEqual(result.route, "sharing")
        self.browser.open.assert_not_called()

    def test_cross_case_and_ingestion_scope_denied(self):
        result = self.agent.route_request(Request("baseline", document_ids=("other",)))
        self.assertEqual(result.status, "blocked")
        self.search.ready.assert_not_called()
        self.ingestor.ingest.return_value = Ingestion("other-case", ("secret",), True)
        result = self.agent.route_request(Request("Find cohorts"))
        self.assertEqual(result.status, "blocked")
        self.assertNotIn("secret", self.context.authorized_document_ids)

    def test_pending_ingestion_never_searches(self):
        self.ingestor.ingest.return_value = Ingestion("case", ("doc",), False)
        result = self.agent.route_request(Request("Find cohorts"))
        self.assertEqual(result.route, "ingestion")
        self.search.search.assert_not_called()

    def test_budget_checked_between_tool_steps(self):
        self.context.request_limit = 1
        result = self.agent.route_request(Request("Find cohorts"))
        self.assertEqual(result.status, "partial")
        self.assertEqual(self.context.external_requests, 1)
        self.browser.open.assert_not_called()

    def test_cancellation_and_deadline_start_no_calls(self):
        self.context.cancelled = True
        self.assertEqual(self.agent.route_request(Request("Find cohorts")).status, "cancelled")
        self.context.cancelled = False
        self.context.deadline = time.monotonic() - 1
        self.assertEqual(self.agent.route_request(Request("Find cohorts")).route, "guard")
        self.browser.search.assert_not_called()

    def test_late_cancelled_result_is_not_accepted(self):
        def cancel(**kwargs):
            self.context.cancelled = True
            return (PUBLIC,)
        self.browser.search.side_effect = cancel
        result = self.agent.route_request(Request("Find cohorts"))
        self.assertEqual(result.status, "cancelled")
        self.assertFalse(result.leads)
        self.browser.open.assert_not_called()

    def test_only_transient_errors_retry(self):
        self.browser.search.side_effect = [TransientError(), TransientError(), (PUBLIC,)]
        self.agent.route_request(Request("Find cohorts"))
        self.assertEqual(self.browser.search.call_count, 3)
        self.browser.search.reset_mock(side_effect=True)
        self.browser.search.side_effect = AccessDenied()
        self.assertEqual(self.agent.route_request(Request("Find cohorts")).status, "blocked")
        self.assertEqual(self.browser.search.call_count, 1)

    def test_calculation_requires_complete_inputs_and_adapter(self):
        result = self.agent.route_request(Request("Recount donors", table_ids=("doc",)))
        self.assertEqual(result.status, "needs_input")
        tables = Mock()
        tables.calculate.return_value = (HIT,)
        self.agent.tables = tables
        result = self.agent.route_request(Request("Recount donors", table_ids=("doc",), definitions_verified=True))
        self.assertEqual(result.route, "calculation")
        self.assertEqual(result.evidence, (HIT,))
        self.browser.search.assert_not_called()

    def test_url_credentials_signed_links_and_private_destinations_rejected(self):
        for url in ["https://user:pass@example.org/x", "https://example.org/x?X-Goog-Signature=abc",
                    "http://127.0.0.1/x", "https://[invalid", "file:///tmp/private"]:
            with self.subTest(url=url):
                self.context.approved_references.add(url)
                result = self.agent.route_request(Request("Inspect source", reference=url))
                self.assertEqual(result.status, "blocked")
        self.browser.open.assert_not_called()

    def test_explicit_scope_and_intake_failures(self):
        for request in [Request("Find cohorts", permitted=False), Request(""),
                        Request("Find cohorts", missing_information=("organism",)), Request("Hello")]:
            with self.subTest(request=request):
                self.assertIn(self.agent.route_request(request).status, {"needs_input", "blocked"})
        self.browser.search.assert_not_called()

    def test_local_starter_returns_real_cited_text_without_network(self):
        agent = create_agent(case_id="demo")
        artifact = Artifact(Source("local:methods", public=False), "Methods\nPaired baseline biopsies from 30 donors.", "v1")
        indexed = agent.ingestor.ingest(artifact, case_id="demo", timeout=30)
        agent.context.authorized_document_ids.update(indexed.document_ids)
        result = agent.route_request(Request("baseline donors", document_ids=indexed.document_ids, document_only=True))
        self.assertIn("30 donors", result.evidence[0].text)
        self.assertIn("lines", result.evidence[0].location)
        self.assertEqual(agent.context.external_requests, 0)
        self.assertIn("validation", result.message)


    def test_requested_source_version_is_not_silently_replaced(self):
        result = self.agent.route_request(Request("Inspect source", reference=PUBLIC.url, version="v2"))
        self.assertEqual(result.route, "source")
        self.assertIn("does not match", result.message)
        self.ingestor.ingest.assert_not_called()

    def test_document_only_discovery_searches_local_corpus(self):
        result = self.agent.route_request(Request("Find relevant studies", intent="discovery",
            document_ids=("doc",), document_only=True))
        self.assertEqual(result.evidence, (HIT,))
        self.browser.search.assert_not_called()

    def test_freshness_reference_does_not_use_unapproved_fallback(self):
        self.context.approved_references.clear()
        result = self.agent.route_request(Request("Current access", reference=PUBLIC.url, current=True))
        self.assertEqual(result.status, "needs_input")
        self.browser.search.assert_not_called()
        self.browser.open.assert_not_called()


    def test_auto_freshness_cannot_silently_use_document_only_copy(self):
        result = self.agent.route_request(Request("Are the current terms compatible?",
            document_ids=("doc",), document_only=True))
        self.assertEqual(result.route, "freshness")
        self.assertEqual(result.status, "blocked")
        self.search.search.assert_not_called()
        self.browser.search.assert_not_called()


    def test_classifier_is_explicit_and_does_not_call_tools(self):
        cases = [
            (Request("Find melanoma datasets"), "discovery"),
            (Request("What does this protocol say?"), "documents"),
            (Request("Inspect this source", reference=PUBLIC.url), "source"),
            (Request("Recount donors"), "calculation"),
            (Request("Find methods", document_ids=("doc",)), "documents"),
            (Request("Latest methods", document_ids=("doc",)), "discovery"),
            (Request("Find alternatives", intent="documents"), "documents"),
            (Request("Hello"), None),
        ]
        for request, expected in cases:
            with self.subTest(query=request.query):
                self.assertEqual(classify_query(request), expected)
        self.browser.search.assert_not_called()
        self.search.search.assert_not_called()


if __name__ == "__main__":
    unittest.main()
