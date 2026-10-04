"""请假、教学事故与安全事件：分级可见、重复归并、处置复盘与逾期升级。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

from .models import Level, ReportingPolicy


class IncidentType(str, Enum):
    LEAVE = "leave"  # 请假
    TEACHING_ACCIDENT = "teaching_accident"  # 教学事故
    SAFETY = "safety"  # 安全事件


class CaseStatus(str, Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"  # 已处置
    RETROSPECTED = "retrospected"  # 已复盘
    CLOSED = "closed"


# 各级别处置时限（小时），逾期由可控制时钟触发升级
SLA_HOURS = {
    Level.LOW: 168,
    Level.MEDIUM: 72,
    Level.HIGH: 24,
    Level.CRITICAL: 4,
}

# 级别决定的基础可见范围；学校是否可见另由合作点上报政策决定
BASE_VISIBILITY = {
    Level.LOW: {"mentor", "college_office"},
    Level.MEDIUM: {"mentor", "college_office", "college_leadership"},
    Level.HIGH: {"mentor", "college_office", "college_leadership"},
    Level.CRITICAL: {"mentor", "college_office", "college_leadership", "school"},
}


def compute_visibility(
    incident_type: IncidentType, level: Level, policy: ReportingPolicy
) -> set:
    """按级别限制可见范围，并叠加合作点对敏感事件的上报要求。"""
    visible = set(BASE_VISIBILITY[level])
    if incident_type == IncidentType.LEAVE:
        # 请假始终需要学校与导师知悉
        visible.update({"school", "mentor"})
    if policy.school_must_see(level):
        visible.add("school")
    return visible


@dataclass
class Report:
    reporter: str
    description: str
    reported_at: str

    def to_dict(self) -> dict:
        return {
            "reporter": self.reporter,
            "description": self.description,
            "reported_at": self.reported_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Report":
        return cls(
            reporter=data["reporter"],
            description=data["description"],
            reported_at=data["reported_at"],
        )


@dataclass
class Escalation:
    from_level: int
    to_level: int
    at: str
    reason: str

    def to_dict(self) -> dict:
        return {
            "from_level": self.from_level,
            "to_level": self.to_level,
            "at": self.at,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Escalation":
        return cls(
            from_level=data["from_level"],
            to_level=data["to_level"],
            at=data["at"],
            reason=data["reason"],
        )


@dataclass
class Case:
    """事件案件：同一指纹的重复上报只保留一个案件。"""

    case_id: str
    incident_type: IncidentType
    level: Level
    trainee_id: str
    site_id: str
    occurred_on: str  # 事发日期 ISO
    arrangement_id: str = ""
    status: CaseStatus = CaseStatus.OPEN
    reports: list = field(default_factory=list)
    escalations: list = field(default_factory=list)
    resolution: str = ""
    retrospective: str = ""
    created_at: str = ""
    updated_at: str = ""
    due_at: str = ""

    @property
    def fingerprint(self) -> tuple:
        return (self.incident_type, self.trainee_id, self.occurred_on)

    @property
    def is_closed(self) -> bool:
        return self.status == CaseStatus.CLOSED

    @property
    def escalated(self) -> bool:
        return bool(self.escalations)

    def visibility(self, policy: ReportingPolicy) -> set:
        return compute_visibility(self.incident_type, self.level, policy)

    def add_report(self, report: Report) -> None:
        self.reports.append(report)
        self.updated_at = report.reported_at

    def acknowledge(self, at: datetime) -> None:
        if self.status != CaseStatus.OPEN:
            raise ValueError("仅待受理案件可以受理")
        self.status = CaseStatus.ACKNOWLEDGED
        self.updated_at = at.isoformat()

    def resolve(self, at: datetime, measures: str) -> None:
        if self.status not in (CaseStatus.OPEN, CaseStatus.ACKNOWLEDGED):
            raise ValueError("仅处置中的案件可以办结处置")
        if not measures:
            raise ValueError("处置措施不能为空")
        self.resolution = measures
        self.status = CaseStatus.RESOLVED
        self.updated_at = at.isoformat()

    def complete_retrospective(self, at: datetime, summary: str) -> None:
        if self.status != CaseStatus.RESOLVED:
            raise ValueError("仅已处置案件可以复盘")
        if not summary:
            raise ValueError("复盘结论不能为空")
        self.retrospective = summary
        self.status = CaseStatus.RETROSPECTED
        self.updated_at = at.isoformat()

    def close(self, at: datetime) -> None:
        if self.status != CaseStatus.RETROSPECTED:
            raise ValueError("案件须先复盘方可归档")
        self.status = CaseStatus.CLOSED
        self.updated_at = at.isoformat()

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "incident_type": self.incident_type.value,
            "level": int(self.level),
            "trainee_id": self.trainee_id,
            "site_id": self.site_id,
            "occurred_on": self.occurred_on,
            "arrangement_id": self.arrangement_id,
            "status": self.status.value,
            "reports": [r.to_dict() for r in self.reports],
            "escalations": [e.to_dict() for e in self.escalations],
            "resolution": self.resolution,
            "retrospective": self.retrospective,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "due_at": self.due_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Case":
        return cls(
            case_id=data["case_id"],
            incident_type=IncidentType(data["incident_type"]),
            level=Level(data["level"]),
            trainee_id=data["trainee_id"],
            site_id=data["site_id"],
            occurred_on=data["occurred_on"],
            arrangement_id=data["arrangement_id"],
            status=CaseStatus(data["status"]),
            reports=[Report.from_dict(r) for r in data["reports"]],
            escalations=[Escalation.from_dict(e) for e in data["escalations"]],
            resolution=data["resolution"],
            retrospective=data["retrospective"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            due_at=data["due_at"],
        )


def new_case(
    case_id: str,
    incident_type: IncidentType,
    level: Level,
    trainee_id: str,
    site_id: str,
    occurred_on: str,
    arrangement_id: str,
    first_report: Report,
    now: datetime,
) -> Case:
    due = now + timedelta(hours=SLA_HOURS[level])
    return Case(
        case_id=case_id,
        incident_type=incident_type,
        level=level,
        trainee_id=trainee_id,
        site_id=site_id,
        occurred_on=occurred_on,
        arrangement_id=arrangement_id,
        reports=[first_report],
        created_at=now.isoformat(),
        updated_at=now.isoformat(),
        due_at=due.isoformat(),
    )
