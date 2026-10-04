"""候选安排生成与冲突检测：每条建议与拒绝都附带可解释的理由。"""
from __future__ import annotations

from dataclasses import dataclass, field

from .models import CourseScenario, Mentor, PartnerSite, Trainee, UnavailableWindow, Window

# 冲突代码
LANGUAGE_MISMATCH = "LANGUAGE_MISMATCH"  # 学员语言水平与授课对象不匹配
MENTOR_CAPACITY = "MENTOR_CAPACITY"  # 导师容量被重复占用
CALENDAR_OVERLAP = "CALENDAR_OVERLAP"  # 同一学员落入两个重叠校历窗口
TRAINEE_UNAVAILABLE = "TRAINEE_UNAVAILABLE"
MENTOR_UNAVAILABLE = "MENTOR_UNAVAILABLE"
SITE_UNAVAILABLE = "SITE_UNAVAILABLE"


@dataclass(frozen=True)
class Conflict:
    code: str
    detail: str

    def to_dict(self) -> dict:
        return {"code": self.code, "detail": self.detail}

    @classmethod
    def from_dict(cls, data: dict) -> "Conflict":
        return cls(code=data["code"], detail=data["detail"])


@dataclass(frozen=True)
class Placement:
    """一条安排（已存在或待评估）的排布视图。"""

    trainee_id: str
    scenario_id: str
    mentor_id: str
    site_id: str
    window: Window
    arrangement_id: str = ""


@dataclass
class Candidate:
    """某课程场景下的一名候选学员及其打分理由。"""

    trainee_id: str
    scenario_id: str
    score: int
    reasons: list = field(default_factory=list)


def detect_conflicts(
    placement: Placement,
    *,
    trainee: Trainee,
    scenario: CourseScenario,
    mentor: Mentor,
    placements: list,
    unavailable: list,
    ignore_arrangement_id: str = "",
) -> list:
    """对一条安排做全量冲突检查，返回冲突列表（空列表表示可安排）。"""
    conflicts: list = []

    if trainee.language_level < scenario.min_language_level:
        conflicts.append(
            Conflict(
                LANGUAGE_MISMATCH,
                f"学员语言水平 {trainee.language_level} 级低于授课对象要求的 "
                f"{scenario.min_language_level} 级",
            )
        )

    peers = [
        p
        for p in placements
        if p.window.overlaps(placement.window)
        and (not ignore_arrangement_id or p.arrangement_id != ignore_arrangement_id)
    ]

    mentor_load = sum(1 for p in peers if p.mentor_id == mentor.mentor_id)
    if mentor_load + 1 > mentor.capacity:
        conflicts.append(
            Conflict(
                MENTOR_CAPACITY,
                f"导师 {mentor.name} 容量为 {mentor.capacity}，同时段已被占用 "
                f"{mentor_load} 次",
            )
        )

    for p in peers:
        if p.trainee_id == trainee.trainee_id:
            conflicts.append(
                Conflict(
                    CALENDAR_OVERLAP,
                    f"学员 {trainee.name} 已落入另一重叠校历窗口（场景 {p.scenario_id}）",
                )
            )
            break

    owner_checks = (
        ("trainee", trainee.trainee_id, TRAINEE_UNAVAILABLE, f"学员 {trainee.name}"),
        ("mentor", mentor.mentor_id, MENTOR_UNAVAILABLE, f"导师 {mentor.name}"),
        ("site", scenario.site_id, SITE_UNAVAILABLE, f"合作点 {scenario.site_id}"),
    )
    for owner_kind, owner_id, code, label in owner_checks:
        for u in unavailable:
            if u.applies_to(owner_kind, owner_id) and u.window.overlaps(placement.window):
                conflicts.append(Conflict(code, f"{label}在窗口内不可用：{u.reason}"))
                break

    return conflicts


