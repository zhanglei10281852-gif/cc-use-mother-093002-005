"""应用服务：统一维护合作点/导师/学员，生成并管理安排。

任何一方（学校、导师、学院侧学员资料）变更都会触发受影响在排人员的重新评估；
已开始的实践只记录变更提示，绝不静默改派；需要改派时必须显式“立新替旧”，
旧安排保留为“已被新方案替代”并留下关联。
"""
from __future__ import annotations

from datetime import datetime

from .clock import Clock
from .contracts import PracticumSiteVersion, TraineeProfile
from .domain import (
    Competency,
    CourseScenario,
    DateRange,
    LanguageRequirement,
    Mentor,
    PartnerSite,
    ReportScope,
    Role,
    Trainee,
)
from .incidents import IncidentRegistry
from .scheduler import (
    ACTIVE_STATUSES,
    Assignment,
    AssignmentStatus,
    Candidate,
    Plan,
    Scheduler,
)


class ServiceError(RuntimeError):
    pass


class PracticumService:
    def __init__(self, clock: Clock | None = None) -> None:
        self.clock = clock or Clock()
        self.sites: dict[str, PartnerSite] = {}
        self.mentors: dict[str, Mentor] = {}
        self.trainees: dict[str, Trainee] = {}
        self.assignments: dict[str, Assignment] = {}
        self.scheduler = Scheduler(self.sites, self.mentors, self.trainees, self.assignments)
        self.incidents = IncidentRegistry(self.sites, self.clock)
        self._seq = 0

    def _next_id(self, prefix: str) -> str:
        self._seq += 1
        return f"{prefix}-{self._seq:04d}"

    # ------------------------------------------------------------------
    # 合作点
    # ------------------------------------------------------------------

    def register_site(self, site_id: str, name: str, country: str,
                      windows: list[DateRange] | None = None,
                      scenarios: list[CourseScenario] | None = None,
                      report_scope: ReportScope | None = None) -> PartnerSite:
        if site_id in self.sites:
            raise ServiceError(f"合作点 {site_id} 已存在")
        site = PartnerSite(
            version=PracticumSiteVersion(site_id, name, 1),
            country=country, windows=list(windows or []),
            scenarios=list(scenarios or []), report_scope=report_scope,
        )
        self.sites[site_id] = site
        return site

    def revise_site(self, site_id: str, *,
                    windows: list[DateRange] | None = None,
                    scenarios: list[CourseScenario] | None = None,
                    report_scope: ReportScope | None | object = ...,
                    name: str | None = None) -> list[Assignment]:
        """学校侧变更：创建新版本（revision+1），随后触发重评估。"""
        old = self._site(site_id)
        new = PartnerSite(
            version=PracticumSiteVersion(site_id, name or old.version.display_name,
                                         old.revision + 1),
            country=old.country,
            windows=list(windows if windows is not None else old.windows),
            scenarios=list(scenarios if scenarios is not None else old.scenarios),
            report_scope=(old.report_scope if report_scope is ... else report_scope),  # type: ignore[arg-type]
        )
        self.sites[site_id] = new
        return self.reevaluate()

    # ------------------------------------------------------------------
    # 导师
    # ------------------------------------------------------------------

    def register_mentor(self, mentor_id: str, name: str, site_id: str, capacity: int,
                        language_requirements=frozenset(),
                        competencies=frozenset(),
                        unavailable: list[DateRange] | None = None) -> Mentor:
        self._site(site_id)
        if mentor_id in self.mentors:
            raise ServiceError(f"导师 {mentor_id} 已存在")
        mentor = Mentor(mentor_id, name, site_id, capacity, 1,
                        frozenset(language_requirements), frozenset(competencies),
                        list(unavailable or []))
        self.mentors[mentor_id] = mentor
        return mentor

    def revise_mentor(self, mentor_id: str, *, capacity: int | None = None,
                      language_requirements=None, competencies=None,
                      unavailable: list[DateRange] | None = None) -> list[Assignment]:
        """导师侧变更（容量收紧、新增不可用时段等）：修订号+1 并重评估。"""
        old = self._mentor(mentor_id)
        new = Mentor(
            mentor_id=old.mentor_id, name=old.name, site_id=old.site_id,
            capacity=capacity if capacity is not None else old.capacity,
            revision=old.revision + 1,
            language_requirements=(old.language_requirements
                                   if language_requirements is None else frozenset(language_requirements)),
            competencies=(old.competencies if competencies is None
                          else frozenset(competencies)),
            unavailable=list(old.unavailable if unavailable is None else unavailable),
        )
        self.mentors[mentor_id] = new
        return self.reevaluate()

    # ------------------------------------------------------------------
    # 学员
    # ------------------------------------------------------------------

    def register_trainee(self, trainee_id: str, name: str,
                         languages: dict | None = None,
                         acquired_competencies=None,
                         unavailable: list[DateRange] | None = None,
                         category: str = "已登记") -> Trainee:
        if trainee_id in self.trainees:
            raise ServiceError(f"学员 {trainee_id} 已存在")
        trainee = Trainee(
            profile=TraineeProfile(self._next_id("TR"), trainee_id, category),
            name=name, languages=dict(languages or {}),
            acquired_competencies=set(acquired_competencies or []),
            unavailable=list(unavailable or []),
        )
        self.trainees[trainee_id] = trainee
        return trainee

    def update_trainee(self, trainee_id: str, *, languages: dict | None = None,
                       acquired_competencies=None,
                       unavailable: list[DateRange] | None = None) -> list[Assignment]:
        """学院侧学员资料变更（语言成绩更正等），触发该学员相关安排重评估。"""
        t = self._trainee(trainee_id)
        if languages is not None:
            t.languages = dict(languages)
        if acquired_competencies is not None:
            t.acquired_competencies = set(acquired_competencies)
        if unavailable is not None:
            t.unavailable = list(unavailable)
        return [a for a in self.reevaluate() if a.trainee_id == trainee_id]

    # ------------------------------------------------------------------
    # 候选方案与安排
    # ------------------------------------------------------------------

    def plan(self, trainee_ids: list[str] | None = None) -> Plan:
        return self.scheduler.generate_plan(trainee_ids)

    def propose(self, trainee_id: str, candidate: Candidate | None = None) -> Assignment:
        """依据候选（默认取得分最高者）建立安排；落库前再次执行硬约束。"""
        trainee = self._trainee(trainee_id)
        if candidate is None:
            candidate = self.scheduler.best_candidate(trainee_id)
            if candidate is None:
                raise ServiceError(f"学员 {trainee_id} 当前没有可行候选")
        site, mentor = self._site(candidate.site_id), self._mentor(candidate.mentor_id)
        # 与候选生成一致：忽略该学员本人待重新评估安排的占用
        exclude = frozenset(
            a.assignment_id for a in self.assignments.values()
            if a.trainee_id == trainee_id
            and a.status == AssignmentStatus.NEEDS_REASSESSMENT
        )
        reasons = self.scheduler.hard_check(
            trainee, site, mentor, candidate.scenario_id, candidate.window,
            exclude=exclude,
        )
        if reasons:
            raise ServiceError("候选已不再可行：" + "；".join(reasons))

        scenario = next(s for s in site.scenarios if s.scenario_id == candidate.scenario_id)
        now = self.clock.now()
        aid = self._next_id("AS")
        assignment = Assignment(
            assignment_id=aid, trainee_id=trainee_id,
            site_id=site.site_id, site_revision=site.revision,
            mentor_id=mentor.mentor_id, mentor_revision=mentor.revision,
            scenario_id=scenario.scenario_id, window=candidate.window,
            offered_competencies=frozenset(scenario.competencies),
            expected_gain=candidate.expected_gain,
            score=candidate.score, explanation=list(candidate.explanation),
            created_at=now, updated_at=now,
        )
        assignment.log.append(
            f"{now:%Y-%m-%d %H:%M} 生成候选安排（得分 {candidate.score:.1f}）："
            f"{site.site_id}/{mentor.name}/{scenario.title}/{candidate.window.start}~{candidate.window.end}"
        )
        self.assignments[aid] = assignment
        return assignment

    def confirm(self, assignment_id: str, party: Role) -> bool:
        a = self._assignment(assignment_id)
        return a.confirm(party, self.clock.now())

    def start(self, assignment_id: str) -> None:
        self._assignment(assignment_id).start(self.clock.now())

    def complete(self, assignment_id: str) -> None:
        self._assignment(assignment_id).complete(self.clock.now())

    def replace_assignment(self, old_id: str, new_candidate: Candidate | None = None) -> Assignment:
        """显式改派：旧安排（未开始）标记为被替代并关联新安排，绝不静默。"""
        old = self._assignment(old_id)
        if old.status == AssignmentStatus.STARTED:
            raise ServiceError("实践已开始，不能改派；请通过事件流程处置")
        if not old.is_active():
            raise ServiceError(f"安排 {old_id} 状态为 {old.status.value}，无需改派")
        # 先释放旧安排占用的窗口/容量，再对新候选做硬约束自检
        now = self.clock.now()
        old.status = AssignmentStatus.SUPERSEDED
        old.updated_at = now
        new = self.propose(old.trainee_id, new_candidate)
        old.superseded_by = new.assignment_id
        old.log.append(f"{now:%Y-%m-%d %H:%M} 显式改派，由 {new.assignment_id} 接替")
        new.log.append(f"{now:%Y-%m-%d %H:%M} 接替改派自 {old.assignment_id}")
        return new

    def cancel(self, assignment_id: str, reason: str) -> None:
        a = self._assignment(assignment_id)
        if a.status == AssignmentStatus.STARTED:
            raise ServiceError("实践已开始，不能取消；请通过事件流程处置")
        now = self.clock.now()
        a.status = AssignmentStatus.CANCELLED
        a.updated_at = now
        a.log.append(f"{now:%Y-%m-%d %H:%M} 取消：{reason}")

    def reevaluate(self) -> list[Assignment]:
        return self.scheduler.reevaluate_all(self.clock.now())

    # ------------------------------------------------------------------
    # 内部查找
    # ------------------------------------------------------------------

    def _site(self, site_id: str) -> PartnerSite:
        try:
            return self.sites[site_id]
        except KeyError:
            raise ServiceError(f"未知合作点: {site_id}") from None

    def _mentor(self, mentor_id: str) -> Mentor:
        try:
            return self.mentors[mentor_id]
        except KeyError:
            raise ServiceError(f"未知导师: {mentor_id}") from None

    def _trainee(self, trainee_id: str) -> Trainee:
        try:
            return self.trainees[trainee_id]
        except KeyError:
            raise ServiceError(f"未知学员: {trainee_id}") from None

    def _assignment(self, assignment_id: str) -> Assignment:
        try:
            return self.assignments[assignment_id]
        except KeyError:
            raise ServiceError(f"未知安排: {assignment_id}") from None
