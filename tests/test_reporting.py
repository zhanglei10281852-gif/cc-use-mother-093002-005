import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from support import generate_all, make_service  # noqa: E402
from teacher_practicum import IncidentType, Level, Party  # noqa: E402
from teacher_practicum.reporting import format_summary  # noqa: E402


class DailySummaryTests(unittest.TestCase):
    def setUp(self):
        self.service = make_service()
        self.arrangements = generate_all(self.service)

    def test_summary_lists_pending_parties(self):
        arr = self.arrangements[0]
        self.service.confirm(arr.arrangement_id, Party.SCHOOL)
        summary = self.service.daily_summary()
        pending = {p["arrangement_id"]: p["waiting_on"] for p in summary["pending_confirmations"]}
        self.assertEqual(pending[arr.arrangement_id], ["mentor", "college"])

    def test_summary_lists_conflicted_arrangements(self):
        self.service.set_mentor_capacity("M1", 1)
        summary = self.service.daily_summary()
        conflicted = summary["conflicted_arrangements"]
        self.assertEqual(len(conflicted), 2)
        self.assertTrue(any("MENTOR_CAPACITY" in c for c in conflicted[0]["conflicts"]))

    def test_summary_lists_competency_coverage_per_trainee(self):
        arr = next(a for a in self.arrangements if a.scenario_id == "C1")
        for party in Party:
            self.service.confirm(arr.arrangement_id, party)
        self.service.start(arr.arrangement_id)
        self.service.complete(arr.arrangement_id)
        summary = self.service.daily_summary()
        coverage = {c["trainee_id"]: c for c in summary["competency_coverage"]}
        t1 = coverage[arr.trainee_id]
        self.assertEqual(t1["covered"], ["课堂管理", "跨文化沟通"])
        self.assertEqual(t1["gap"], ["教学设计"])  # 目标中尚未覆盖也未计划

    def test_summary_lists_unresolved_cases_only(self):
        case_open, _ = self.service.report_incident(
            IncidentType.SAFETY, Level.HIGH, "T1", "夜间施工", reporter="导师"
        )
        case_done, _ = self.service.report_incident(
            IncidentType.LEAVE, Level.LOW, "T2", "事假", reporter="学员"
        )
        self.service.resolve_case(case_done.case_id, "已批准")
        self.service.retrospect_case(case_done.case_id, "无需改进")
        self.service.close_case(case_done.case_id)
        summary = self.service.daily_summary()
        ids = [c["case_id"] for c in summary["unresolved_cases"]]
        self.assertIn(case_open.case_id, ids)
        self.assertNotIn(case_done.case_id, ids)

    def test_format_summary_renders_sections(self):
        self.service.report_incident(IncidentType.LEAVE, Level.LOW, "T1", "病假", reporter="学员")
        text = format_summary(self.service.daily_summary())
        self.assertIn("仍有冲突的安排", text)
        self.assertIn("等待确认的安排", text)
        self.assertIn("学员能力覆盖", text)
        self.assertIn("未办结事件", text)


if __name__ == "__main__":
    unittest.main()
