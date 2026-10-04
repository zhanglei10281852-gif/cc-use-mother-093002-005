"""实践办公室命令行。

用法示例：
    python run_cli.py smoke                 # 基础契约冒烟
    python run_cli.py demo                  # 端到端情景演示（内存，不落地）
    python run_cli.py --data state.json init
    python run_cli.py --data state.json plan --trainee T01
    python run_cli.py --data state.json daily
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from teacher_practicum.contracts import PracticumSiteVersion, TraineeProfile
from teacher_practicum.domain import (
    DateRange,
    EventLevel,
    Language,
    Role,
)
from teacher_practicum.fixtures import build_demo_service
from teacher_practicum.incidents import IncidentKind
from teacher_practicum.reporting import build_daily_report
from teacher_practicum import storage


def cmd_smoke(_args) -> None:
    entity = PracticumSiteVersion("E-DEMO", "跨国中文教师实践安排", 1)
    record = TraineeProfile("R-DEMO", entity.entity_id, "已登记")
    print(json.dumps({"entity": entity.display_name, "revision": entity.revision,
                      "record_state": record.category}, ensure_ascii=False))


def cmd_demo(_args) -> None:
    svc = build_demo_service()

    print("# 1. 生成候选安排（可解释打分）")
    plan = svc.plan()
    for tid in ("T01", "T02", "T03"):
        c = plan.candidates[tid][0]
        print(f"  {tid} 最佳候选: {c.site_id}/{c.mentor_id}/{c.scenario_id} "
              f"{c.window.start}~{c.window.end} 得分 {c.score:.1f}")
        for line in c.explanation:
            print(f"      · {line}")
    print("  T04 无可行候选：")
    for reason in plan.infeasible["T04"][:3]:
        print(f"      · {reason}")

    a1 = svc.propose("T01", plan.candidates["T01"][0])
    a2 = svc.propose("T02", plan.candidates["T02"][0])
    a3 = svc.propose("T03", plan.candidates["T03"][0])

    print("\n# 2. 容量重复占用防护：再给 T04 尝试 M-B1（容量1已被 T01 占用）")
    svc.register_trainee("T05", "陈临",
                         languages={Language.THAI: "B1"}, acquired_competencies=set())
    plan5 = svc.plan(["T05"])
    blocked = [r for r in plan5.infeasible.get("T05", []) if "容量" in r]
    print(f"  {blocked[0] if blocked else '未发现容量问题（异常）'}")

    print("\n# 3. 三方确认（学校/导师/学院）")
    for party in (Role.SCHOOL, Role.MENTOR, Role.COLLEGE):
        done = svc.confirm(a1.assignment_id, party)
    print(f"  {a1.assignment_id} -> {a1.status.value}，集齐确认={done}")
    svc.confirm(a2.assignment_id, Role.SCHOOL)

    print("\n# 4. T01 已开始；导师突发收紧容量 → 仅提示，绝不静默改派")
    svc.clock.advance(days=30)
    svc.start(a1.assignment_id)
    svc.revise_mentor("M-B1", capacity=0)
    print(f"  {a1.assignment_id} 状态仍为：{a1.status.value}")
    print(f"  变更提示：{a1.change_notices[-1] if a1.change_notices else '无'}")

    print("\n# 5. 未开始的 T02 因学校校历调整进入待重新评估，随后显式改派")
    svc.revise_site("BKK", windows=[DateRange(date(2026, 11, 20), date(2026, 12, 25))])
    print(f"  {a2.assignment_id} -> {a2.status.value}：{a2.reassessment_reasons[0]}")
    new_plan = svc.plan(["T02"])
    a2_new = svc.replace_assignment(a2.assignment_id, new_plan.candidates["T02"][0])
    print(f"  旧 {a2.assignment_id} -> {a2.status.value}；新 {a2_new.assignment_id} "
          f"({a2_new.site_id}/{a2_new.mentor_id})")

    print("\n# 6. 事件：请假 / 教学事故 / 安全事件，分级可见、重复上报并案")
    leave, _ = svc.incidents.report(
        trainee_id="T01", kind=IncidentKind.LEAVE, level=EventLevel.LOW,
        title="病假两天", occurred_from=date(2026, 12, 2),
        occurred_to=date(2026, 12, 3), assignment_id=a1.assignment_id,
        site_id="BKK", actor=Role.MENTOR)
    dup, created = svc.incidents.report(
        trainee_id="T01", kind=IncidentKind.LEAVE, level=EventLevel.LOW,
        title="同一病假重复上报", occurred_from=date(2026, 12, 2),
        site_id="BKK", actor=Role.SCHOOL)
    print(f"  重复上报是否新建案件：{created}；案件 {dup.case_id} 上报次数 {dup.report_count}")
    safety, _ = svc.incidents.report(
        trainee_id="T01", kind=IncidentKind.SAFETY, level=EventLevel.SAFETY,
        title="通勤交通事故受轻伤", occurred_from=date(2026, 12, 5),
        assignment_id=a1.assignment_id, site_id="BKK", actor=Role.SCHOOL)
    print(f"  安全案 {safety.case_id} 可见：{'、'.join(r.value for r in safety.visibility)}")
    try:
        svc.incidents.acknowledge(safety.case_id, Role.MENTOR)
    except PermissionError as e:
        print(f"  导师越权查看被拒：{e}")
    svc.incidents.acknowledge(safety.case_id, Role.COLLEGE)
    svc.incidents.handle(safety.case_id, Role.COLLEGE, "送医检查无大碍，已通知家属")
    print(f"  安全案处置后状态：{safety.status.value}（须复盘才能办结）")

    print("\n# 7. 可控时钟推进 → 请假案逾期升级（低级别超过3天未受理）")
    svc.clock.advance(days=4)
    escalated = svc.incidents.sweep_overdue()
    print(f"  升级案件：{[c.case_id for c in escalated]}；{leave.case_id} "
          f"状态 {leave.status.value}，升级 {leave.escalations} 次")

    print("\n# 8. 中断恢复：保存后重新加载，未办结事件仍在")
    tmp = Path("demo_state.json")
    storage.save(svc, tmp)
    restored = storage.load(tmp)
    print(f"  恢复后未办结案件：{[c.case_id for c in restored.incidents.open_cases()]}")
    tmp.unlink()

    print("\n# 9. 每日汇总")
    print(build_daily_report(svc).render_text())


def _load(args):
    if not args.data or not Path(args.data).exists():
        raise SystemExit(f"数据文件不存在：{args.data}（先运行 init）")
    return storage.load(args.data)


def cmd_init(args) -> None:
    svc = build_demo_service()
    storage.save(svc, args.data)
    print(f"已初始化：{args.data}（2 个合作点、3 名导师、4 名学员）")


def cmd_plan(args) -> None:
    svc = _load(args)
    plan = svc.plan([args.trainee] if args.trainee else None)
    for tid, ranked in plan.candidates.items():
        c = ranked[0]
        print(f"{tid}: {c.site_id}/{c.mentor_id}/{c.scenario_id} "
              f"{c.window.start}~{c.window.end} 得分 {c.score:.1f}")
        for line in c.explanation:
            print(f"    · {line}")
    for tid, reasons in plan.infeasible.items():
        print(f"{tid}: 无可行候选")
        for r in reasons:
            print(f"    · {r}")


def cmd_propose(args) -> None:
    svc = _load(args)
    a = svc.propose(args.trainee)
    storage.save(svc, args.data)
    print(f"已生成 {a.assignment_id}：{a.site_id}/{a.mentor_id}/{a.scenario_id}，{a.status.value}")


def cmd_confirm(args) -> None:
    svc = _load(args)
    party = Role(args.party)
    svc.confirm(args.assignment, party)
    storage.save(svc, args.data)
    a = svc.assignments[args.assignment]
    print(f"{a.assignment_id} {a.status.value}；待确认：{'、'.join(r.value for r in a.pending_parties()) or '无'}")


def cmd_start(args) -> None:
    svc = _load(args)
    svc.start(args.assignment)
    storage.save(svc, args.data)
    print(f"{args.assignment} 已开始")


def cmd_report_incident(args) -> None:
    svc = _load(args)
    kind = IncidentKind(args.kind)
    level = EventLevel[args.level]
    case, created = svc.incidents.report(
        trainee_id=args.trainee, kind=kind, level=level, title=args.title,
        occurred_from=date.fromisoformat(args.date), site_id=args.site,
        actor=Role(args.actor))
    storage.save(svc, args.data)
    print(f"{'新建案件' if created else '重复上报已并案'} {case.case_id}，"
          f"可见：{'、'.join(r.value for r in case.visibility)}")


def cmd_tick(args) -> None:
    svc = _load(args)
    svc.clock.advance(days=args.days, hours=args.hours)
    escalated = svc.incidents.sweep_overdue()
    storage.save(svc, args.data)
    print(f"时钟推进至 {svc.clock.now():%Y-%m-%d %H:%M}；新升级 {len(escalated)} 件")


def cmd_daily(args) -> None:
    svc = _load(args)
    print(build_daily_report(svc).render_text())
    storage.save(svc, args.data)


def main() -> None:
    parser = argparse.ArgumentParser(description="跨国中文教师实践安排与在岗支持")
    parser.add_argument("--data", default="practicum_state.json", help="状态快照文件")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("smoke").set_defaults(func=cmd_smoke)
    sub.add_parser("demo").set_defaults(func=cmd_demo)
    sub.add_parser("init").set_defaults(func=cmd_init)

    p_plan = sub.add_parser("plan", help="生成候选安排")
    p_plan.add_argument("--trainee")
    p_plan.set_defaults(func=cmd_plan)

    p_prop = sub.add_parser("propose", help="为学员建立安排")
    p_prop.add_argument("--trainee", required=True)
    p_prop.set_defaults(func=cmd_propose)

    p_conf = sub.add_parser("confirm", help="某一方确认")
    p_conf.add_argument("assignment")
    p_conf.add_argument("--party", required=True,
                        choices=[r.value for r in Role])
    p_conf.set_defaults(func=cmd_confirm)

    p_start = sub.add_parser("start", help="实践开始")
    p_start.add_argument("assignment")
    p_start.set_defaults(func=cmd_start)

    p_inc = sub.add_parser("incident", help="上报事件")
    p_inc.add_argument("--trainee", required=True)
    p_inc.add_argument("--kind", required=True, choices=[k.value for k in IncidentKind])
    p_inc.add_argument("--level", required=True, choices=[e.name for e in EventLevel])
    p_inc.add_argument("--title", required=True)
    p_inc.add_argument("--date", required=True, help="YYYY-MM-DD")
    p_inc.add_argument("--site")
    p_inc.add_argument("--actor", default=Role.MENTOR.value, choices=[r.value for r in Role])
    p_inc.set_defaults(func=cmd_report_incident)

    p_tick = sub.add_parser("tick", help="推进可控时钟并扫描逾期")
    p_tick.add_argument("--days", type=int, default=0)
    p_tick.add_argument("--hours", type=int, default=0)
    p_tick.set_defaults(func=cmd_tick)

    sub.add_parser("daily", help="每日汇总").set_defaults(func=cmd_daily)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
