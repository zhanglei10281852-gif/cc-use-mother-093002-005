import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from support import generate_all, make_service  # noqa: E402
from teacher_practicum import (  # noqa: E402
    ArrangementStatus,
    IncidentType,
    Level,
    Party,
    PracticumService,
    StartedPracticumError,
    UnavailableWindow,
    Window,
)
from teacher_practicum.scheduling import MENTOR_CAPACITY  # noqa: E402


class PlanGenerationTests(unittest.TestCase):
    def test_generate_plan_creates_explained_pending_arrangements(self):
        service = make_service()
        created, unassigned = service.generate_plan()
        self.assertEqual(len(created), 2)
        self.assertEqual(unassigned, {})
        for arr in created:
            self.assertEqual(arr.status, ArrangementStatus.PENDING)
            self.assertTrue(arr.explanation, "候选安排必须附带可解释理由")

    def test_unassigned_scenario_keeps_reasons(self):
        service = make_service()
        service.trainees["T1"].language_level = 1
        service.trainees["T2"].language_level = 1
        created, unassigned = service.generate_plan()
        self.assertEqual(created, [])
        self.assertIn("C1", unassigned)
        self.assertTrue(any("低于要求" in r for r in unassigned["C1"]))


class ReevaluationTests(unittest.TestCase):
    def setUp(self):
        self.service = make_service()
        self.arrangements = generate_all(self.service)

    def _confirm_all(self, arr):
        for party in Party:
            self.service.confirm(arr.arrangement_id, party)

    def test_capacity_cut_marks_conflict_and_resets_confirmations(self):
        for arr in self.arrangements:
            self._confirm_all(arr)
            self.assertEqual(arr.status, ArrangementStatus.CONFIRMED)
        self.service.set_mentor_capacity("M1", 1)
        for arr in self.arrangements:
            self.assertEqual(arr.status, ArrangementStatus.CONFLICTED)
            self.assertIn(MENTOR_CAPACITY, [c.code for c in arr.conflicts])
            self.assertEqual(len(arr.pending_parties()), 0)  # 非 PENDING 状态
            self.assertTrue(
                all(c.state == "pending" for c in arr.confirmations.values()),
                "三方确认应被重置",
            )

    def test_capacity_restore_clears_conflict(self):
        self.service.set_mentor_capacity("M1", 1)
        self.service.set_mentor_capacity("M1", 2)
        for arr in self.arrangements:
            self.assertEqual(arr.status, ArrangementStatus.PENDING)
            self.assertEqual(arr.conflicts, [])

    def test_unrelated_change_does_not_touch_arrangement(self):
        self._confirm_all(self.arrangements[0])
        revision = self.arrangements[0].revision
        # 登记一名与安排无关人员的不可用时段
        self.service.add_unavailable_window(
            UnavailableWindow("trainee", "T-OTHER", Window(date(2026, 11, 3), date(2026, 11, 4)), "事假")
        )
        self.assertEqual(self.arrangements[0].status, ArrangementStatus.CONFIRMED)
        self.assertEqual(self.arrangements[0].revision, revision)

    def test_language_update_reevaluates_only_affected_trainee(self):
        self._confirm_all(self.arrangements[0])
        self._confirm_all(self.arrangements[1])
        t1_arr = next(a for a in self.arrangements if a.trainee_id == "T1")
        other = next(a for a in self.arrangements if a.trainee_id != "T1")
        self.service.set_trainee_language_level("T1", 1)
        self.assertEqual(t1_arr.status, ArrangementStatus.CONFLICTED)
        self.assertEqual(other.status, ArrangementStatus.CONFIRMED)

    def test_started_practicum_is_not_silently_changed(self):
        arr = self.arrangements[0]
        self._confirm_all(arr)
        self.service.start(arr.arrangement_id)
        self.service.set_mentor_capacity("M1", 1)
        self.assertEqual(arr.status, ArrangementStatus.STARTED, "进行中实践不得被静默改状态")
        self.assertTrue(arr.conflicts, "冲突应被记录供人工处置")
        self.assertTrue(any("不做静默改派" in h for h in arr.history))


class ReassignmentTests(unittest.TestCase):
    def setUp(self):
        self.service = make_service()
        self.arrangements = generate_all(self.service)
        from teacher_practicum.models import Trainee

        self.service.add_trainee(Trainee("T3", "替补学员", 5))
        self.arr = self.arrangements[0]

    def _confirm_and_start(self):
        for party in Party:
            self.service.confirm(self.arr.arrangement_id, party)
        self.service.start(self.arr.arrangement_id)

    def test_started_practicum_rejects_silent_reassignment(self):
        self._confirm_and_start()
        with self.assertRaises(StartedPracticumError):
            self.service.reassign_trainee(self.arr.arrangement_id, "T3")

    def test_explicit_reassignment_is_audited_and_reconfirmed(self):
        self._confirm_and_start()
        self.service.reassign_trainee(
            self.arr.arrangement_id, "T3", reason="原学员突发疾病", actor="实践办公室"
        )
        self.assertEqual(self.arr.trainee_id, "T3")
        self.assertEqual(self.arr.status, ArrangementStatus.PENDING)
        self.assertTrue(any("显式改派" in h for h in self.arr.history))
        self.assertTrue(
            all(c.state == "pending" for c in self.arr.confirmations.values()),
            "改派后须重新三方确认",
        )

    def test_pending_arrangement_can_be_reassigned(self):
        self.service.reassign_trainee(self.arr.arrangement_id, "T3")
        self.assertEqual(self.arr.trainee_id, "T3")


class CompletionTests(unittest.TestCase):
    def test_completion_updates_trainee_coverage(self):
        service = make_service()
        (arr,) = [a for a in generate_all(service) if a.scenario_id == "C1"]
        for party in Party:
            service.confirm(arr.arrangement_id, party)
        service.start(arr.arrangement_id)
        service.complete(arr.arrangement_id)
        trainee = service.trainees[arr.trainee_id]
        self.assertEqual(trainee.covered_competencies, {"课堂管理", "跨文化沟通"})
        self.assertEqual(trainee.completed_rotations, 1)
        self.assertEqual(trainee.visited_countries, {"泰国"})


class PersistenceTests(unittest.TestCase):
    def test_snapshot_restore_keeps_unresolved_cases_and_clock(self):
        service = make_service()
        generate_all(service)
        case, _ = service.report_incident(
            IncidentType.SAFETY, Level.HIGH, "T1", "夜间施工", reporter="导师"
        )
        service.advance_clock(hours=10)

        restored = PracticumService.from_snapshot(service.to_snapshot())
        self.assertIn(case.case_id, restored.cases)
        summary = restored.daily_summary()
        unresolved_ids = [c["case_id"] for c in summary["unresolved_cases"]]
        self.assertIn(case.case_id, unresolved_ids)
        # 时钟随快照恢复，继续推进可再次触发升级
        escalated = restored.advance_clock(hours=20)
        self.assertIn(case.case_id, [c.case_id for c in escalated])

    def test_snapshot_roundtrip_preserves_arrangements(self):
        service = make_service()
        arrangements = generate_all(service)
        for party in Party:
            service.confirm(arrangements[0].arrangement_id, party)
        restored = PracticumService.from_snapshot(service.to_snapshot())
        self.assertEqual(
            restored.arrangements[arrangements[0].arrangement_id].status,
            ArrangementStatus.CONFIRMED,
        )
        self.assertEqual(len(restored.arrangements), len(arrangements))


if __name__ == "__main__":
    unittest.main()
