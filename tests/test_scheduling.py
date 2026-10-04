import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from support import AUTUMN, make_service  # noqa: E402
from teacher_practicum.models import Trainee, UnavailableWindow, Window  # noqa: E402
from teacher_practicum.scheduling import (  # noqa: E402
    CALENDAR_OVERLAP,
    LANGUAGE_MISMATCH,
    MENTOR_CAPACITY,
    TRAINEE_UNAVAILABLE,
    Placement,
    detect_conflicts,
    generate_candidates,
)


class ConflictDetectionTests(unittest.TestCase):
    def setUp(self):
        self.service = make_service()

    def _detect(self, trainee_id, scenario_id, placements=None, unavailable=None):
        s = self.service
        placement = Placement(
            trainee_id=trainee_id,
            scenario_id=scenario_id,
            mentor_id="M1",
            site_id="S1",
            window=AUTUMN,
        )
        return detect_conflicts(
            placement,
            trainee=s.trainees[trainee_id],
            scenario=s.scenarios[scenario_id],
            mentor=s.mentors["M1"],
            placements=placements or [],
            unavailable=unavailable if unavailable is not None else s.unavailable,
        )

    def test_language_mismatch_is_flagged(self):
        conflicts = self._detect("T2", "C2")  # C2 要求 4 级？T2 恰好 4 级，改用低水平学员
        self.assertEqual(conflicts, [])
        self.service.trainees["T2"].language_level = 3
        conflicts = self._detect("T2", "C2")
        self.assertEqual([c.code for c in conflicts], [LANGUAGE_MISMATCH])
        self.assertIn("3 级低于授课对象要求的 4 级", conflicts[0].detail)

    def test_mentor_capacity_double_booking_is_flagged(self):
        existing = [
            Placement("T1", "C1", "M1", "S1", AUTUMN, arrangement_id="A-1"),
            Placement("T2", "C2", "M1", "S1", AUTUMN, arrangement_id="A-2"),
        ]
        self.service.mentors["M1"].capacity = 2
        # 第三人叠加到同一导师同一时段，超出容量 2
        self.service.add_trainee(Trainee("T3", "张可", 5))
        conflicts = self._detect("T3", "C1", placements=existing)
        self.assertIn(MENTOR_CAPACITY, [c.code for c in conflicts])

    def test_same_trainee_two_calendar_windows_is_flagged(self):
        existing = [Placement("T1", "C1", "M1", "S1", AUTUMN, arrangement_id="A-1")]
        conflicts = self._detect("T1", "C2", placements=existing)
        self.assertIn(CALENDAR_OVERLAP, [c.code for c in conflicts])

    def test_unavailable_window_blocks_assignment(self):
        unavailable = [
            UnavailableWindow("trainee", "T1", Window(date(2026, 12, 1), date(2026, 12, 10)), "答辩")
        ]
        conflicts = self._detect("T1", "C1", unavailable=unavailable)
        self.assertIn(TRAINEE_UNAVAILABLE, [c.code for c in conflicts])

    def test_self_is_excluded_when_reevaluating(self):
        existing = [Placement("T1", "C1", "M1", "S1", AUTUMN, arrangement_id="A-1")]
        conflicts = detect_conflicts(
            Placement("T1", "C1", "M1", "S1", AUTUMN, arrangement_id="A-1"),
            trainee=self.service.trainees["T1"],
            scenario=self.service.scenarios["C1"],
            mentor=self.service.mentors["M1"],
            placements=existing,
            unavailable=[],
            ignore_arrangement_id="A-1",
        )
        self.assertEqual(conflicts, [])


class CandidateExplanationTests(unittest.TestCase):
    def setUp(self):
        self.service = make_service()

    def test_rejections_explain_language_gap(self):
        self.service.add_trainee(Trainee("T9", "低水平", 2))
        candidates, rejections = generate_candidates(
            list(self.service.trainees.values()),
            [self.service.scenarios["C1"]],
            self.service.sites,
        )
        self.assertNotIn("T9", [c.trainee_id for c in candidates["C1"]])
        self.assertTrue(any("低于要求的 3 级" in r for r in rejections["C1"]))

    def test_fair_rotation_prefers_fewer_rotations(self):
        self.service.trainees["T1"].completed_rotations = 4
        candidates, _ = generate_candidates(
            list(self.service.trainees.values()),
            [self.service.scenarios["C1"]],
            self.service.sites,
        )
        scores = {c.trainee_id: c.score for c in candidates["C1"]}
        self.assertGreater(scores["T2"], scores["T1"])

    def test_candidate_reasons_are_explainable(self):
        candidates, _ = generate_candidates(
            list(self.service.trainees.values()),
            [self.service.scenarios["C1"]],
            self.service.sites,
        )
        top = candidates["C1"][0]
        self.assertTrue(any("培养目标增益" in r for r in top.reasons))
        self.assertTrue(any("公平轮换" in r for r in top.reasons))


if __name__ == "__main__":
    unittest.main()
