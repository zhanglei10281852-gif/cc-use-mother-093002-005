import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from support import generate_all, make_service  # noqa: E402
from teacher_practicum import (  # noqa: E402
    CaseStatus,
    IncidentType,
    Level,
    PartnerSite,
    ReportingPolicy,
    Window,
)
from datetime import date  # noqa: E402


class IncidentReportTests(unittest.TestCase):
    def setUp(self):
        self.service = make_service()
        self.arrangements = generate_all(self.service)

    def test_duplicate_reports_merge_into_single_case(self):
        case1, created1 = self.service.report_incident(
            IncidentType.SAFETY, Level.HIGH, "T1", "宿舍停水", reporter="导师"
        )
        case2, created2 = self.service.report_incident(
            IncidentType.SAFETY, Level.HIGH, "T1", "宿舍仍停水", reporter="学员"
        )
        self.assertTrue(created1)
        self.assertFalse(created2)
        self.assertEqual(case1.case_id, case2.case_id)
        self.assertEqual(len(self.service.cases), 1)
        self.assertEqual(len(case1.reports), 2)

    def test_visibility_follows_level_and_site_policy(self):
        # 曼谷合作学校要求 HIGH 及以上同步学校
        case, _ = self.service.report_incident(
            IncidentType.SAFETY, Level.HIGH, "T1", "夜间施工", reporter="导师"
        )
        visible = self.service.case_visibility(case.case_id)
        self.assertIn("school", visible)
        self.assertIn("college_leadership", visible)

        # 另一合作点仅 CRITICAL 同步学校
        self.service.add_site(
            PartnerSite(
                site_id="S2",
                name="河内合作学校",
                country="越南",
                terms={"秋": Window(date(2026, 11, 9), date(2026, 12, 31))},
                reporting_policy=ReportingPolicy(
                    school_visible_levels=frozenset({Level.CRITICAL})
                ),
            )
        )
        self.service.trainees["T2"].visited_countries.add("泰国")
        case2, _ = self.service.report_incident(
            IncidentType.SAFETY, Level.MEDIUM, "T2", "财物遗失", reporter="导师"
        )
        case2.site_id = "S2"  # 事件发生在另一合作点，适用该校上报政策
        visible2 = self.service.case_visibility(case2.case_id)
        self.assertNotIn("school", visible2)

    def test_leave_is_visible_to_school_and_mentor(self):
        case, _ = self.service.report_incident(
            IncidentType.LEAVE, Level.LOW, "T1", "病假两天", reporter="学员"
        )
        visible = self.service.case_visibility(case.case_id)
        self.assertIn("school", visible)
        self.assertIn("mentor", visible)
        self.assertNotIn("college_leadership", visible)

    def test_overdue_case_escalates_with_controllable_clock(self):
        case, _ = self.service.report_incident(
            IncidentType.TEACHING_ACCIDENT, Level.MEDIUM, "T1", "误授内容", reporter="学校"
        )
        # MEDIUM 时限 72 小时，推进 73 小时触发升级
        escalated = self.service.advance_clock(hours=73)
        self.assertEqual([c.case_id for c in escalated], [case.case_id])
        self.assertEqual(case.level, Level.HIGH)
        self.assertTrue(case.escalated)
        self.assertEqual(len(case.escalations), 1)

    def test_escalation_caps_at_critical(self):
        case, _ = self.service.report_incident(
            IncidentType.SAFETY, Level.HIGH, "T1", "治安事件", reporter="学校"
        )
        self.service.advance_clock(hours=25)  # HIGH 时限 24h -> CRITICAL
        self.assertEqual(case.level, Level.CRITICAL)
        escalated = self.service.advance_clock(hours=100)
        self.assertEqual(escalated, [])
        self.assertEqual(case.level, Level.CRITICAL)

    def test_resolved_case_does_not_escalate(self):
        case, _ = self.service.report_incident(
            IncidentType.LEAVE, Level.LOW, "T1", "事假", reporter="学员"
        )
        self.service.resolve_case(case.case_id, "已批准并调课")
        escalated = self.service.advance_clock(hours=200)
        self.assertEqual(escalated, [])

    def test_full_lifecycle_to_closed(self):
        case, _ = self.service.report_incident(
            IncidentType.TEACHING_ACCIDENT, Level.MEDIUM, "T1", "课堂冲突", reporter="导师"
        )
        with self.assertRaises(ValueError):
            self.service.close_case(case.case_id)
        self.service.acknowledge_case(case.case_id)
        self.service.resolve_case(case.case_id, "导师介入调解")
        self.service.retrospect_case(case.case_id, "复盘：加强备课审核")
        self.service.close_case(case.case_id)
        self.assertEqual(case.status, CaseStatus.CLOSED)
        self.assertTrue(case.is_closed)


if __name__ == "__main__":
    unittest.main()
