"""每日汇总与中断恢复测试。"""
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from teacher_practicum.clock import Clock
from teacher_practicum.domain import EventLevel, Role
from teacher_practicum.fixtures import build_demo_service
from teacher_practicum.incidents import CaseStatus, IncidentKind
from teacher_practicum.reporting import build_daily_report
from teacher_practicum import storage
from teacher_practicum.scheduler import AssignmentStatus


class DailyReportTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.svc = build_demo_service(self.clock)

    def test_report_covers_four_required_sections(self):
        a = self.svc.propose("T03")
        self.svc.confirm(a.assignment_id, Role.SCHOOL)
        self.svc.incidents.report(
            trainee_id="T03", kind=IncidentKind.LEAVE, level=EventLevel.LOW,
            title="事假", occurred_from=date(2026, 11, 15))
        report = build_daily_report(self.svc, sweep=False)

        # 等待确认：列出剩余两方
        item = next(x for x in report.awaiting_confirmation
                    if x["assignment_id"] == a.assignment_id)
        self.assertIn("导师", item["pending"])
        self.assertIn("学院实践办公室", item["pending"])

        # 能力覆盖：每名学员一行
        ids = {x["trainee_id"] for x in report.competency_coverage}
        self.assertEqual(ids, {"T01", "T02", "T03", "T04"})
        t03 = next(x for x in report.competency_coverage if x["trainee_id"] == "T03")
        self.assertIn("课堂组织", t03["missing"])

        # 未办结事件出现
        self.assertEqual(len(report.open_cases), 1)
        self.assertEqual(report.open_cases[0]["trainee_id"], "T03")

        # 文本汇总包含四个章节
        text = report.render_text()
        for title in ("仍有冲突", "等待确认", "学员能力覆盖", "尚未办结事件"):
            self.assertIn(title, text)

    def test_conflict_section_shows_reassessment(self):
        a = self.svc.propose("T03")
        self.svc.revise_mentor("M-H1", capacity=0)
        report = build_daily_report(self.svc, sweep=False)
        self.assertTrue(any(a.assignment_id in c and "重新评估" in c
                            for c in report.conflicts))

    def test_in_progress_gain_listed_as_coverage(self):
        a = self.svc.propose("T03")  # 三项能力
        for party in (Role.SCHOOL, Role.MENTOR, Role.COLLEGE):
            self.svc.confirm(a.assignment_id, party)
        self.svc.start(a.assignment_id)
        report = build_daily_report(self.svc, sweep=False)
        t03 = next(x for x in report.competency_coverage if x["trainee_id"] == "T03")
        self.assertIn("课堂组织", t03["in_progress"])

    def test_sweep_runs_inside_daily_report(self):
        self.svc.incidents.report(
            trainee_id="T01", kind=IncidentKind.LEAVE, level=EventLevel.LOW,
            title="将逾期的请假", occurred_from=date(2026, 11, 1))
        self.clock.advance(days=5)
        report = build_daily_report(self.svc)  # sweep=True
        self.assertEqual(len(report.escalated), 1)
        case = self.svc.incidents.open_cases()[0]
        self.assertEqual(case.status, CaseStatus.ESCALATED)


class PersistenceTests(unittest.TestCase):
    def test_full_state_round_trip_including_open_cases(self):
        clock = Clock()
        svc = build_demo_service(clock)
        a = svc.propose("T03")
        svc.confirm(a.assignment_id, Role.SCHOOL)
        svc.incidents.report(
            trainee_id="T03", kind=IncidentKind.TEACHING, level=EventLevel.MEDIUM,
            title="待复盘事故", occurred_from=date(2026, 11, 20),
            site_id="HAN", actor=Role.SCHOOL)
        clock.advance(days=2)
        svc.incidents.sweep_overdue()  # 时钟到达时限，触发升级后再保存

        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "state.json"
            storage.save(svc, path)
            restored = storage.load(path)

        # 中断恢复：安排状态、确认痕迹、未办结事件全部保留
        ra = restored.assignments[a.assignment_id]
        self.assertEqual(ra.status, AssignmentStatus.PROPOSED)
        self.assertIn(Role.SCHOOL, ra.confirmations)
        self.assertEqual(ra.pending_parties(), [Role.MENTOR, Role.COLLEGE])
        open_cases = restored.incidents.open_cases()
        self.assertEqual(len(open_cases), 1)
        self.assertEqual(open_cases[0].status, CaseStatus.ESCALATED)
        # 时钟时间随快照恢复
        self.assertEqual(restored.clock.now(), svc.clock.now())
        # 恢复后可继续操作
        restored.confirm(ra.assignment_id, Role.MENTOR)
        self.assertEqual(
            ra.pending_parties(), [Role.COLLEGE])

    def test_site_scope_round_trips(self):
        svc = build_demo_service(Clock())
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "state.json"
            storage.save(svc, path)
            restored = storage.load(path)
        scope = restored.sites["BKK"].report_scope
        self.assertIsNotNone(scope)
        self.assertTrue(Role.CONSULAR in scope.extras_for(EventLevel.HIGH))
        self.assertFalse(Role.CONSULAR in scope.extras_for(EventLevel.MEDIUM))


if __name__ == "__main__":
    unittest.main()
