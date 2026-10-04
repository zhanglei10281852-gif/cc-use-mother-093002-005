"""安排生命周期与学校、导师、学院三方确认。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from .models import Window
from .scheduling import Conflict


class Party(str, Enum):
    SCHOOL = "school"  # 合作学校
    MENTOR = "mentor"  # 在岗导师
    COLLEGE = "college"  # 学院实践办公室


class ArrangementStatus(str, Enum):
    DRAFT = "draft"
    PENDING = "pending"  # 等待三方确认
    CONFIRMED = "confirmed"  # 三方均已确认
    STARTED = "started"  # 实践已开始，禁止静默改派
    COMPLETED = "completed"
    CONFLICTED = "conflicted"  # 重新评估发现冲突
    CANCELLED = "cancelled"


ACTIVE_STATUSES = (
    ArrangementStatus.PENDING,
    ArrangementStatus.CONFIRMED,
    ArrangementStatus.STARTED,
    ArrangementStatus.CONFLICTED,
)


@dataclass
class Confirmation:
    party: Party
    state: str = "pending"  # pending | confirmed | rejected
    at: str = ""
    note: str = ""

    def to_dict(self) -> dict:
        return {"party": self.party.value, "state": self.state, "at": self.at, "note": self.note}

    @classmethod
    def from_dict(cls, data: dict) -> "Confirmation":
        return cls(
            party=Party(data["party"]),
            state=data["state"],
            at=data["at"],
            note=data["note"],
        )


def fresh_confirmations() -> dict:
    return {party: Confirmation(party=party) for party in Party}


@dataclass
class Arrangement:
    arrangement_id: str
    trainee_id: str
    scenario_id: str
    mentor_id: str
    site_id: str
    window: Window
    status: ArrangementStatus = ArrangementStatus.DRAFT
    confirmations: dict = field(default_factory=fresh_confirmations)
    conflicts: list = field(default_factory=list)
    explanation: list = field(default_factory=list)
    history: list = field(default_factory=list)
    revision: int = 1

    def _stamp(self, at: datetime, message: str) -> None:
        self.history.append(f"{at.isoformat()} {message}")
        self.revision += 1

    def pending_parties(self) -> list:
        if self.status != ArrangementStatus.PENDING:
            return []
        return [p for p, c in self.confirmations.items() if c.state == "pending"]

    def confirm(self, party: Party, at: datetime, note: str = "") -> None:
        if self.status != ArrangementStatus.PENDING:
            raise ValueError(f"当前状态 {self.status.value} 不可确认")
        conf = self.confirmations[party]
        if conf.state == "confirmed":
            raise ValueError(f"{party.value} 已确认过，不可重复确认")
        conf.state = "confirmed"
        conf.at = at.isoformat()
        conf.note = note
        self._stamp(at, f"{party.value} 确认")
        if all(c.state == "confirmed" for c in self.confirmations.values()):
            self.status = ArrangementStatus.CONFIRMED
            self._stamp(at, "三方确认完毕，安排生效")

    def reject(self, party: Party, at: datetime, note: str = "") -> None:
        if self.status != ArrangementStatus.PENDING:
            raise ValueError(f"当前状态 {self.status.value} 不可拒绝")
        conf = self.confirmations[party]
        conf.state = "rejected"
        conf.at = at.isoformat()
        conf.note = note
        self.status = ArrangementStatus.CANCELLED
        self._stamp(at, f"{party.value} 拒绝（{note}），安排取消")

    def reset_confirmations(self, at: datetime, reason: str) -> None:
        """任何一方数据变更后，三方需重新确认。"""
        self.confirmations = fresh_confirmations()
        self._stamp(at, f"重新评估：{reason}，三方确认重置")

    def mark_conflicted(self, conflicts: list, at: datetime, reason: str) -> None:
        self.conflicts = list(conflicts)
        self.status = ArrangementStatus.CONFLICTED
        self.reset_confirmations(at, reason)

    def clear_conflicts(self, at: datetime, reason: str) -> None:
        self.conflicts = []
        self.status = ArrangementStatus.PENDING
        self.reset_confirmations(at, reason)

    def start(self, at: datetime) -> None:
        if self.status != ArrangementStatus.CONFIRMED:
            raise ValueError("仅三方确认完毕的安排可以开始实践")
        self.status = ArrangementStatus.STARTED
        self._stamp(at, "实践开始，禁止静默改派")

    def complete(self, at: datetime) -> None:
        if self.status != ArrangementStatus.STARTED:
            raise ValueError("仅进行中的实践可以办结")
        self.status = ArrangementStatus.COMPLETED
        self._stamp(at, "实践办结")

    def to_dict(self) -> dict:
        return {
            "arrangement_id": self.arrangement_id,
            "trainee_id": self.trainee_id,
            "scenario_id": self.scenario_id,
            "mentor_id": self.mentor_id,
            "site_id": self.site_id,
            "window": self.window.to_dict(),
            "status": self.status.value,
            "confirmations": [c.to_dict() for c in self.confirmations.values()],
            "conflicts": [c.to_dict() for c in self.conflicts],
            "explanation": list(self.explanation),
            "history": list(self.history),
            "revision": self.revision,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Arrangement":
        arr = cls(
            arrangement_id=data["arrangement_id"],
            trainee_id=data["trainee_id"],
            scenario_id=data["scenario_id"],
            mentor_id=data["mentor_id"],
            site_id=data["site_id"],
            window=Window.from_dict(data["window"]),
            status=ArrangementStatus(data["status"]),
            conflicts=[Conflict.from_dict(c) for c in data["conflicts"]],
            explanation=list(data["explanation"]),
            history=list(data["history"]),
            revision=data["revision"],
        )
        arr.confirmations = {
            c.party: c for c in (Confirmation.from_dict(d) for d in data["confirmations"])
        }
        return arr
