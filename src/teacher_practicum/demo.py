"""演示数据：两所东盟合作学校、导师、课程场景与首批学员。"""
from __future__ import annotations

from datetime import date, datetime, timezone

from .clock import ManualClock
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
from .service import PracticumService

DEMO_NOW = datetime(2026, 10, 4, 9, 0, tzinfo=timezone.utc)

# 能力要求目录
CLASSROOM = "课堂管理"
LESSON_DESIGN = "教学设计"
CROSS_CULTURE = "跨文化沟通"
ASSESSMENT = "学习评估"
MULTIMEDIA = "多媒体教学"


def build_demo_service() -> PracticumService:
    service = PracticumService(clock=ManualClock(DEMO_NOW))

    bangkok = PartnerSite(
        site_id="S-BKK",
        name="曼谷合作学校",
        country="泰国",
        terms={
            "2026秋季": Window(date(2026, 11, 2), date(2026, 12, 25)),
            "2027春季": Window(date(2027, 1, 12), date(2027, 3, 6)),
        },
        # 该校要求 HIGH 及以上敏感事件必须同步学校
        reporting_policy=ReportingPolicy(
            school_visible_levels=frozenset({Level.HIGH, Level.CRITICAL})
        ),
    )
    hanoi = PartnerSite(
        site_id="S-HAN",
        name="河内合作学校",
        country="越南",
        terms={
            "2026秋季": Window(date(2026, 11, 9), date(2026, 12, 31)),
            "2027春季": Window(date(2027, 1, 5), date(2027, 2, 27)),
        },
        # 该校仅要求 CRITICAL 事件同步学校
        reporting_policy=ReportingPolicy(school_visible_levels=frozenset({Level.CRITICAL})),
    )
    service.add_site(bangkok)
    service.add_site(hanoi)

    service.add_mentor(Mentor("M-BKK-1", "S-BKK", "陈老师", capacity=1))
    service.add_mentor(Mentor("M-BKK-2", "S-BKK", "林老师", capacity=2))
    service.add_mentor(Mentor("M-HAN-1", "S-HAN", "黄老师", capacity=1))

    service.add_scenario(
        CourseScenario(
            scenario_id="C-BKK-PRIMARY",
            site_id="S-BKK",
            mentor_id="M-BKK-1",
            title="曼谷小学中文口语课",
            term="2026秋季",
            window=bangkok.terms["2026秋季"],
            min_language_level=3,
            competencies=frozenset({CLASSROOM, CROSS_CULTURE}),
        )
    )
    service.add_scenario(
        CourseScenario(
            scenario_id="C-BKK-SECONDARY",
            site_id="S-BKK",
            mentor_id="M-BKK-2",
            title="曼谷中学中文综合课",
            term="2026秋季",
            window=bangkok.terms["2026秋季"],
            min_language_level=4,
            competencies=frozenset({LESSON_DESIGN, ASSESSMENT}),
        )
    )
    service.add_scenario(
        CourseScenario(
            scenario_id="C-HAN-ADULT",
            site_id="S-HAN",
            mentor_id="M-HAN-1",
            title="河内成人中文兴趣班",
            term="2026秋季",
            window=hanoi.terms["2026秋季"],
            min_language_level=4,
            competencies=frozenset({LESSON_DESIGN, MULTIMEDIA}),
        )
    )

    service.add_trainee(
        Trainee(
            trainee_id="T-01",
            name="王小雨",
            language_level=5,
            target_competencies={CLASSROOM, LESSON_DESIGN, ASSESSMENT},
        )
    )
    service.add_trainee(
        Trainee(
            trainee_id="T-02",
            name="李思远",
            language_level=4,
            target_competencies={CLASSROOM, CROSS_CULTURE, MULTIMEDIA},
        )
    )
    service.add_trainee(
        Trainee(
            trainee_id="T-03",
            name="赵明玉",
            language_level=2,
            target_competencies={CLASSROOM, CROSS_CULTURE},
        )
    )
    service.add_trainee(
        Trainee(
            trainee_id="T-04",
            name="孙可欣",
            language_level=4,
            target_competencies={LESSON_DESIGN, MULTIMEDIA, ASSESSMENT},
        )
    )

    # 学员 T-02 十一月底有回国答辩，落在秋季窗口内
    service.unavailable.append(
        UnavailableWindow(
            owner_kind="trainee",
            owner_id="T-02",
            window=Window(date(2026, 11, 25), date(2026, 12, 5)),
            reason="回国参加中期答辩",
        )
    )
    return service
