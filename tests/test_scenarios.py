from helpers import OfflineTest, run_case


class ScenarioTests(OfflineTest):
    def test_all_six_cases_use_both_tools_and_real_calculations(self):
        for number in range(1, 7):
            with self.subTest(scenario=number):
                agent, transport, fixture, report = run_case(number)
                self.assertEqual(
                    report["status"], "partial" if number in (4, 6) else "completed"
                )
                self.assertEqual(
                    report["claims"][0]["statement"], fixture["public_text"]
                )
                traces = [item for step in report["steps"] for item in step["trace"]]
                self.assertIn("A3:file_search", traces)
                self.assertIn("A5:browser_search", traces)
                self.assertIn("A4:ingest", traces)
                self.assertEqual(report["api_usage"]["calls"], 2)
                if fixture["expected"]:
                    actual = report["calculations"][0]["result"]
                    for field, value in fixture["expected"].items():
                        self.assertEqual(actual[field], value)
                # Browser only receives preapproved public terms, not model/case text.
                queries = [
                    r["url"]
                    for r in transport.requests
                    if "api.search.brave.com" in r["url"]
                ]
                self.assertEqual(len(queries), 1)
                for claim in report["claims"]:
                    for citation in claim["citations"]:
                        self.assertIn(
                            citation["quote"],
                            report["evidence"][citation["id"]]["text"],
                        )
                if report["criteria"]:
                    self.assertEqual(report["criteria"][0]["status"], "fails")

    def test_restricted_source_does_not_prevent_independent_alternative(self):
        _, transport, _, report = run_case(4)
        self.assertTrue(any("/restricted" in r["url"] for r in transport.requests))
        self.assertEqual(report["status"], "partial")
        self.assertTrue(report["claims"])
        self.assertTrue(report["unresolved"])
