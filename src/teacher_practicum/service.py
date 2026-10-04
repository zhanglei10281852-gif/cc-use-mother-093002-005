"""实践安排与在岗支持服务门面：统一维护主数据、生成安排、驱动确认与事件处置。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .arrangements import (
    ACTIVE_STATUSES,
    Arrangement,
    ArrangementStatus,
    Party,
)
from .clock import Clock, ManualClock, SystemClock
from .incidents import (
    SLA_HOURS,
    Case,
    CaseStatus,
    IncidentType,
    Report,
    Escalation,
    compute_visibility,
    new_case,
)
from .models import (
    CourseScenario,
    Level,
    Mentor,
    PartnerSite,
    ReportingPolicy,
    Trainee,
    UnavailableWindow,
    Window,
)
from .scheduling import Placement, detect_conflicts, greedy_assign


class StartedPracticumError(RuntimeError):
    """已开始的实践禁止静默改派。"""


class PracticumService:
    def __init__(self, clock: Clock | None = None) -> None:
        self.clock: Clock = clock or SystemClock()
        self.sites: dict = {}
        self.mentors: dict = {}
        self.scenarios: dict = {}
        self.trainees: dict = {}
        self.unavailable: list = []
        self.arrangements: dict = {}
        self.cases: dict = {}
        self.last_unassigned: dict = {}
        self._arrangement_seq = 0
        self._case_seq = 0

    # ------------------------------------------------------------------
    # 主数据维护
    # ------------------------------------------------------------------
    def add_site(self, site: PartnerSite) -> None:
        self.sites[site.site_id] = site

    def add_mentor(self, mentor: Mentor) -> None:
        if mentor.site_id not in self.sites:
            raise ValueError(f"导师所属合作点 {mentor.site_id} 不存在")
        self.mentors[mentor.mentor_id] = mentor

    def add_scenario(self, scenario: CourseScenario) -> None:
        if scenario.site_id not in self.sites:
            raise ValueError(f"场景所属合作点 {scenario.site_id} 不存在")
        if scenario.mentor_id not in self.mentors:
            raise ValueError(f"场景指定导师 {scenario.mentor_id} 不存在")
        self.scenarios[scenario.scenario_id] = scenario

    def add_trainee(self, trainee: Trainee) -> None:
        self.trainees[trainee.trainee_id] = trainee

    def add_unavailable_window(self, entry: UnavailableWindow) -> None:
        self.unavailable.append(entry)

        def affected(arr: Arrangement) -> bool:
            return (entry.owner_kind, entry.owner_id) in (
                ("trainee", arr.trainee_id),
                ("mentor", arr.mentor_id),
                ("site", arr.site_id),
            )

        self._reevaluate(
            f"新增不可用时段（{entry.owner_kind}:{entry.owner_id} {entry.reason}）", affected
        )

    # ------------------------------------------------------------------
    # 候选安排生成与三方确认
    # ------------------------------------------------------------------
    def _active_arrangements(self) -> list:
        return [a for a in self.arrangements.values() if a.status in ACTIVE_STATUSES]

    def _placement_of(self, arr: Arrangement) -> Placement:
        return Placement(
            trainee_id=arr.trainee_id,
            scenario_id=arr.scenario_id,
            mentor_id=arr.mentor_id,
            site_id=arr.site_id,
            window=arr.window,
            arrangement_id=arr.arrangement_id,
        )

    def generate_plan(self) -> tuple:
        """生成可解释候选安排；返回 (新建安排列表, 未安排场景及理由)。"""
        existing = [self._placement_of(a) for a in self._active_arrangements()]
        scenarios = sorted(self.scenarios.values(), key=lambda s: s.scenario_id)
        assigned, unassigned = greedy_assign(
            trainees=self.trainees,
            scenarios=scenarios,
            sites=self.sites,
            mentors=self.mentors,
            existing=existing,
            unavailable=self.unavailable,
        )
        now = self.clock.now()
        created = []
        for placement, candidate in assigned:
            self._arrangement_seq += 1
            arr = Arrangement(
                arrangement_id=f"A-{self._arrangement_seq:04d}",
                trainee_id=placement.trainee_id,
                scenario_id=placement.scenario_id,
                mentor_id=placement.mentor_id,
                site_id=placement.site_id,
                window=placement.window,
                status=ArrangementStatus.PENDING,
                explanation=list(candidate.reasons),
            )
            arr.history.append(f"{now.isoformat()} 生成候选安排，等待三方确认")
            self.arrangements[arr.arrangement_id] = arr
            created.append(arr)
        self.last_unassigned = unassigned
        return created, unassigned

    def confirm(self, arrangement_id: str, party: Party, note: str = "") -> Arrangement:
        arr = self._arrangement(arrangement_id)
        arr.confirm(party, self.clock.now(), note)
        return arr

    def reject(self, arrangement_id: str, party: Party, note: str = "") -> Arrangement:
        arr = self._arrangement(arrangement_id)
        arr.reject(party, self.clock.now(), note)
        return arr

    def start(self, arrangement_id: str) -> Arrangement:
        arr = self._arrangement(arrangement_id)
        arr.start(self.clock.now())
        return arr

    def complete(self, arrangement_id: str) -> Arrangement:
        arr = self._arrangement(arrangement_id)
        arr.complete(self.clock.now())
        trainee = self.trainees[arr.trainee_id]
        scenario = self.scenarios[arr.scenario_id]
        site = self.sites[arr.site_id]
        trainee.covered_competencies |= set(scenario.competencies)
        trainee.completed_rotations += 1
        trainee.visited_countries.add(site.country)
        return arr

    # ------------------------------------------------------------------
    # 变更触发重新评估
    # ------------------------------------------------------------------
    def set_mentor_capacity(self, mentor_id: str, capacity: int) -> None:
        mentor = self.mentors[mentor_id]
        if capacity < 1:
            raise ValueError("导师容量至少为 1")
        mentor.capacity = capacity
        self._reevaluate(
            f"导师 {mentor.name} 容量调整为 {capacity}",
            lambda arr: arr.mentor_id == mentor_id,
        )

    def reschedule_scenario(self, scenario_id: str, window: Window) -> None:
        scenario = self.scenarios[scenario_id]
        scenario.window = window
        for arr in self._active_arrangements():
            if arr.scenario_id == scenario_id:
                arr.window = window
        self._reevaluate(
            f"场景 {scenario.title} 调整至 {window.start}~{window.end}",
            lambda arr: arr.scenario_id == scenario_id,
        )

    def set_trainee_language_level(self, trainee_id: str, level: int) -> None:
        trainee = self.trainees[trainee_id]
        trainee.language_level = level
        self._reevaluate(
            f"学员 {trainee.name} 语言水平更新为 {level} 级",
            lambda arr: arr.trainee_id == trainee_id,
        )

    def _reevaluate(self, reason: str, affected) -> None:
        """任何一方变更后，仅对受影响人员重新评估；进行中的实践只记录不改派。"""
        now = self.clock.now()
        placements = [self._placement_of(a) for a in self._active_arrangements()]
        for arr in self._active_arrangements():
            if not affected(arr):
                continue
            trainee = self.trainees[arr.trainee_id]
            scenario = self.scenarios[arr.scenario_id]
            mentor = self.mentors[arr.mentor_id]
            conflicts = detect_conflicts(
                self._placement_of(arr),
                trainee=trainee,
                scenario=scenario,
                mentor=mentor,
                placements=placements,
                unavailable=self.unavailable,
                ignore_arrangement_id=arr.arrangement_id,
            )
            if arr.status == ArrangementStatus.STARTED:
                if conflicts:
                    arr.conflicts = conflicts
                    arr.history.append(
                        f"{now.isoformat()} 重新评估（{reason}）：进行中实践出现冲突，"
                        "需人工处置，不做静默改派"
                    )
                continue
            if conflicts:
                arr.mark_conflicted(conflicts, now, reason)
            elif arr.status == ArrangementStatus.CONFLICTED:
                arr.clear_conflicts(now, f"{reason}，冲突已消除")
            elif arr.status in (ArrangementStatus.PENDING, ArrangementStatus.CONFIRMED):
                arr.reset_confirmations(now, reason)
                arr.status = ArrangementStatus.PENDING

    # ------------------------------------------------------------------
    # 改派
    # ------------------------------------------------------------------
    def reassign_trainee(
        self,
        arrangement_id: str,
        new_trainee_id: str,
        *,
        reason: str = "",
        actor: str = "",
    ) -> Arrangement:
        """改派学员。已开始的实践必须显式说明理由与操作人，且全程留痕。"""
        arr = self._arrangement(arrangement_id)
        if new_trainee_id not in self.trainees:
            raise ValueError(f"学员 {new_trainee_id} 不存在")
        if arr.status == ArrangementStatus.STARTED and not (reason and actor):
            raise StartedPracticumError(
                "已开始的实践不能静默改派：须提供操作人与理由，并重新走三方确认"
            )
        now = self.clock.now()
        old = arr.trainee_id
        arr.trainee_id = new_trainee_id
        if arr.status in (ArrangementStatus.STARTED, ArrangementStatus.CONFIRMED,
                          ArrangementStatus.PENDING, ArrangementStatus.CONFLICTED):
            arr.reset_confirmations(now, f"改派 {old} -> {new_trainee_id}")
            arr.status = ArrangementStatus.PENDING
        if reason or actor:
            arr.history.append(f"{now.isoformat()} 显式改派：操作人 {actor}，理由 {reason}")
        self._reevaluate(
            f"安排 {arrangement_id} 改派学员",
            lambda a: a.arrangement_id == arrangement_id,
        )
        return arr

    # ------------------------------------------------------------------
    # 事件：上报、去重、处置、复盘、逾期升级
    # ------------------------------------------------------------------
    def report_incident(
        self,
        incident_type: IncidentType,
        level: Level,
        trainee_id: str,
        description: str,
        reporter: str,
        occurred_on: str = "",
        arrangement_id: str = "",
    ) -> tuple:
        """上报事件；同一学员同日同类的重复上报归并到既有案件。"""
        if trainee_id not in self.trainees:
            raise ValueError(f"学员 {trainee_id} 不存在")
        now = self.clock.now()
        occurred = occurred_on or now.date().isoformat()
        fingerprint = (incident_type, trainee_id, occurred)
        for case in self.cases.values():
            if not case.is_closed and case.fingerprint == fingerprint:
                case.add_report(Report(reporter, description, now.isoformat()))
                return case, False

        site_id = ""
        if arrangement_id:
            site_id = self._arrangement(arrangement_id).site_id
        else:
            for arr in self._active_arrangements():
                if arr.trainee_id == trainee_id:
                    arrangement_id = arr.arrangement_id
                    site_id = arr.site_id
                    break
        self._case_seq += 1
        case = new_case(
            case_id=f"C-{self._case_seq:04d}",
            incident_type=incident_type,
            level=level,
            trainee_id=trainee_id,
            site_id=site_id,
            occurred_on=occurred,
            arrangement_id=arrangement_id,
            first_report=Report(reporter, description, now.isoformat()),
            now=now,
        )
        self.cases[case.case_id] = case
        return case, True

    def case_visibility(self, case_id: str) -> set:
        case = self._case(case_id)
        site = self.sites.get(case.site_id)
        policy = site.reporting_policy if site else ReportingPolicy()
        return compute_visibility(case.incident_type, case.level, policy)

    def acknowledge_case(self, case_id: str) -> Case:
        case = self._case(case_id)
        case.acknowledge(self.clock.now())
        return case

    def resolve_case(self, case_id: str, measures: str) -> Case:
        case = self._case(case_id)
        case.resolve(self.clock.now(), measures)
        return case

    def retrospect_case(self, case_id: str, summary: str) -> Case:
        case = self._case(case_id)
        case.complete_retrospective(self.clock.now(), summary)
        return case

    def close_case(self, case_id: str) -> Case:
        case = self._case(case_id)
        case.close(self.clock.now())
        return case

    def tick(self) -> list:
        """以可控制时钟检查逾期案件并升级；返回本次升级的案件。"""
        now = self.clock.now()
        escalated = []
        for case in self.cases.values():
            if case.status not in (CaseStatus.OPEN, CaseStatus.ACKNOWLEDGED):
                continue
            if case.level >= Level.CRITICAL:
                continue
            if now > datetime.fromisoformat(case.due_at):
                old = case.level
                case.level = Level(old + 1)
                case.escalations.append(
                    Escalation(int(old), int(case.level), now.isoformat(), "超过处置时限自动升级")
                )
                case.due_at = (now + timedelta(hours=SLA_HOURS[case.level])).isoformat()
                case.updated_at = now.isoformat()
                escalated.append(case)
        return escalated

    def advance_clock(self, **kwargs) -> list:
        """推进手动时钟并触发逾期检查（仅 ManualClock 可用）。"""
        if not isinstance(self.clock, ManualClock):
            raise TypeError("仅手动时钟可以推进")
        self.clock.advance(**kwargs)
        return self.tick()

    # ------------------------------------------------------------------
    # 汇总与持久化
    # ------------------------------------------------------------------
    def daily_summary(self) -> dict:
        from .reporting import build_daily_summary

        return build_daily_summary(self)

    def to_snapshot(self) -> dict:
        data = {
            "sites": [s.to_dict() for s in self.sites.values()],
            "mentors": [m.to_dict() for m in self.mentors.values()],
            "scenarios": [s.to_dict() for s in self.scenarios.values()],
            "trainees": [t.to_dict() for t in self.trainees.values()],
            "unavailable": [u.to_dict() for u in self.unavailable],
            "arrangements": [a.to_dict() for a in self.arrangements.values()],
            "cases": [c.to_dict() for c in self.cases.values()],
            "last_unassigned": self.last_unassigned,
            "arrangement_seq": self._arrangement_seq,
            "case_seq": self._case_seq,
        }
        if isinstance(self.clock, ManualClock):
            data["clock_now"] = self.clock.now().isoformat()
        return data

    @classmethod
    def from_snapshot(cls, data: dict, clock: Clock | None = None) -> "PracticumService":
        if clock is None and data.get("clock_now"):
            clock = ManualClock(datetime.fromisoformat(data["clock_now"]))
        service = cls(clock=clock)
        for raw in data["sites"]:
            service.sites[raw["site_id"]] = PartnerSite.from_dict(raw)
        for raw in data["mentors"]:
            service.mentors[raw["mentor_id"]] = Mentor.from_dict(raw)
        for raw in data["scenarios"]:
            service.scenarios[raw["scenario_id"]] = CourseScenario.from_dict(raw)
        for raw in data["trainees"]:
            service.trainees[raw["trainee_id"]] = Trainee.from_dict(raw)
        service.unavailable = [UnavailableWindow.from_dict(u) for u in data["unavailable"]]
        for raw in data["arrangements"]:
            service.arrangements[raw["arrangement_id"]] = Arrangement.from_dict(raw)
        for raw in data["cases"]:
            service.cases[raw["case_id"]] = Case.from_dict(raw)
        service.last_unassigned = dict(data["last_unassigned"])
        service._arrangement_seq = data["arrangement_seq"]
        service._case_seq = data["case_seq"]
        return service

    # ------------------------------------------------------------------
    def _arrangement(self, arrangement_id: str) -> Arrangement:
        try:
            return self.arrangements[arrangement_id]
        except KeyError:
            raise KeyError(f"安排 {arrangement_id} 不存在") from None

    def _case(self, case_id: str) -> Case:
        try:
            return self.cases[case_id]
        except KeyError:
            raise KeyError(f"案件 {case_id} 不存在") from None