def score_candidate(trainee: Trainee, scenario: CourseScenario, site: PartnerSite) -> Candidate:
    """按培养目标与公平轮换为候选学员打分，并记录可解释理由。"""
    gained = sorted(
        c for c in scenario.competencies
        if c in trainee.target_competencies and c not in trainee.covered_competencies
    )
    score = 10 * len(gained)
    reasons = []
    if gained:
        reasons.append(f"培养目标增益：新覆盖能力 {','.join(gained)}")
    else:
        reasons.append("培养目标增益：无新增能力")
    reasons.append(
        f"语言水平 {trainee.language_level} 级满足授课对象要求的 "
        f"{scenario.min_language_level} 级"
    )
    if site.country not in trainee.visited_countries:
        score += 3
        reasons.append(f"公平轮换：尚未赴{site.country}实践，优先体验新区域")
    rotation_bonus = max(0, 5 - trainee.completed_rotations)
    score += rotation_bonus
    reasons.append(
        f"公平轮换：已完成 {trainee.completed_rotations} 次轮换，轮换加分 {rotation_bonus}"
    )
    return Candidate(
        trainee_id=trainee.trainee_id,
        scenario_id=scenario.scenario_id,
        score=score,
        reasons=reasons,
    )


def generate_candidates(
    trainees: list,
    scenarios: list,
    sites: dict,
) -> tuple:
    """为每个课程场景生成候选名单；语言不达标者直接列入拒绝理由。"""
    candidates: dict = {}
    rejections: dict = {}
    for scenario in scenarios:
        site = sites[scenario.site_id]
        cands, rejects = [], []
        for trainee in trainees:
            if trainee.language_level < scenario.min_language_level:
                rejects.append(
                    f"{trainee.name}：语言水平 {trainee.language_level} 级低于要求的 "
                    f"{scenario.min_language_level} 级"
                )
                continue
            cands.append(score_candidate(trainee, scenario, site))
        cands.sort(key=lambda c: (-c.score, c.trainee_id))
        candidates[scenario.scenario_id] = cands
        rejections[scenario.scenario_id] = rejects
    return candidates, rejections


def greedy_assign(
    trainees: dict,
    scenarios: list,
    sites: dict,
    mentors: dict,
    existing: list,
    unavailable: list,
) -> tuple:
    """按候选得分贪心落位：最难安排的场景优先，冲突即跳过并记录理由。

    返回 (成功列表[(Placement, Candidate)], 未安排场景{scenario_id: [理由]})。
    """
    trainee_list = list(trainees.values())
    candidates, rejections = generate_candidates(trainee_list, scenarios, sites)
    placements = list(existing)
    assigned: list = []
    unassigned: dict = {}

    # 候选最少的场景优先安排，降低被挤占的概率
    ordered = sorted(scenarios, key=lambda s: (len(candidates[s.scenario_id]), s.scenario_id))
    for scenario in ordered:
        mentor = mentors[scenario.mentor_id]
        chosen = None
        skip_reasons = []
        for cand in candidates[scenario.scenario_id]:
            trainee = trainees[cand.trainee_id]
            placement = Placement(
                trainee_id=trainee.trainee_id,
                scenario_id=scenario.scenario_id,
                mentor_id=scenario.mentor_id,
                site_id=scenario.site_id,
                window=scenario.window,
            )
            conflicts = detect_conflicts(
                placement,
                trainee=trainee,
                scenario=scenario,
                mentor=mentor,
                placements=placements,
                unavailable=unavailable,
            )
            if conflicts:
                skip_reasons.append(
                    f"{trainee.name}：" + "；".join(c.detail for c in conflicts)
                )
                continue
            chosen = (placement, cand)
            break
        if chosen is None:
            reasons = list(rejections[scenario.scenario_id]) + skip_reasons
            unassigned[scenario.scenario_id] = reasons or ["无可用学员"]
            continue
        placements.append(chosen[0])
        assigned.append(chosen)
    return assigned, unassigned
