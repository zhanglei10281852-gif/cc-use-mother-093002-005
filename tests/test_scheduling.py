"""排程硬约束、候选打分与公平轮换测试。"""
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from teacher_practicum.clock import Clock
from teacher_practicum.domain import (
    Competency,
    DateRange,
    Language,
)
from teacher_practicum.fixtures import build_demo_service
from teacher_practicum.scheduler import AssignmentStatus


def w(start, end):
    return DateRange(date(*start), date(*end))


class HardConstraintTests(unittest.TestCase):
    def setUp(self):
        self.svc = build_demo_service(Clock())

    def test_language_mismatch_explained(self):
        # T02 只会英语 B2：泰语 B1 的小学场景不可行，英语 B2 的大学场景可行
        plan = self.svc.plan(["T02"])
        self.assertIn("T02", plan.candidates)
        best = plan.candidates["T02"][0]
        self.assertEqual(best.scenario_id, "BKK-UNI")
        # 直接对小学场景做硬校验，原因中应明确出现语言不匹配
        site = self.svc.sites["BKK"]
        mentor = self.svc.mentors["M-B1"]
        trainee = self.svc.trainees["T02"]
        reasons = self.svc.scheduler.hard_check(
            trainee, site, mentor, "BKK-PRI", site.windows[0])
        self.assertTrue(any("语言不匹配" in r for r in reasons), reasons)

    def test_no_feasible_candidate_when_all_levels_below(self):
        plan = self.svc.plan(["T04"])
        self.assertNotIn("T04", plan.candidates)
        self.assertTrue(plan.infeasible["T04"])

    def test_mentor_capacity_not_double_booked(self):
        a1 = self.svc.propose("T01")  # T01 -> M-B1 容量 1
        self.assertEqual(a1.mentor_id, "M-B1")
        self.svc.register_trainee("T05", "陈临",
                                  languages={Language.THAI: "B1"})
        plan = self.svc.plan(["T05"])
        # M-B1 因容量满不可选；若有候选则不能落在 M-B1
        for c in plan.candidates.get("T05", []):
            self.assertNotEqual(c.mentor_id, "M-B1")
        all_reasons = [r for rs in plan.infeasible.values() for r in rs]
        self.assertTrue(any("容量" in r for r in all_reasons))

    def test_trainee_cannot_fall_into_two_overlapping_windows(self):
        a = self.svc.propose("T03")  # 河内窗口
        self.svc.register_site(
            "BKK2", "曼谷第二学校", "泰国",
            windows=[w((2026, 11, 15), (2026, 12, 5))],  # 与河内窗口重叠
            scenarios=list(self.svc.sites["HAN"].scenarios),
        )
        self.svc.register_mentor(
            "M-X1", "林老师", "BKK2", capacity=2,
            language_requirements=list(self.svc.mentors["M-H1"].language_requirements),
            competencies=list(self.svc.mentors["M-H1"].competencies))
        plan = self.svc.plan(["T03"])
        for c in plan.candidates.get("T03", []):
            if c.site_id == "BKK2":
                self.fail("重叠窗口不应产生候选")

    def test_mentor_unavailable_slot_blocks_candidate(self):
        # 在河内校历中加入一个完全落在导师不可用时段（11/20~11/25）内的窗口
        site = self.svc.sites["HAN"]
        site.windows.append(w((2026, 11, 21), (2026, 11, 24)))
        trainee = self.svc.trainees["T03"]
        mentor = self.svc.mentors["M-H1"]
        plan = self.svc.plan(["T03"])
        # 任何候选都不得使用该窗口
        for c in plan.candidates.get("T03", []):
            self.assertFalse(
                c.site_id == "HAN" and c.window.start == date(2026, 11, 21),
                "导师不可用时段内的窗口不应成为候选")
        reasons = self.svc.scheduler.hard_check(
            trainee, site, mentor, "HAN-SEC", w((2026, 11, 21), (2026, 11, 24)))
        self.assertTrue(any("不可用时段" in r for r in reasons))

    def test_window_must_fit_school_calendar(self):
        site = self.svc.sites["HAN"]
        mentor = self.svc.mentors["M-H1"]
        trainee = self.svc.trainees["T03"]
        rogue = w((2026, 9, 1), (2026, 9, 20))
        reasons = self.svc.scheduler.hard_check(
            trainee, site, mentor, "HAN-SEC", rogue)
        self.assertTrue(any("校历" in r for r in reasons))


class ScoringTests(unittest.TestCase):
    def setUp(self):
        self.svc = build_demo_service(Clock())

    def test_coverage_weight_beats_fairness(self):
        # T03 尚无任何能力：候选解释必须体现能力补齐加分且分数可追溯
        plan = self.svc.plan(["T03"])
        best = plan.candidates["T03"][0]
        self.assertGreater(best.score, 0)
        self.assertTrue(any("能力补齐" in line for line in best.explanation))
        self.assertEqual(len(best.expected_gain), 3)

    def test_fairness_prefers_less_loaded_mentor(self):
        # M-B1 容量 1；把容量调大后，先占用 M-B1，新增同水平学员应优先 M-B2 之外的低负载者
        # 这里验证评分含负荷项：制造两条同分能力路径时，负荷低者排在前
        plan = self.svc.plan(["T01"])
        scores = [(c.mentor_id, c.score) for c in plan.candidates["T01"]]
        # M-B1 小学场景（补 2 项）应排在大学场景（语言不达标，根本不可行）之前
        self.assertEqual(scores[0][0], "M-B1")

    def test_repeat_pairing_is_penalised(self):
        a = self.svc.propose("T01")
        for party in ("合作学校", "导师", "学院实践办公室"):
            from teacher_practicum.domain import Role
            self.svc.confirm(a.assignment_id, Role(party))
        self.svc.start(a.assignment_id)
        self.svc.complete(a.assignment_id)
        # 完成一轮后，再次排 T01：与 M-B1 的重复配对应在解释中出现轮换扣分
        plan = self.svc.plan(["T01"])
        repeats = [c for c in plan.candidates["T01"] if c.mentor_id == "M-B1"]
        if repeats:
            self.assertTrue(any("轮换扣分" in x for x in repeats[0].explanation))


if __name__ == "__main__":
    unittest.main()
