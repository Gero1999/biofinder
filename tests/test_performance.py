"""Cheap offline regression gates; these are not live provider SLA measurements."""

import time

from helpers import OfflineTest, run_case
from annotation import Artifact, Source
from cache import ExactCache
from runtime import scenario_investigation


class PerformanceTests(OfflineTest):
    def test_warm_runs_avoid_upstream_tools_without_changing_answers(self):
        cache = ExactCache()
        _, cold, _, baseline = run_case(1, cache)
        durations = []
        calls = []
        for _ in range(30):
            started = time.perf_counter()
            _, transport, _, report = run_case(1, cache)
            durations.append(time.perf_counter() - started)
            calls.append(transport.calls)
            self.assertEqual(report["claims"], baseline["claims"])
            self.assertEqual(report["calculations"], baseline["calculations"])
        self.assertEqual(cold.calls, 4)
        self.assertTrue(all(n == 2 for n in calls))
        self.assertLess(sorted(durations)[28], 1.0)  # generous local regression bound

    def test_100000_row_count_with_complete_input(self):
        agent, _, fixture = scenario_investigation(1)
        artifact = Artifact(
            Source("case:large", public=False),
            "donor_id\n" + "".join(f"D{i%1000}\n" for i in range(100000)),
            media_type="text/csv",
        )
        identifier = agent.router.ingestor.ingest(
            artifact, case_id=agent.router.context.case_id, timeout=30
        ).document_ids[0]
        agent.router.context.authorized_document_ids.add(identifier)
        start = time.perf_counter()
        evidence = agent.router.tables.calculate(
            "",
            (identifier,),
            case_id=agent.router.context.case_id,
            timeout=5,
            specification={"operation": "count_distinct", "column": "donor_id"},
        )
        import json

        self.assertEqual(json.loads(evidence[0].text)["result"]["distinct"], 1000)
        self.assertLess(time.perf_counter() - start, 5.0)
