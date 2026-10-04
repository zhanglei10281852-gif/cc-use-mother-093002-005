"""可复用的情景数据：首批学员分赴曼谷、河内合作点。"""
from __future__ import annotations

from datetime import date

from .clock import Clock
from .domain import (
    Competency,
    CourseScenario,
    DateRange,
    EventLevel,
    Language,
    LanguageRequirement,
    ReportScope,
    Role,
)
from .service import PracticumService


def build_demo_service(clock: Clock | None = None) -> PracticumService:
    svc = PracticumService(clock or Clock())

    # 曼谷：HIGH 级别以上事件加报领事/应急联络人
    svc.register_site(
        "BKK", "曼谷华文学校", "泰国",
        windows=[DateRange(date(2026, 11, 1), date(2026, 12, 15))],
        scenarios=[
            CourseScenario("BKK-PRI", "小学中文兴趣班", "小学生",
                           LanguageRequirement(Language.THAI, "B1"),
                           frozenset({Competency.YOUNG_LEARNERS, Competency.CLASSROOM_MANAGEMENT,
                                      Competency.PRONUNCIATION_COACHING})),
            CourseScenario("BKK-UNI", "大学公共中文课", "大学生",
                           LanguageRequirement(Language.ENGLISH, "B2"),
                           frozenset({Competency.LESSON_DESIGN, Competency.ADULT_LEARNERS,
                                      Competency.BASIC_LINGUISTICS})),
        ],
        report_scope=ReportScope(EventLevel.HIGH, frozenset({Role.CONSULAR})),
    )
    svc.register_site(
        "HAN", "河内外国语中学", "越南",
        windows=[DateRange(date(2026, 11, 10), date(2026, 11, 20)),
                 DateRange(date(2026, 11, 25), date(2026, 12, 20))],
        scenarios=[
            CourseScenario("HAN-SEC", "中学生中文必修课", "中学生",
                           LanguageRequirement(Language.VIETNAMESE, "B1"),
                           frozenset({Competency.CLASSROOM_MANAGEMENT, Competency.LESSON_DESIGN,
                                      Competency.TEST_PREP})),
        ],
    )

    svc.register_mentor("M-B1", "颂巴萨", "BKK", capacity=1,
                        language_requirements=frozenset({LanguageRequirement(Language.THAI, "B1")}),
                        competencies=frozenset({Competency.YOUNG_LEARNERS,
                                                Competency.CLASSROOM_MANAGEMENT,
                                                Competency.PRONUNCIATION_COACHING}))
    svc.register_mentor("M-B2", "玛琳达", "BKK", capacity=2,
                        language_requirements=frozenset({LanguageRequirement(Language.ENGLISH, "B2")}),
                        competencies=frozenset({Competency.LESSON_DESIGN,
                                                Competency.ADULT_LEARNERS}))
    svc.register_mentor("M-H1", "阮文河", "HAN", capacity=2,
                        language_requirements=frozenset({LanguageRequirement(Language.VIETNAMESE, "B1")}),
                        competencies=frozenset({Competency.CLASSROOM_MANAGEMENT,
                                                Competency.LESSON_DESIGN}),
                        unavailable=[DateRange(date(2026, 11, 20), date(2026, 11, 25))])

    # T02 英语 B2 但不会泰语 → 曼谷小学场景不匹配、大学场景可行
    svc.register_trainee("T01", "王安",
                         languages={Language.THAI: "B1", Language.ENGLISH: "B1"},
                         acquired_competencies={Competency.BASIC_LINGUISTICS})
    svc.register_trainee("T02", "李禾",
                         languages={Language.ENGLISH: "B2"},
                         acquired_competencies={Competency.YOUNG_LEARNERS})
    svc.register_trainee("T03", "张宁",
                         languages={Language.VIETNAMESE: "B2", Language.ENGLISH: "B1"},
                         acquired_competencies=set())
    # 语言全部不达门槛 → 无可行候选
    svc.register_trainee("T04", "赵桥",
                         languages={Language.ENGLISH: "A2"},
                         acquired_competencies=set())
    return svc
