"""三方确认、变更触发重新评估、已开始实践不得静默改派的测试。"""
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from teacher_practicum.clock import Clock
from teacher_practicum.domain import DateRange, Role
from teacher_practicum.fixtures import build_demo_service
from teacher_practicum.scheduler import AssignmentStatus
from teacher_practicum.service import ServiceError


def w(start, end):
    return DateRange(date(*start), date(*end))


class ConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.svc = build_demo_service(Clock())
        self.a = self.svc.propose("T03")

    def test_requires_all_three_parties(self):
        self.assertEqual(
            set(self.a.pending_parties()),
            {Role.SCHOOL, Role.MENTOR, Role.COLLEGE})
        self.svc.confirm(self.a.assignment_id, Role.SCHOOL)
        self.svc.confirm(self.a.assignment_id, Role.MENTOR)
        self.assertEqual(self.a.status, AssignmentStatus.PROPOSED)
        done = self.svc.confirm(self.a.assignment_id, Role.COLLEGE)
        self.assertTrue(done)
        self.assertEqual(self.a.status, AssignmentStatus.CONFIRMED)
        self.assertEqual(self.a.pending_parties(), [])

    def test_duplicate_confirmation_is_idempotent(self):
        self.svc.confirm(self.a.assignment_id, Role.SCHOOL)
        self.assertFalse(self.svc.confirm(self.a.assignment_id, Role.SCHOOL))
        self.assertEqual(len(self.a.confirmations), 1)

    def test_cannot_start_without_all_confirmations(self):
        self.svc.confirm(self.a.assignment_id, Role.SCHOOL)
        with self.assertRaises(ValueError):
            self.svc.start(self.a.assignment_id)


class ReassessmentTests(unittest.TestCase):
    def setUp(self):
        self.svc = build_demo_service(Clock())
        self.a = self.svc.propose("T03")  # T03 -> HAN / M-H1

    def test_mentor_capacity_shrink_triggers_reassessment(self):
        changed = self.svc.revise_mentor("M-H1", capacity=0)
        self.assertIn(self.a.assignment_id, [x.assignment_id for x in changed])
        self.assertEqual(self.a.status, AssignmentStatus.NEEDS_REASSESSMENT)
        self.assertTrue(any("容量" in r for r in self.a.reassessment_reasons))
        # 日报可呈现等待学院/学校/导师的状态，确认在重新评估时被视为待重新推进
        self.assertTrue(self.a.pending_parties())

    def test_school_calendar_change_triggers_reassessment(self):
        self.svc.revise_site("HAN", windows=[w((2026, 12, 1), (2027, 1, 15))])
        self.assertEqual(self.a.status, AssignmentStatus.NEEDS_REASSESSMENT)
        self.assertTrue(any("校历" in r for r in self.a.reassessment_reasons))
        self.assertEqual(self.a.site_revision, 1)
        self.assertEqual(self.svc.sites["HAN"].revision, 2)

    def test_recovery_when_conflict_clears(self):
        self.svc.revise_mentor("M-H1", capacity=0)
        self.assertEqual(self.a.status, AssignmentStatus.NEEDS_REASSESSMENT)
        # 学校/导师恢复容量后自动回到待确认
        self.svc.revise_mentor("M-H1", capacity=2)
        self.assertEqual(self.a.status, AssignmentStatus.PROPOSED)
        self.assertEqual(self.a.reassessment_reasons, [])

    def test_started_practicum_is_never_silently_reassigned(self):
        for party in (Role.SCHOOL, Role.MENTOR, Role.COLLEGE):
            self.svc.confirm(self.a.assignment_id, party)
        self.svc.start(self.a.assignment_id)
        # 导师容量收紧：状态必须仍是进行中
        self.svc.revise_mentor("M-H1", capacity=0)
        self.assertEqual(self.a.status, AssignmentStatus.STARTED)
        self.assertTrue(self.a.change_notices)
        # 显式改派也必须被拒绝
        with self.assertRaises(ServiceError):
            self.svc.replace_assignment(self.a.assignment_id)
        with self.assertRaises(ServiceError):
            self.svc.cancel(self.a.assignment_id, "测试")

    def test_explicit_replacement_keeps_audit_link(self):
        # T03 在河内；新增一个同语种合作点后显式改派
        self.svc.register_site(
            "HAN2", "胡志明市华文中心", "越南",
            windows=[w((2026, 11, 10), (2026, 12, 20))],
            scenarios=list(self.svc.sites["HAN"].scenarios))
        self.svc.register_mentor(
            "M-H2", "陈氏红", "HAN2", capacity=1,
            language_requirements=list(self.svc.mentors["M-H1"].language_requirements),
            competencies=list(self.svc.mentors["M-H1"].competencies))
        new = self.svc.replace_assignment(self.a.assignment_id)
        self.assertEqual(self.a.status, AssignmentStatus.SUPERSEDED)
        self.assertEqual(self.a.superseded_by, new.assignment_id)
        self.assertEqual(new.status, AssignmentStatus.PROPOSED)
        self.assertIn("接替改派", new.log[-1])


if __name__ == "__main__":
    unittest.main()
