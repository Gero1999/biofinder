import json
from unittest.mock import Mock, patch

from helpers import OfflineTest
from annotation import AccessDenied, Artifact, CaseContext, Source, ToolError
from api_client import HTTPTransport, OpenAIClient
from cache import ExactCache
from runtime import scenario_investigation
from table_processing import TableProcessor


class CacheTests(OfflineTest):
    def test_ttl_and_eviction(self):
        now = [0]
        cache = ExactCache(2, clock=lambda: now[0])
        cache.put(("A",), 1, 10)
        cache.put(("B",), 2, 10)
        self.assertEqual(cache.get(("A",)), 1)
        cache.put(("C",), 3, 10)
        self.assertIsNone(cache.get(("B",)))
        now[0] = 11
        self.assertIsNone(cache.get(("A",)))
        cache.invalidate()
        self.assertFalse(cache.entries)

    def test_calculation_cache_rechecks_scope_and_inputs(self):
        agent, _, fixture = scenario_investigation(1)
        processor = agent.router.tables
        processor.cache = ExactCache()
        ids = tuple(agent.tables.values())
        args = dict(
            case_id=agent.router.context.case_id,
            timeout=30,
            specification={"operation": "count_distinct", "column": "donor_id"},
        )
        first = processor.calculate("", ids, **args)
        self.assertEqual(processor.calculate("", ids, **args), first)
        self.assertEqual(processor.cache.hits, 1)
        del processor.store.documents[ids[0]]
        with self.assertRaises(AccessDenied):
            processor.calculate("", ids, **args)


class APIClientTests(OfflineTest):
    def test_real_client_parses_predefined_provider_response(self):
        transport = Mock()
        transport.send.return_value = (
            200,
            {},
            json.dumps(
                {
                    "choices": [{"message": {"content": '{"steps": []}'}}],
                    "usage": {"prompt_tokens": 12, "completion_tokens": 3},
                }
            ).encode(),
        )
        client = OpenAIClient(
            transport, api_key="test", model="test", allow_private_context=True
        )
        self.assertEqual(
            client.complete("plan", {"query": "public question"}), {"steps": []}
        )
        self.assertEqual((client.input_tokens, client.output_tokens), (12, 3))
        sent = json.loads(transport.send.call_args.kwargs["body"])
        self.assertEqual(sent["response_format"]["type"], "json_object")

    def test_model_requires_explicit_processing_approval(self):
        transport = Mock()
        client = OpenAIClient(transport, api_key="test", model="test")
        with self.assertRaises(AccessDenied):
            client.complete("plan", {})
        transport.send.assert_not_called()

    def test_malformed_model_json_is_not_a_result(self):
        transport = Mock()
        transport.send.return_value = (200, {}, b'{"choices": []}')
        client = OpenAIClient(
            transport, api_key="test", model="test", allow_private_context=True
        )
        with self.assertRaises(ToolError):
            client.complete("plan", {})

    def test_public_destination_checks_reject_private_resolution(self):
        transport = HTTPTransport(CaseContext("test"))
        with patch(
            "socket.getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", 443))]
        ):
            with self.assertRaises(AccessDenied):
                transport.validate_public_destination("https://example.org")


class ValidationTests(OfflineTest):
    def test_invalid_numeric_criteria_are_rejected_before_api_calls(self):
        agent, transport, fixture = scenario_investigation(1)
        for criterion in [
            None,
            {},
            {
                "minimum": float("nan"),
                "operation": "count_distinct",
                "field": "distinct",
            },
        ]:
            with self.assertRaises(ValueError):
                agent.run(fixture["query"], requirements={"criteria": [criterion]})
        self.assertEqual(transport.calls, 0)

    def test_fabricated_citation_and_unsupported_statement_are_rejected(self):
        agent, _, fixture = scenario_investigation(1)
        original = fixture["model"]["synthesis"]["claims"][0]
        for field, value in [("id", "invented"), ("quote", "invented claim")]:
            agent, _, fixture = scenario_investigation(1)
            fixture["model"]["synthesis"]["claims"][0]["citations"][0][field] = value
            report = agent.run(fixture["query"])
            self.assertEqual(report["status"], "partial")
            self.assertEqual(report["claims"], [])
        agent, _, fixture = scenario_investigation(1)
        fixture["model"]["synthesis"]["claims"][0][
            "statement"
        ] = "Commercial reuse is unrestricted."
        report = agent.run(fixture["query"])
        self.assertEqual(report["claims"], [])

    def test_unknown_columns_and_invalid_operations_fail_closed(self):
        agent, _, fixture = scenario_investigation(1)
        processor = agent.router.tables
        ids = tuple(agent.tables.values())
        for spec in [
            {"operation": "count_distinct", "column": "unknown"},
            {"operation": "exec", "code": "arbitrary"},
        ]:
            with self.assertRaises(ToolError):
                processor.calculate(
                    "",
                    ids,
                    case_id=agent.router.context.case_id,
                    timeout=1,
                    specification=spec,
                )

    def test_row_limit_and_missing_values(self):
        agent, _, fixture = scenario_investigation(1)
        agent.router.tables.max_rows = 10
        report = agent.run(fixture["query"])
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["calculations"], [])

    def test_invalid_table_arity_and_nonfinite_window_are_rejected(self):
        agent, _, _ = scenario_investigation(1)
        ids = tuple(agent.tables.values())
        for tables, spec in [
            (ids * 2, {"operation": "count_distinct", "column": "donor_id"}),
            (
                ids,
                {"operation": "baseline", "column": "donor_id", "lower": float("inf")},
            ),
        ]:
            with self.assertRaises(ToolError):
                agent.router.tables.calculate(
                    "",
                    tables,
                    case_id=agent.router.context.case_id,
                    timeout=1,
                    specification=spec,
                )

    def test_unsupported_or_overlong_plans_start_no_tools(self):
        agent, transport, fixture = scenario_investigation(1)
        fixture["model"]["plan"]["steps"] *= 4
        report = agent.run(fixture["query"])
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(len(transport.requests), 1)
