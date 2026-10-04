"""核心领域模型：合作点、导师、课程场景、能力要求、学员与不可用时段。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import IntEnum

MIN_LANGUAGE_LEVEL = 1
MAX_LANGUAGE_LEVEL = 6


class Level(IntEnum):
    """事件级别，数值越大越敏感、可见范围越受控。"""

    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


def _check_language_level(level: int) -> None:
    if not MIN_LANGUAGE_LEVEL <= level <= MAX_LANGUAGE_LEVEL:
        raise ValueError(f"语言水平须为 {MIN_LANGUAGE_LEVEL}-{MAX_LANGUAGE_LEVEL} 级")


@dataclass(frozen=True)
class Window:
    """闭区间日期窗口，校历窗口、课程窗口与不可用时段共用。"""

    start: date
    end: date

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError("时段结束日期不能早于开始日期")

    def overlaps(self, other: "Window") -> bool:
        return self.start <= other.end and other.start <= self.end

    def to_dict(self) -> dict:
        return {"start": self.start.isoformat(), "end": self.end.isoformat()}

    @classmethod
    def from_dict(cls, data: dict) -> "Window":
        return cls(start=date.fromisoformat(data["start"]), end=date.fromisoformat(data["end"]))


@dataclass(frozen=True)
class ReportingPolicy:
    """合作点对敏感事件上报范围的要求：哪些级别必须同步给学校。"""

    school_visible_levels: frozenset = frozenset({Level.HIGH, Level.CRITICAL})

    def school_must_see(self, level: Level) -> bool:
        return level in self.school_visible_levels

    def to_dict(self) -> dict:
        return {"school_visible_levels": [int(v) for v in sorted(self.school_visible_levels)]}

    @classmethod
    def from_dict(cls, data: dict) -> "ReportingPolicy":
        return cls(school_visible_levels=frozenset(Level(v) for v in data["school_visible_levels"]))


@dataclass
class PartnerSite:
    """东盟合作学校（实践点），自带校历窗口与上报政策。"""

    site_id: str
    name: str
    country: str
    terms: dict = field(default_factory=dict)  # 校历窗口名 -> Window
    reporting_policy: ReportingPolicy = field(default_factory=ReportingPolicy)

    def __post_init__(self) -> None:
        if not self.site_id or not self.name or not self.country:
            raise ValueError("合作点信息不完整")

    def to_dict(self) -> dict:
        return {
            "site_id": self.site_id,
            "name": self.name,
            "country": self.country,
            "terms": {k: w.to_dict() for k, w in self.terms.items()},
            "reporting_policy": self.reporting_policy.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PartnerSite":
        return cls(
            site_id=data["site_id"],
            name=data["name"],
            country=data["country"],
            terms={k: Window.from_dict(w) for k, w in data["terms"].items()},
            reporting_policy=ReportingPolicy.from_dict(data["reporting_policy"]),
        )


@dataclass
class Mentor:
    """在岗导师，容量限制同一时段可带教的学员数。"""

    mentor_id: str
    site_id: str
    name: str
    capacity: int = 1

    def __post_init__(self) -> None:
        if not self.mentor_id or not self.site_id or not self.name:
            raise ValueError("导师信息不完整")
        if self.capacity < 1:
            raise ValueError("导师容量至少为 1")

    def to_dict(self) -> dict:
        return {
            "mentor_id": self.mentor_id,
            "site_id": self.site_id,
            "name": self.name,
            "capacity": self.capacity,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Mentor":
        return cls(
            mentor_id=data["mentor_id"],
            site_id=data["site_id"],
            name=data["name"],
            capacity=data["capacity"],
        )


@dataclass
class CourseScenario:
    """课程场景：某合作点在某校历窗口内、面向特定授课对象的授课任务。"""

    scenario_id: str
    site_id: str
    mentor_id: str
    title: str
    term: str
    window: Window
    min_language_level: int
    competencies: frozenset = frozenset()  # 该场景覆盖的能力要求编码

    def __post_init__(self) -> None:
        if not self.scenario_id or not self.site_id or not self.mentor_id or not self.title:
            raise ValueError("课程场景信息不完整")
        _check_language_level(self.min_language_level)

    def to_dict(self) -> dict:
        return {
            "scenario_id": self.scenario_id,
            "site_id": self.site_id,
            "mentor_id": self.mentor_id,
            "title": self.title,
            "term": self.term,
            "window": self.window.to_dict(),
            "min_language_level": self.min_language_level,
            "competencies": sorted(self.competencies),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CourseScenario":
        return cls(
            scenario_id=data["scenario_id"],
            site_id=data["site_id"],
            mentor_id=data["mentor_id"],
            title=data["title"],
            term=data["term"],
            window=Window.from_dict(data["window"]),
            min_language_level=data["min_language_level"],
            competencies=frozenset(data["competencies"]),
        )


@dataclass
class Trainee:
    """学员画像：语言水平、培养目标、已覆盖能力与轮换历史。"""

    trainee_id: str
    name: str
    language_level: int
    target_competencies: set = field(default_factory=set)
    covered_competencies: set = field(default_factory=set)
    completed_rotations: int = 0
    visited_countries: set = field(default_factory=set)

    def __post_init__(self) -> None:
        if not self.trainee_id or not self.name:
            raise ValueError("学员信息不完整")
        _check_language_level(self.language_level)
        if self.completed_rotations < 0:
            raise ValueError("轮换次数不能为负")

    def to_dict(self) -> dict:
        return {
            "trainee_id": self.trainee_id,
            "name": self.name,
            "language_level": self.language_level,
            "target_competencies": sorted(self.target_competencies),
            "covered_competencies": sorted(self.covered_competencies),
            "completed_rotations": self.completed_rotations,
            "visited_countries": sorted(self.visited_countries),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Trainee":
        return cls(
            trainee_id=data["trainee_id"],
            name=data["name"],
            language_level=data["language_level"],
            target_competencies=set(data["target_competencies"]),
            covered_competencies=set(data["covered_competencies"]),
            completed_rotations=data["completed_rotations"],
            visited_countries=set(data["visited_countries"]),
        )


@dataclass
class UnavailableWindow:
    """不可用时段：学员、导师或合作点在窗口内不可安排。"""

    owner_kind: str  # trainee | mentor | site
    owner_id: str
    window: Window
    reason: str

    VALID_OWNER_KINDS = ("trainee", "mentor", "site")

    def __post_init__(self) -> None:
        if self.owner_kind not in self.VALID_OWNER_KINDS:
            raise ValueError(f"不可用时段属主须为 {self.VALID_OWNER_KINDS}")
        if not self.owner_id or not self.reason:
            raise ValueError("不可用时段须注明属主与原因")

    def applies_to(self, owner_kind: str, owner_id: str) -> bool:
        return self.owner_kind == owner_kind and self.owner_id == owner_id

    def to_dict(self) -> dict:
        return {
            "owner_kind": self.owner_kind,
            "owner_id": self.owner_id,
            "window": self.window.to_dict(),
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "UnavailableWindow":
        return cls(
            owner_kind=data["owner_kind"],
            owner_id=data["owner_id"],
            window=Window.from_dict(data["window"]),
            reason=data["reason"],
        )
