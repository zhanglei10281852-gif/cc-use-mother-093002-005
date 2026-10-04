"""领域模型：合作点、导师、课程场景、能力、学员、校历窗口、不可用时段。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum

from .contracts import PracticumSiteVersion, TraineeProfile


# ---------------------------------------------------------------------------
# 语言水平
# ---------------------------------------------------------------------------

class Language(str, Enum):
    ENGLISH = "en"
    THAI = "th"
    VIETNAMESE = "vi"
    INDONESIAN = "id"
    MALAY = "ms"
    LAO = "lo"
    KHMER = "km"
    MYANMAR = "my"
    TAGALOG = "tl"


# CEFR 等级，数字越大水平越高；学员水平须达到场景要求
LEVEL_ORDER: dict[str, int] = {"A2": 2, "B1": 3, "B2": 4, "C1": 5, "C2": 6}


def meets_level(trainee_level: str, required_level: str) -> bool:
    if trainee_level not in LEVEL_ORDER or required_level not in LEVEL_ORDER:
        raise ValueError(f"未知的语言等级: {trainee_level!r}/{required_level!r}")
    return LEVEL_ORDER[trainee_level] >= LEVEL_ORDER[required_level]


class Competency(str, Enum):
    """培养方案中的教学能力项。"""

    CLASSROOM_MANAGEMENT = "课堂组织"
    LESSON_DESIGN = "教案设计"
    PRONUNCIATION_COACHING = "语音纠音"
    CULTURAL_ADAPTATION = "跨文化适应"
    TEST_PREP = "考试辅导"
    YOUNG_LEARNERS = "少儿教学"
    ADULT_LEARNERS = "成人教学"
    ONLINE_DELIVERY = "线上授课"
    BASIC_LINGUISTICS = "汉语言基础"
    EMERGENCY_DRILL = "应急演练"


@dataclass(frozen=True)
class LanguageRequirement:
    language: Language
    min_level: str

    def satisfied_by(self, languages: dict[Language, str]) -> bool:
        actual = languages.get(self.language)
        return actual is not None and meets_level(actual, self.min_level)


# ---------------------------------------------------------------------------
# 校历窗口 / 不可用时段
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DateRange:
    """半开放区间 [start, end)，按日比较。"""

    start: date
    end: date

    def __post_init__(self) -> None:
        if self.end <= self.start:
            raise ValueError("时间区间结束日必须晚于开始日")

    def overlaps(self, other: "DateRange") -> bool:
        return self.start < other.end and other.start < self.end

    def contains(self, day: date) -> bool:
        return self.start <= day < self.end


CalendarWindow = DateRange
UnavailableSlot = DateRange


# ---------------------------------------------------------------------------
# 课程场景与合作点
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CourseScenario:
    """一个具体授课场景：教授对象、语言门槛、可覆盖的能力。"""

    scenario_id: str
    title: str
    learner_type: str  # 如 "小学生" / "大学生" / "成人"
    language_requirement: LanguageRequirement
    competencies: frozenset[Competency]

    def __post_init__(self) -> None:
        if not self.scenario_id or not self.title or not self.learner_type:
            raise ValueError("课程场景信息不完整")
        if not self.competencies:
            raise ValueError("课程场景至少覆盖一项能力")


@dataclass
class PartnerSite:
    """东盟合作学校（版本化实体）。"""

    version: PracticumSiteVersion
    country: str
    windows: list[CalendarWindow] = field(default_factory=list)
    scenarios: list[CourseScenario] = field(default_factory=list)
    # 敏感事件上报范围：学校可要求某级别以上的事件直接上报给额外角色
    report_scope: "ReportScope | None" = None

    @property
    def site_id(self) -> str:
        return self.version.entity_id

    @property
    def revision(self) -> int:
        return self.version.revision


# ---------------------------------------------------------------------------
# 导师
# ---------------------------------------------------------------------------

@dataclass
class Mentor:
    mentor_id: str
    name: str
    site_id: str
    capacity: int  # 同期可带学员数
    revision: int = 1
    language_requirements: frozenset[LanguageRequirement] = field(default_factory=frozenset)
    competencies: frozenset[Competency] = field(default_factory=frozenset)
    unavailable: list[UnavailableSlot] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.mentor_id or not self.name or not self.site_id:
            raise ValueError("导师信息不完整")
        if self.capacity < 0 or self.revision < 1:
            raise ValueError("导师容量/修订号不合法")

    def available_during(self, rng: DateRange) -> bool:
        return not any(slot.overlaps(rng) for slot in self.unavailable)


# ---------------------------------------------------------------------------
# 学员
# ---------------------------------------------------------------------------

@dataclass
class Trainee:
    profile: TraineeProfile
    name: str
    languages: dict[Language, str] = field(default_factory=dict)
    # 已获得的能力（此前实践/课程已覆盖）
    acquired_competencies: set[Competency] = field(default_factory=set)
    unavailable: list[UnavailableSlot] = field(default_factory=list)

    @property
    def trainee_id(self) -> str:
        # entity_id 是学员实体标识（与安排、案件中的 trainee_id 一致）；
        # record_id 仅标识这条档案记录本身
        return self.profile.entity_id

    @property
    def record_id(self) -> str:
        return self.profile.record_id

    def available_during(self, rng: DateRange) -> bool:
        return not any(slot.overlaps(rng) for slot in self.unavailable)

    def covers(self, competency: Competency) -> bool:
        return competency in self.acquired_competencies


# ---------------------------------------------------------------------------
# 敏感事件上报范围
# ---------------------------------------------------------------------------

class EventLevel(int, Enum):
    LOW = 1       # 请假等常规事项
    MEDIUM = 2    # 一般教学事故
    HIGH = 3      # 严重教学事故
    SAFETY = 4    # 安全事件


class Role(str, Enum):
    COLLEGE = "学院实践办公室"
    SCHOOL = "合作学校"
    MENTOR = "导师"
    CONSULAR = "领事/应急联络人"
    LEADERSHIP = "学院领导"


@dataclass(frozen=True)
class ReportScope:
    """某合作点对各级别事件的可见/上报范围。"""

    # 级别 >= threshold 的事件，除默认接收方外还应上报给 extra_recipients
    threshold: EventLevel
    extra_recipients: frozenset[Role]

    def extras_for(self, level: EventLevel) -> frozenset[Role]:
        return self.extra_recipients if level >= self.threshold else frozenset()
