"""事件分级可见、去重并案、可控时钟逾期升级、处置复盘闭环测试。"""
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from teacher_practicum.clock import Clock
from teacher_practicum.domain import EventLevel, Role
from teacher_practicum.fixtures import build_demo_service
from teacher_practicum.incidents import CaseStatus, IncidentKind


class VisibilityTests(unittest.TestCase):
    def setUp(self):
        self.svc = build_demo_service(Clock())
        self.reg = self.svc.incidents

    def _report(self, level, kind=IncidentKind.LEAVE, site_id=None, trainee_id="T01"):
        case, _ = self.reg.report(
            trainee_id=trainee_id, kind=kind, level=level, title=level.name,
            occurred_from=date(2026, 12, 1), site_id=site_id)
        return case

    def test_low_level_hidden_from_school(self):
        c = self._report(EventLevel.LOW)
        self.assertTrue(c.visible_to(Role.MENTOR))
        self.assertFalse(c.visible_to(Role.SCHOOL))
        self.assertFalse(c.visible_to(Role.LEADERSHIP))

    def test_safety_visible_to_consular(self):
        c = self._report(EventLevel.SAFETY, IncidentKind.SAFETY, site_id="HAN")
        self.assertTrue(c.visible_to(Role.CONSULAR))
        self.assertTrue(c.visible_to(Role.SCHOOL))

    def test_site_scope_extends_high_level_reporting(self):
        # 曼谷要求 HIGH 以上加报领事
        c = self._report(EventLevel.HIGH, IncidentKind.TEACHING, site_id="BKK")
        self.assertTrue(c.visible_to(Role.CONSULAR))
        # 河内没有该要求：HIGH 对领事不可见（换一名学员，避免与上案并案）
        c2 = self._report(EventLevel.HIGH, IncidentKind.TEACHING,
                          site_id="HAN", trainee_id="T02")
        self.assertFalse(c2.visible_to(Role.CONSULAR))

    def test_out_of_scope_actor_cannot_handle(self):
        c = self._report(EventLevel.LOW)
        with self.assertRaises(PermissionError):
            self.reg.acknowledge(c.case_id, Role.SCHOOL)


class DeduplicationTests(unittest.TestCase):
    def setUp(self):
        self.svc = build_demo_service(Clock())
        self.reg = self.svc.incidents

    def test_repeated_report_keeps_single_case(self):
        c1, created1 = self.reg.report(
            trainee_id="T03", kind=IncidentKind.LEAVE, level=EventLevel.LOW,
            title="病假", occurred_from=date(2026, 11, 20),
            occurred_to=date(2026, 11, 21))
        c2, created2 = self.reg.report(
            trainee_id="T03", kind=IncidentKind.LEAVE, level=EventLevel.LOW,
            title="同一病假再次上报", occurred_from=date(2026, 11, 21))
        self.assertTrue(created1)
        self.assertFalse(created2)
        self.assertEqual(c1.case_id, c2.case_id)
        self.assertEqual(c1.report_count, 2)
        self.assertEqual(len(self.reg.cases), 1)

    def test_different_period_or_kind_opens_new_case(self):
        self.reg.report(
            trainee_id="T03", kind=IncidentKind.LEAVE, level=EventLevel.LOW,
            title="病假", occurred_from=date(2026, 11, 20))
        c, created = self.reg.report(
            trainee_id="T03", kind=IncidentKind.LEAVE, level=EventLevel.LOW,
            title="另一段事假", occurred_from=date(2026, 12, 5))
        self.assertTrue(created)
        c2, created2 = self.reg.report(
            trainee_id="T03", kind=IncidentKind.TEACHING, level=EventLevel.MEDIUM,
            title="同期教学事故", occurred_from=date(2026, 11, 20))
        self.assertTrue(created2)

    def test_duplicate_with_higher_level_upgrades_case(self):
        c1, _ = self.reg.report(
            trainee_id="T01", kind=IncidentKind.SAFETY, level=EventLevel.MEDIUM,
            title="擦伤", occurred_from=date(2026, 11, 30), site_id="BKK")
        c2, created = self.reg.report(
            trainee_id="T01", kind=IncidentKind.SAFETY, level=EventLevel.SAFETY,
            title="复核为安全事件", occurred_from=date(2026, 11, 30), site_id="BKK")
        self.assertFalse(created)
        self.assertEqual(c1.level, EventLevel.SAFETY)
        self.assertTrue(c1.visible_to(Role.CONSULAR))


class EscalationTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.svc = build_demo_service(self.clock)
        self.reg = self.svc.incidents

    def test_low_case_overdue_escalates_after_three_days(self):
        c, _ = self.reg.report(
            trainee_id="T03", kind=IncidentKind.LEAVE, level=EventLevel.LOW,
            title="逾期未受理的请假", occurred_from=date(2026, 11, 10))
        # 未到时限：不升级
        self.clock.advance(days=2)
        self.assertEqual(self.reg.sweep_overdue(), [])
        self.assertEqual(c.status, CaseStatus.OPEN)
        # 超过 3 天：升级
        self.clock.advance(days=2)  # 共 4 天
        escalated = self.reg.sweep_overdue()
        self.assertEqual([x.case_id for x in escalated], [c.case_id])
        self.assertEqual(c.status, CaseStatus.ESCALATED)
        self.assertEqual(c.escalations, 1)
        # LOW 升级前不对学院领导可见，升级后扩大
        self.assertTrue(c.visible_to(Role.LEADERSHIP))

    def test_safety_deadline_is_twelve_hours(self):
        c, _ = self.reg.report(
            trainee_id="T01", kind=IncidentKind.SAFETY, level=EventLevel.SAFETY,
            title="安全事件", occurred_from=date(2026, 11, 10))
        self.clock.advance(hours=11)
        self.assertEqual(self.reg.sweep_overdue(), [])
        self.clock.advance(hours=2)
        self.assertEqual(len(self.reg.sweep_overdue()), 1)

    def test_acknowledged_case_still_escalates_if_unresolved(self):
        c, _ = self.reg.report(
            trainee_id="T03", kind=IncidentKind.TEACHING, level=EventLevel.MEDIUM,
            title="处置中超时", occurred_from=date(2026, 11, 10),
            actor=Role.COLLEGE)
        self.reg.acknowledge(c.case_id, Role.COLLEGE)
        self.clock.advance(days=3)
        self.assertEqual(c.status, CaseStatus.HANDLING)
        escalated = self.reg.sweep_overdue()
        self.assertEqual(len(escalated), 1)
        self.assertTrue(c.visible_to(Role.LEADERSHIP))

    def test_reviewing_case_is_not_re_escalated(self):
        c, _ = self.reg.report(
            trainee_id="T03", kind=IncidentKind.SAFETY, level=EventLevel.SAFETY,
            title="已处置待复盘", occurred_from=date(2026, 11, 10),
            actor=Role.COLLEGE)
        self.reg.acknowledge(c.case_id, Role.COLLEGE)
        self.reg.handle(c.case_id, Role.COLLEGE, "已送医并通知家属")
        self.assertEqual(c.status, CaseStatus.REVIEWING)
        self.clock.advance(days=30)
        self.assertEqual(self.reg.sweep_overdue(), [])
        self.assertEqual(c.status, CaseStatus.REVIEWING)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.svc = build_demo_service(Clock())
        self.reg = self.svc.incidents

    def test_low_leave_closes_without_review(self):
        c, _ = self.reg.report(
            trainee_id="T03", kind=IncidentKind.LEAVE, level=EventLevel.LOW,
            title="事假一天", occurred_from=date(2026, 11, 12))
        self.reg.acknowledge(c.case_id, Role.MENTOR)
        self.reg.handle(c.case_id, Role.COLLEGE, "准假，已安排代课")
        self.assertEqual(c.status, CaseStatus.CLOSED)
        self.assertIsNone(c.review)

    def test_teaching_incident_requires_review_to_close(self):
        c, _ = self.reg.report(
            trainee_id="T03", kind=IncidentKind.TEACHING, level=EventLevel.MEDIUM,
            title="教学进度事故", occurred_from=date(2026, 11, 15),
            site_id="HAN", actor=Role.SCHOOL)
        self.reg.acknowledge(c.case_id, Role.SCHOOL)
        self.reg.handle(c.case_id, Role.COLLEGE, "补排课时并向学校说明")
        self.assertEqual(c.status, CaseStatus.REVIEWING)
        with self.assertRaises(ValueError):
            self.reg.review_and_close(c.case_id, Role.COLLEGE, "   ")
        self.reg.review_and_close(c.case_id, Role.COLLEGE,
                                  "复盘：出发前增加校历对齐培训，两周内完成")
        self.assertEqual(c.status, CaseStatus.CLOSED)
        self.assertIn("复盘", c.timeline[-1].text)


if __name__ == "__main__":
    unittest.main()
