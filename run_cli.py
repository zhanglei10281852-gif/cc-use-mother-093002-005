"""跨国中文教师实践安排与在岗支持服务命令行。

用法示例：
    python run_cli.py                      # 演示全流程（不写状态文件）
    python run_cli.py seed                 # 初始化演示数据到状态文件
    python run_cli.py generate             # 生成候选安排
    python run_cli.py confirm A-0001 school
    python run_cli.py report --type safety --level high --trainee T-01 --by 导师 --desc "..."
    python run_cli.py tick --hours 30      # 推进可控制时钟并触发逾期升级
    python run_cli.py summary              # 实践办公室每日汇总
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from teacher_practicum import (  # noqa: E402
    IncidentType,
    Level,
    ManualClock,
    Party,
    PracticumService,
    UnavailableWindow,
    Window,
)
from teacher_practicum.demo import DEMO_NOW, build_demo_service  # noqa: E402
from teacher_practicum.reporting import format_summary  # noqa: E402

DEFAULT_STATE = "practicum_state.json"


def load_service(path: str) -> PracticumService:
    state = Path(path)
    if state.exists():
        return PracticumService.from_snapshot(json.loads(state.read_text(encoding="utf-8")))
    return PracticumService(clock=ManualClock(DEMO_NOW))


def save_service(path: str, service: PracticumService) -> None:
    Path(path).write_text(
        json.dumps(service.to_snapshot(), ensure_ascii=False, indent=2), encoding="utf-8"
    )


def print_summary(service: PracticumService) -> None:
    print(format_summary(service.daily_summary()))


def cmd_demo(_args) -> None:
    """内存中跑完整流程：生成、确认、事件、逾期升级、汇总。"""
    service = build_demo_service()
    created, _unassigned = service.generate_plan()
    for arr in created:
        print(f"候选安排 {arr.arrangement_id}：学员 {arr.trainee_id} -> {arr.scenario_id}")
        for reason in arr.explanation:
            print(f"    理由：{reason}")
    if created:
        first = created[0].arrangement_id
        for party in (Party.SCHOOL, Party.MENTOR, Party.COLLEGE):
            service.confirm(first, party)
        print(f"\n{first} 三方确认完毕")
        if len(created) > 1:
            second = created[1].arrangement_id
            service.confirm(second, Party.SCHOOL)
            service.confirm(second, Party.MENTOR)
            print(f"{second} 等待学院确认")

    case, created_new = service.report_incident(
        IncidentType.SAFETY, Level.HIGH, "T-01", "宿舍区夜间施工扰民", reporter="陈老师"
    )
    print(f"\n安全事件案件 {case.case_id}（新建={created_new}），可见范围 {sorted(service.case_visibility(case.case_id))}")
    case2, created_new2 = service.report_incident(
        IncidentType.SAFETY, Level.HIGH, "T-01", "同一扰民事件再次上报", reporter="学员本人"
    )
    print(f"重复上报归并：{case2.case_id}（新建={created_new2}，累计上报 {len(case2.reports)} 次）")

    escalated = service.advance_clock(hours=30)
    for c in escalated:
        print(f"案件 {c.case_id} 逾期升级为 L{int(c.level)}")
    print()
    print_summary(service)


def cmd_seed(args) -> None:
    service = build_demo_service()
    save_service(args.state, service)
    print(f"演示数据已写入 {args.state}")


def cmd_generate(args) -> None:
    service = load_service(args.state)
    created, unassigned = service.generate_plan()
    save_service(args.state, service)
    for arr in created:
        print(f"{arr.arrangement_id}：{arr.trainee_id} -> {arr.scenario_id}（等待三方确认）")
        for reason in arr.explanation:
            print(f"    理由：{reason}")
    for sid, reasons in unassigned.items():
        print(f"场景 {sid} 未安排：")
        for reason in reasons:
            print(f"    * {reason}")


def cmd_confirm(args) -> None:
    service = load_service(args.state)
    arr = service.confirm(args.arrangement, Party(args.party), note=args.note)
    save_service(args.state, service)
    print(f"{arr.arrangement_id} 当前状态 {arr.status.value}，待确认方 {[p.value for p in arr.pending_parties()]}")


def cmd_reject(args) -> None:
    service = load_service(args.state)
    arr = service.reject(args.arrangement, Party(args.party), note=args.note)
    save_service(args.state, service)
    print(f"{arr.arrangement_id} 已被 {args.party} 拒绝，安排取消")


def cmd_start(args) -> None:
    service = load_service(args.state)
    arr = service.start(args.arrangement)
    save_service(args.state, service)
    print(f"{arr.arrangement_id} 实践开始，禁止静默改派")


def cmd_complete(args) -> None:
    service = load_service(args.state)
    arr = service.complete(args.arrangement)
    save_service(args.state, service)
    print(f"{arr.arrangement_id} 实践办结，能力已计入学员档案")


def cmd_report(args) -> None:
    service = load_service(args.state)
    case, created = service.report_incident(
        IncidentType(args.type),
        Level[args.level.upper()],
        args.trainee,
        args.desc,
        reporter=args.by,
        arrangement_id=args.arrangement or "",
    )
    save_service(args.state, service)
    merged = "新建案件" if created else "归并到既有案件"
    print(f"{merged} {case.case_id}，级别 L{int(case.level)}，可见范围 {sorted(service.case_visibility(case.case_id))}")


def cmd_tick(args) -> None:
    service = load_service(args.state)
    escalated = service.advance_clock(hours=args.hours)
    save_service(args.state, service)
    if escalated:
        for case in escalated:
            print(f"案件 {case.case_id} 逾期升级为 L{int(case.level)}")
    else:
        print("时钟已推进，无逾期升级")


def cmd_capacity(args) -> None:
    service = load_service(args.state)
    service.set_mentor_capacity(args.mentor, args.capacity)
    save_service(args.state, service)
    print(f"导师 {args.mentor} 容量调整为 {args.capacity}，受影响安排已重新评估")


def cmd_blackout(args) -> None:
    service = load_service(args.state)
    service.add_unavailable_window(
        UnavailableWindow(
            owner_kind=args.kind,
            owner_id=args.owner,
            window=Window(date.fromisoformat(args.start), date.fromisoformat(args.end)),
            reason=args.reason,
        )
    )
    save_service(args.state, service)
    print(f"已登记不可用时段并重新评估受影响安排")


def cmd_summary(args) -> None:
    service = load_service(args.state)
    print_summary(service)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="跨国中文教师实践安排与在岗支持服务")
    parser.add_argument("--state", default=DEFAULT_STATE, help="状态文件路径")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("demo", help="内存演示全流程").set_defaults(func=cmd_demo)
    sub.add_parser("seed", help="写入演示数据").set_defaults(func=cmd_seed)
    sub.add_parser("generate", help="生成候选安排").set_defaults(func=cmd_generate)
    sub.add_parser("summary", help="每日汇总").set_defaults(func=cmd_summary)

    p = sub.add_parser("confirm", help="一方确认安排")
    p.add_argument("arrangement")
    p.add_argument("party", choices=[p.value for p in Party])
    p.add_argument("--note", default="")
    p.set_defaults(func=cmd_confirm)

    p = sub.add_parser("reject", help="一方拒绝安排")
    p.add_argument("arrangement")
    p.add_argument("party", choices=[p.value for p in Party])
    p.add_argument("--note", default="")
    p.set_defaults(func=cmd_reject)

    p = sub.add_parser("start", help="开始实践")
    p.add_argument("arrangement")
    p.set_defaults(func=cmd_start)

    p = sub.add_parser("complete", help="办结实践")
    p.add_argument("arrangement")
    p.set_defaults(func=cmd_complete)

    p = sub.add_parser("report", help="上报请假/教学事故/安全事件")
    p.add_argument("--type", required=True, choices=[t.value for t in IncidentType])
    p.add_argument("--level", required=True, choices=[l.name.lower() for l in Level])
    p.add_argument("--trainee", required=True)
    p.add_argument("--by", required=True, help="上报人")
    p.add_argument("--desc", required=True, help="事件描述")
    p.add_argument("--arrangement", default="")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("tick", help="推进可控制时钟并触发逾期升级")
    p.add_argument("--hours", type=float, required=True)
    p.set_defaults(func=cmd_tick)

    p = sub.add_parser("capacity", help="调整导师容量（触发重新评估）")
    p.add_argument("mentor")
    p.add_argument("capacity", type=int)
    p.set_defaults(func=cmd_capacity)

    p = sub.add_parser("blackout", help="登记不可用时段（触发重新评估）")
    p.add_argument("kind", choices=["trainee", "mentor", "site"])
    p.add_argument("owner")
    p.add_argument("start")
    p.add_argument("end")
    p.add_argument("reason")
    p.set_defaults(func=cmd_blackout)

    return parser


def main(argv=None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        args.func = cmd_demo
    args.func(args)


if __name__ == "__main__":
    main()
