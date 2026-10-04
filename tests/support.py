"""测试共享的数据构造器。"""
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from teacher_practicum import (  # noqa: E402
    CourseScenario,
    Level,
    ManualClock,
    Mentor,
    PartnerSite,
    PracticumService,
    ReportingPolicy,
    Trainee,
    Window,
)

NOW = datetime(2026, 10, 4, 9, 0, tzinfo=timezone.utc)
AUTUMN = Window(date(2026, 11, 2), date(2026, 12, 25))
SPRING = Window(date(2027, 1, 12), date(2027, 3, 6))


def make_service() -> PracticumService:
    """一个合作点、一名容量为 2 的导师、两个重叠场景、两名达标学员。"""
    service = PracticumService(clock=ManualClock(NOW))
    service.add_site(
        PartnerSite(
            site_id="S1",
            name="曼谷合作学校",
            country="泰国",
            terms={"秋": AUTUMN, "春": SPRING},
            reporting_policy=ReportingPolicy(
                school_visible_levels=frozenset({Level.HIGH, Level.CRITICAL})
            ),
        )
    )
    service.add_mentor(Mentor("M1", "S1", "陈老师", capacity=2))
    service.add_scenario(
        CourseScenario(
            scenario_id="C1",
            site_id="S1",
            mentor_id="M1",
            title="小学口语课",
            term="秋",
            window=AUTUMN,
            min_language_level=3,
            competencies=frozenset({"课堂管理", "跨文化沟通"}),
        )
    )
    service.add_scenario(
        CourseScenario(
            scenario_id="C2",
            site_id="S1",
            mentor_id="M1",
            title="中学综合课",
            term="秋",
            window=AUTUMN,
            min_language_level=4,
            competencies=frozenset({"教学设计", "学习评估"}),
        )
    )
    service.add_trainee(
        Trainee("T1", "王小雨", 5, target_competencies={"课堂管理", "教学设计"})
    )
    service.add_trainee(
        Trainee("T2", "李思远", 4, target_competencies={"学习评估", "跨文化沟通"})
    )
    return service


def generate_all(service):
    created, unassigned = service.generate_plan()
    assert not unassigned, f"预期全部安排成功：{unassigned}"
    return created
