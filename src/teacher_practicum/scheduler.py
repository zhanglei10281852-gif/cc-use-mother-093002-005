"""候选安排生成与冲突评估。

硬约束（任一不满足即不可作为候选）：
  1. 安排窗口必须落在合作学校的某个校历窗口内；
  2. 学员语言水平达到课程场景要求，并满足导师提出的语言要求；
  3. 导师在该窗口内无不可用时段，学员同理；
  4. 同一导师在重叠窗口内的在排学员数不得超过容量（杜绝容量重复占用）；
  5. 同一学员不得同时落入两个重叠窗口。

软目标（用于可解释打分）：
  - 培养目标：优先补齐学员尚未覆盖的能力（权重最高）；
  - 公平轮换：导师负荷越满越不优先，避免同一学员重复跟同一导师/同一学校。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from .domain import (
    Competency,
    DateRange,
    Mentor,
    PartnerSite,
    Role,
    Trainee,
)


class AssignmentStatus(str, Enum):
    PROPOSED = "待确认"
    CONFIRMED = "已确认待出发"
    STARTED = "实践进行中"
    COMPLETED = "已完成"
    NEEDS_REASSESSMENT = "待重新评估"
    SUPERSEDED = "已被新方案替代"
    CANCELLED = "已取消"


ACTIVE_STATUSES = {
    AssignmentStatus.PROPOSED,
    AssignmentStatus.CONFIRMED,
    AssignmentStatus.STARTED,
    AssignmentStatus.NEEDS_REASSESSMENT,
}

CONFIRMING_PARTIES = (Role.SCHOOL, Role.MENTOR, Role.COLLEGE)


@dataclass
class Assignment:
    assignment_id: str
    trainee_id: str
    site_id: str
    site_revision: int
    mentor_id: str
    mentor_revision: int
    scenario_id: str
    window: DateRange
    offered_competencies: frozenset[Competency]
    expected_gain: frozenset[Competency]
    score: float
    explanation: list[str]
    status: AssignmentStatus = AssignmentStatus.PROPOSED
    confirmations: dict[Role, datetime] = field(default_factory=dict)
    reassessment_reasons: list[str] = field(default_factory=list)
    change_notices: list[str] = field(default_factory=list)
    revision_notes: list[str] = field(default_factory=list)
    superseded_by: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    log: list[str] = field(default_factory=list)

    def pending_parties(self) -> list[Role]:
        return [p for p in CONFIRMING_PARTIES if p not in self.confirmations]

    def confirm(self, party: Role, now: datetime) -> bool:
        """返回是否在本次确认后集齐三方。"""
        if party not in CONFIRMING_PARTIES:
            raise ValueError(f"无权确认安排的角色: {party}")
        if self.status not in (AssignmentStatus.PROPOSED, AssignmentStatus.CONFIRMED):
            raise ValueError(f"当前状态 {self.status.value} 不可确认")
        if party in self.confirmations:
            return False
        self.confirmations[party] = now
        self.updated_at = now
        self.log.append(f"{now:%Y-%m-%d %H:%M} {party.value} 确认")
        if not self.pending_parties():
            self.status = AssignmentStatus.CONFIRMED
            self.log.append(f"{now:%Y-%m-%d %H:%M} 三方确认集齐，安排成立")
            return True
        return False

    def start(self, now: datetime) -> None:
        if self.status != AssignmentStatus.CONFIRMED:
            raise ValueError("只有三方确认完毕的安排可以开始实践")
        self.status = AssignmentStatus.STARTED
        self.started_at = now
        self.updated_at = now
        self.log.append(f"{now:%Y-%m-%d %H:%M} 实践开始，此后变更不得静默改派")

    def complete(self, now: datetime) -> None:
        if self.status != AssignmentStatus.STARTED:
            raise ValueError("只有进行中的实践可以办结")
        self.status = AssignmentStatus.COMPLETED
        self.completed_at = now
        self.updated_at = now
        self.log.append(f"{now:%Y-%m-%d %H:%M} 实践完成")

    def is_active(self) -> bool:
        return self.status in ACTIVE_STATUSES


@dataclass
class Candidate:
    trainee_id: str
    site_id: str
    site_revision: int
    mentor_id: str
    mentor_revision: int
    scenario_id: str
    window: DateRange
    expected_gain: frozenset[Competency]
    score: float
    explanation: list[str]


@dataclass
class Plan:
    candidates: dict[str, list[Candidate]]  # trainee_id -> 按分数降序
    infeasible: dict[str, list[str]]       # trainee_id -> 每个尝试对象的关键拒绝原因


class Scheduler:
    def __init__(self, sites: dict[str, PartnerSite], mentors: dict[str, Mentor],
                 trainees: dict[str, Trainee], assignments: dict[str, Assignment]):
        self.sites = sites
        self.mentors = mentors
        self.trainees = trainees
        self.assignments = assignments

    # ------------------------------------------------------------------
    # 现状度量
    # ------------------------------------------------------------------

    def _active_assignments(self) -> list[Assignment]:
        return [a for a in self.assignments.values() if a.is_active()]

    def mentor_load(self, mentor_id: str, window: DateRange,
                    exclude: frozenset[str] | str | None = None) -> int:
        """同一导师在与 window 重叠区间内的在排人数。"""
        excluded = {exclude} if isinstance(exclude, str) else (exclude or set())
        return sum(
            1
            for a in self._active_assignments()
            if a.assignment_id not in excluded
            and a.mentor_id == mentor_id
            and a.window.overlaps(window)
        )

    def trainee_busy(self, trainee_id: str, window: DateRange,
                     exclude: frozenset[str] | str | None = None) -> bool:
        excluded = {exclude} if isinstance(exclude, str) else (exclude or set())
        return any(
            a.assignment_id not in excluded
            and a.trainee_id == trainee_id
            and a.window.overlaps(window)
            for a in self._active_assignments()
        )

    def prior_pairs(self, trainee_id: str) -> tuple[set[str], set[str]]:
        """该学员历史/在排已接触过的导师与学校（用于公平轮换）。"""
        mentors, sites = set(), set()
        for a in self.assignments.values():
            if a.trainee_id == trainee_id and a.status in (
                AssignmentStatus.CONFIRMED,
                AssignmentStatus.STARTED,
                AssignmentStatus.COMPLETED,
            ):
                mentors.add(a.mentor_id)
                sites.add(a.site_id)
        return mentors, sites

    # ------------------------------------------------------------------
    # 硬约束
    # ------------------------------------------------------------------

    def hard_check(self, trainee: Trainee, site: PartnerSite, mentor: Mentor,
                   scenario_id: str, window: DateRange,
                   exclude: str | None = None) -> list[str]:
        reasons: list[str] = []

        if window not in site.windows:
            reasons.append(f"窗口 {window.start}~{window.end} 不在 {site.site_id} 的校历内")
        scenario = next((s for s in site.scenarios if s.scenario_id == scenario_id), None)
        if scenario is None:
            reasons.append(f"学校 {site.site_id}（r{site.revision}）不提供场景 {scenario_id}")
            return reasons  # 后续检查依赖场景，直接返回

        if not scenario.language_requirement.satisfied_by(trainee.languages):
            req = scenario.language_requirement
            actual = trainee.languages.get(req.language)
            reasons.append(
                f"语言不匹配：场景“{scenario.title}”要求 {req.language.value} {req.min_level}，"
                f"学员实际 {actual or '未掌握'}"
            )
        for req in mentor.language_requirements:
            if not req.satisfied_by(trainee.languages):
                actual = trainee.languages.get(req.language)
                reasons.append(
                    f"语言不匹配：导师 {mentor.name} 要求 {req.language.value} {req.min_level}，"
                    f"学员实际 {actual or '未掌握'}"
                )
        if not scenario.competencies & mentor.competencies:
            reasons.append(
                f"导师 {mentor.name} 不具备场景“{scenario.title}”所需的任何能力"
            )
        if not trainee.available_during(window):
            reasons.append("学员在该窗口存在不可用时段")
        if not mentor.available_during(window):
            reasons.append(f"导师 {mentor.name} 在该窗口存在不可用时段")
        load = self.mentor_load(mentor.mentor_id, window, exclude)
        if load >= mentor.capacity:
            reasons.append(
                f"导师 {mentor.name} 容量将被重复占用（{load}/{mentor.capacity}）"
            )
        if self.trainee_busy(trainee.trainee_id, window, exclude):
            reasons.append("学员在此窗口已有重叠安排，不能同时落入两个校历窗口")
        return reasons

    # ------------------------------------------------------------------
    # 候选生成与评分
    # ------------------------------------------------------------------

    def _score(self, trainee: Trainee, site: PartnerSite, mentor: Mentor,
               scenario_id: str, window: DateRange,
               exclude: frozenset[str] | None = None
               ) -> tuple[float, frozenset[Competency], list[str]]:
        scenario = next(s for s in site.scenarios if s.scenario_id == scenario_id)
        gain = frozenset(scenario.competencies - trainee.acquired_competencies)
        prior_mentors, prior_sites = self.prior_pairs(trainee.trainee_id)
        load = self.mentor_load(mentor.mentor_id, window, exclude=exclude)

        # 培养目标：每多补一项能力 +25
        coverage_points = 25 * len(gain)
        # 公平轮换：当前负荷率越高越不优先；重复跟同导师/同学校扣分
        load_points = -15 * (load / mentor.capacity)
        rotation_points = -8 if mentor.mentor_id in prior_mentors else 0
        site_points = -4 if site.site_id in prior_sites else 0
        score = coverage_points + load_points + rotation_points + site_points

        explanation = [
            f"能力补齐 {len(gain)} 项（+{coverage_points}）："
            + ("、".join(c.value for c in gain) or "无新增"),
            f"导师负荷 {load}/{mentor.capacity}（{load_points:+.1f}）",
            (f"曾跟随导师 {mentor.name}，轮换扣分（{rotation_points:+d}）"
             if rotation_points else f"未跟随过导师 {mentor.name}，利于轮换（+0）"),
            (f"曾派往 {site.site_id}，轮换扣分（{site_points:+d}）"
             if site_points else f"未派往过 {site.site_id}，利于轮换（+0）"),
            f"综合得分 {score:.1f}",
        ]
        return score, gain, explanation

    def generate_plan(self, trainee_ids: list[str] | None = None) -> Plan:
        candidates: dict[str, list[Candidate]] = {}
        infeasible: dict[str, list[str]] = {}
        for tid in trainee_ids or list(self.trainees):
            trainee = self.trainees[tid]
            # 寻找（新）方案时，忽略该学员本人待重新评估安排的占用，
            # 否则失效安排会永久阻塞替代候选；对其他学员的候选仍保守计入。
            own_reassessing = frozenset(
                a.assignment_id for a in self._active_assignments()
                if a.trainee_id == tid
                and a.status == AssignmentStatus.NEEDS_REASSESSMENT
            )
            ranked: list[Candidate] = []
            blockers: list[str] = []
            for site in self.sites.values():
                for scenario in site.scenarios:
                    for window in site.windows:
                        for mentor in self.mentors.values():
                            if mentor.site_id != site.site_id:
                                continue
                            reasons = self.hard_check(
                                trainee, site, mentor, scenario.scenario_id, window,
                                exclude=own_reassessing,
                            )
                            if reasons:
                                blockers.append(
                                    f"[{site.site_id}/{mentor.mentor_id}/"
                                    f"{scenario.scenario_id}/{window.start}] " + "；".join(reasons)
                                )
                                continue
                            score, gain, expl = self._score(
                                trainee, site, mentor, scenario.scenario_id, window,
                                exclude=own_reassessing,
                            )
                            ranked.append(Candidate(
                                trainee_id=tid, site_id=site.site_id,
                                site_revision=site.revision, mentor_id=mentor.mentor_id,
                                mentor_revision=mentor.revision,
                                scenario_id=scenario.scenario_id, window=window,
                                expected_gain=gain, score=score, explanation=expl,
                            ))
            ranked.sort(key=lambda c: (-c.score, c.site_id, c.mentor_id,
                                       c.scenario_id, c.window.start.isoformat()))
            if ranked:
                candidates[tid] = ranked
            else:
                infeasible[tid] = self._condense_blockers(blockers)
        return Plan(candidates, infeasible)

    @staticmethod
    def _condense_blockers(blockers: list[str]) -> list[str]:
        """同一根因只保留一条代表说明，避免日报刷屏。"""
        seen: set[str] = set()
        out: list[str] = []
        for b in blockers:
            root = b.split("] ", 1)[-1]
            if root not in seen:
                seen.add(root)
                out.append(b)
        return out

    def best_candidate(self, trainee_id: str) -> Candidate | None:
        plan = self.generate_plan([trainee_id])
        return plan.candidates.get(trainee_id, [None])[0]

    # ------------------------------------------------------------------
    # 变更后的重新评估
    # ------------------------------------------------------------------

    def reevaluate_all(self, now: datetime) -> list[Assignment]:
        """重新评估所有在排安排，返回状态发生变化的安排。

        已开始的实践绝不改状态、不改派；若数据变更使其出现隐患，
        只追加一条变更提示，由实践办公室人工处置。
        资料修订号更新但硬约束仍通过时，仅记录版本信息，不阻塞流程。
        """
        changed: list[Assignment] = []
        for a in self._active_assignments():
            site = self.sites.get(a.site_id)
            mentor = self.mentors.get(a.mentor_id)
            trainee = self.trainees.get(a.trainee_id)
            if site is None or mentor is None or trainee is None:
                continue
            # 实质冲突：硬约束（排除自身占用后）
            reasons = self.hard_check(
                trainee, site, mentor, a.scenario_id, a.window,
                exclude=a.assignment_id,
            )
            # 版本更新仅作信息提示
            notes: list[str] = []
            if site.revision != a.site_revision:
                notes.append(f"合作点资料已更新到 r{site.revision}（安排基于 r{a.site_revision}）")
            if mentor.revision != a.mentor_revision:
                notes.append(f"导师资料已更新到 r{mentor.revision}（安排基于 r{a.mentor_revision}）")
            for n in notes:
                if n not in a.revision_notes:
                    a.revision_notes.append(n)

            if a.status == AssignmentStatus.STARTED:
                notice = "；".join(reasons)
                if reasons and notice not in a.change_notices:
                    a.change_notices.append(notice)
                    a.updated_at = now
                    a.log.append(f"{now:%Y-%m-%d %H:%M} 变更提示（实践进行中，不自动改派）：{notice}")
                    changed.append(a)
                continue

            if reasons:
                if a.status != AssignmentStatus.NEEDS_REASSESSMENT or a.reassessment_reasons != reasons:
                    a.status = AssignmentStatus.NEEDS_REASSESSMENT
                    a.reassessment_reasons = reasons
                    a.updated_at = now
                    a.log.append(f"{now:%Y-%m-%d %H:%M} 触发重新评估：{'；'.join(reasons)}")
                    changed.append(a)
            elif a.status == AssignmentStatus.NEEDS_REASSESSMENT:
                a.status = AssignmentStatus.PROPOSED
                a.reassessment_reasons = []
                a.updated_at = now
                a.log.append(f"{now:%Y-%m-%d %H:%M} 隐患消除，回到待确认队列")
                changed.append(a)
        return changed

    def pairwise_conflicts(self) -> list[str]:
        """独立于创建时校验的全量冲突扫描（防御性，供日报使用）。"""
        problems: list[str] = []
        active = self._active_assignments()
        for i, a in enumerate(active):
            for b in active[i + 1:]:
                if a.window.overlaps(b.window):
                    if a.trainee_id == b.trainee_id:
                        problems.append(
                            f"学员 {a.trainee_id} 同时落入两个窗口：{a.assignment_id} 与 {b.assignment_id}"
                        )
                    if a.mentor_id == b.mentor_id:
                        mentor = self.mentors[a.mentor_id]
                        problems.append(
                            f"导师 {a.mentor_id} 重叠带教超过记录：{a.assignment_id} 与 {b.assignment_id}"
                            f"（容量 {mentor.capacity}）"
                        )
        return problems
