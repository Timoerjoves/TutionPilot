"""The scenario runner: 25 scenarios, every Chandan scenario passes, nothing pending is counted as a pass."""
import json
import tempfile
import unittest
from pathlib import Path

from scenarios import runner


class TestScenarioRunner(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = runner.run()
        cls.by_id = {r["id"]: r for r in cls.report["scenarios"]}

    def test_all_25_scenarios_present(self):
        self.assertEqual(self.report["total"], 25)
        self.assertEqual(len(self.by_id), 25)

    def test_no_failures(self):
        failed = [(r["id"], r["actual"]) for r in self.report["scenarios"] if r["status"] == "FAIL"]
        self.assertEqual(failed, [])

    def test_every_chandan_scenario_passes(self):
        for r in self.report["scenarios"]:
            if r["owner"] == "Chandan":
                with self.subTest(scenario=r["id"]):
                    self.assertEqual(r["status"], "PASS", r["actual"])

    def test_unbuilt_parts_are_pending_not_passed(self):
        for sid in ("B1", "B2", "B3", "B4", "B5", "B6", "C6", "C7", "D2"):
            self.assertEqual(self.by_id[sid]["status"], "PENDING")

    def test_verify_rows_marked(self):
        self.assertTrue(self.by_id["A5"]["verify"])
        self.assertTrue(self.by_id["A6"]["verify"])

    def test_report_files_written(self):
        with tempfile.TemporaryDirectory() as d:
            runner.write(self.report, d)
            data = json.loads((Path(d) / "scenario_results.json").read_text(encoding="utf-8"))
            md = (Path(d) / "scenario_results.md").read_text(encoding="utf-8")
        self.assertEqual(data["counts"], self.report["counts"])
        self.assertIn("| A8 |", md)
        self.assertIn("PENDING means", md)


if __name__ == "__main__":
    unittest.main()
