"""请假 / 教学事故 / 安全事件的案件管理。

规则：
  * 事件按级别限定可见范围；合作学校可通过 ReportScope 扩大某级别以上事件的上报范围；
  * 同一人、同一类型、同一发生时段的重复上报只保留一个案件，后续上报并案留痕；
  * 逾期未受理/未处置由可控时钟触发升级，升级会扩大可见范围并写入时间线；
  * 教学事故与安全事件必须完成处置与复盘才能办结；
  * 未办结案件即“中断恢复后仍需跟进”的事项，由日报统一呈现。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum

from .domain import EventLevel, PartnerSite, Role


class IncidentKind(str, Enum):
    LEAVE = "请假"
    TEACHING = "教学事故"
    SAFETY = "安全事件"


class CaseStatus(str, Enum):
    OPEN = "待受理"
    HANDLING = "处置中"
    ESCALATED = "已逾期升级"
    REVIEWING = "待复盘"
    CLOSED = "已办结"


# 各级别默认可见范围
_BASE_VISIBILITY: dict[EventLevel, frozenset[Role]] = {
    EventLevel.LOW: frozenset({Role.COLLEGE, Role.MENTOR}),
    EventLevel.MEDIUM: frozenset({Role.COLLEGE, Role.MENTOR, Role.SCHOOL}),
    EventLevel.HIGH: frozenset({Role.COLLEGE, Role.SCHOOL, Role.LEADERSHIP}),
    EventLevel.SAFETY: frozenset(
        {Role.COLLEGE, Role.SCHOOL, Role.LEADERSHIP, Role.CONSULAR}
    ),
}

# 各级别的首次处置时限
_DEADLINE: dict[EventLevel, timedelta] = {
    EventLevel.LOW: timedelta(days=3),
    EventLevel.MEDIUM: timedelta(days=2),
    EventLevel.HIGH: timedelta(days=1),
    EventLevel.SAFETY: timedelta(hours=12),
}

# 哪些级别必须复盘才能办结
_REVIEW_REQUIRED = {EventLevel.MEDIUM, EventLevel.HIGH, EventLevel.SAFETY}


@dataclass
class TimelineEntry:
    at: datetime
    actor: Role
    text: str


@dataclass
class Case:
    case_id: str
    trainee_id: str
    kind: IncidentKind
    level: EventLevel
    title: str
    occurred_from: date
    occurred_to: date
    assignment_id: str | None
    site_id: str | None
    visibility: frozenset[Role]
    status: CaseStatus = CaseStatus.OPEN
    created_at: datetime | None = None
    updated_at: datetime | None = None
    deadline: datetime | None = None
    escalations: int = 0
    report_count: int = 1
    review: str | None = None
    resolution: str | None = None
    timeline: list[TimelineEntry] = field(default_factory=list)

    def visible_to(self, role: Role) -> bool:
        return role in self.visibility

    def is_open(self) -> bool:
        return self.status != CaseStatus.CLOSED

    def requires_review(self) -> bool:
        return self.level in _REVIEW_REQUIRED


class IncidentRegistry:
    def __init__(self, sites: dict[str, PartnerSite], clock) -> None:
        self.sites = sites
        self.clock = clock
        self.cases: dict[str, Case] = {}
        self._seq = 0

    def _visibility_for(self, level: EventLevel, site_id: str | None) -> frozenset[Role]:
        roles = set(_BASE_VISIBILITY[level])
        if site_id and site_id in self.sites:
            scope = self.sites[site_id].report_scope
            if scope is not None:
                roles |= scope.extras_for(level)
        return frozenset(roles)

    def _next_id(self) -> str:
        self._seq += 1
        return f"IC-{self._seq:04d}"

    # ------------------------------------------------------------------
    # 上报（含去重并案）
    # ------------------------------------------------------------------

    def report(self, *, trainee_id: str, kind: IncidentKind, level: EventLevel,
               title: str, occurred_from: date, occurred_to: date | None = None,
               assignment_id: str | None = None, site_id: str | None = None,
               detail: str = "", actor: Role = Role.MENTOR) -> tuple[Case, bool]:
        """上报事件。返回 (案件, 是否新建)；重复上报只并案，不新建。"""
        now = self.clock.now()
        occurred_to = occurred_to or occurred_from
        if occurred_to < occurred_from:
            raise ValueError("事件发生时段结束日早于开始日")

        existing = self._find_duplicate(trainee_id, kind, occurred_from, occurred_to)
        if existing is not None:
            existing.report_count += 1
            # 新上报级别更高时提级并扩大可见范围
            if level > existing.level:
                widened = self._visibility_for(level, existing.site_id) | existing.visibility
                existing.visibility = widened
                existing.timeline.append(TimelineEntry(
                    now, actor,
                    f"重复上报（第 {existing.report_count} 次）并案，级别由 "
                    f"{existing.level.name} 提为 {level.name}；{title}。{detail}".rstrip("。") + "。",
                ))
                existing.level = level
                existing.deadline = min(existing.deadline or now, now + _DEADLINE[level])
            else:
                existing.timeline.append(TimelineEntry(
                    now, actor,
                    f"重复上报（第 {existing.report_count} 次）并案，不另立案件：{title}。{detail}".rstrip("。") + "。",
                ))
            existing.updated_at = now
            return existing, False

        case = Case(
            case_id=self._next_id(), trainee_id=trainee_id, kind=kind, level=level,
            title=title, occurred_from=occurred_from, occurred_to=occurred_to,
            assignment_id=assignment_id, site_id=site_id,
            visibility=self._visibility_for(level, site_id),
            created_at=now, updated_at=now, deadline=now + _DEADLINE[level],
        )
        case.timeline.append(TimelineEntry(
            now, actor,
            f"立案：{kind.value}（级别 {level.name}），{detail or title}",
        ))
        self.cases[case.case_id] = case
        return case, True

    def _find_duplicate(self, trainee_id: str, kind: IncidentKind,
                        occurred_from: date, occurred_to: date) -> Case | None:
        for c in self.cases.values():
            if (c.is_open() and c.trainee_id == trainee_id and c.kind == kind
                    and not (occurred_to < c.occurred_from or c.occurred_to < occurred_from)):
                return c
        return None

    # ------------------------------------------------------------------
    # 处置流转
    # ------------------------------------------------------------------

    def acknowledge(self, case_id: str, actor: Role, note: str = "") -> Case:
        c = self._case(case_id)
        self._require_view(c, actor)
        if c.status in (CaseStatus.OPEN, CaseStatus.ESCALATED):
            c.status = CaseStatus.HANDLING
        now = self.clock.now()
        c.timeline.append(TimelineEntry(now, actor, f"受理，进入处置。{note}".rstrip("。")))
        c.updated_at = now
        return c

    def handle(self, case_id: str, actor: Role, resolution: str) -> Case:
        c = self._case(case_id)
        self._require_view(c, actor)
        if c.status == CaseStatus.CLOSED:
            raise RuntimeError("案件已办结")
        c.resolution = resolution
        c.status = CaseStatus.REVIEWING if c.requires_review() else CaseStatus.CLOSED
        now = self.clock.now()
        if c.status == CaseStatus.CLOSED:
            c.timeline.append(TimelineEntry(now, actor, f"处置完成并办结：{resolution}"))
        else:
            c.timeline.append(TimelineEntry(
                now, actor, f"处置完成：{resolution}；级别要求复盘，进入待复盘"))
        c.updated_at = now
        return c

    def review_and_close(self, case_id: str, actor: Role, review_note: str) -> Case:
        c = self._case(case_id)
        self._require_view(c, actor)
        if c.status != CaseStatus.REVIEWING:
            raise RuntimeError(f"案件当前为 {c.status.value}，不能复盘办结")
        if not review_note.strip():
            raise ValueError("复盘结论不能为空")
        c.review = review_note
        c.status = CaseStatus.CLOSED
        now = self.clock.now()
        c.timeline.append(TimelineEntry(now, actor, f"完成复盘并办结：{review_note}"))
        c.updated_at = now
        return c

    # ------------------------------------------------------------------
    # 可控时钟驱动的逾期升级
    # ------------------------------------------------------------------

    def sweep_overdue(self) -> list[Case]:
        """由实践办公室每日命令配合可控时钟调用；返回本次被升级的案件。

        只升级尚未受理或处置中的案件；已进入待复盘的案件等待复盘流程，
        不再按受理时限升级（但仍出现在每日未办结列表中）。
        """
        now = self.clock.now()
        escalated: list[Case] = []
        for c in self.cases.values():
            if c.status == CaseStatus.REVIEWING or not c.is_open():
                continue
            if c.deadline is None or now < c.deadline:
                continue
            c.escalations += 1
            if c.status != CaseStatus.ESCALATED:
                c.status = CaseStatus.ESCALATED
            # 升级：扩大可见范围。领事仅介入安全事件；
            # HIGH 教学类事件是否加报领事由合作学校的 ReportScope 自行规定。
            widened = set(c.visibility)
            if c.level == EventLevel.SAFETY:
                widened |= {Role.LEADERSHIP, Role.CONSULAR}
            else:
                widened.add(Role.LEADERSHIP)
            c.visibility = frozenset(widened)
            # 给予升级后的下一处置时限
            c.deadline = now + _DEADLINE[c.level]
            c.timeline.append(TimelineEntry(
                now, Role.COLLEGE,
                f"逾期第 {c.escalations} 次自动升级，可见范围扩大至 "
                f"{'、'.join(r.value for r in sorted(widened, key=lambda x: x.name))}",
            ))
            c.updated_at = now
            escalated.append(c)
        return escalated

    def open_cases(self) -> list[Case]:
        return [c for c in self.cases.values() if c.is_open()]

    def _case(self, case_id: str) -> Case:
        try:
            return self.cases[case_id]
        except KeyError:
            raise KeyError(f"未知案件: {case_id}") from None

    @staticmethod
    def _require_view(c: Case, actor: Role) -> None:
        if not c.visible_to(actor):
            raise PermissionError(f"{actor.value} 不在案件 {c.case_id} 的可见范围内")
