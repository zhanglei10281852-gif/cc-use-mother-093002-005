"""实践办公室每日汇总。

运行汇总命令时先由可控时钟驱动一次逾期升级扫描，再呈现：
  1. 仍有冲突 / 待重新评估的安排；
  2. 各安排等待哪一方确认；
  3. 每名学员已覆盖与进行中安排将补齐的能力；
  4. 中断恢复后尚未办结的事件案件。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .domain import Competency, Role
from .incidents import Case, CaseStatus, IncidentKind
from .scheduler import Assignment, AssignmentStatus


@dataclass
class DailyReport:
    as_of: str
    conflicts: list[str] = field(default_factory=list)
    awaiting_confirmation: list[dict] = field(default_factory=list)
    competency_coverage: list[dict] = field(default_factory=list)
    open_cases: list[dict] = field(default_factory=list)
    escalated: list[str] = field(default_factory=list)

    def render_text(self) -> str:
        lines: list[str] = []
        lines.append(f"实践办公室每日汇总（{self.as_of}）")
        lines.append("=" * 56)

        lines.append(f"\n一、仍有冲突的安排（{len(self.conflicts)}）")
        if self.conflicts:
            lines.extend(f"  - {c}" for c in self.conflicts)
        else:
            lines.append("  无")

        lines.append(f"\n二、等待确认（{len(self.awaiting_confirmation)}）")
        if self.awaiting_confirmation:
            for item in self.awaiting_confirmation:
                lines.append(
                    f"  - {item['assignment_id']} 学员 {item['trainee_id']}"
                    f" -> {item['site_id']}/{item['mentor_id']}"
                    f" 待：{'、'.join(item['pending'])}"
                )
        else:
            lines.append("  无")

        lines.append(f"\n三、学员能力覆盖（{len(self.competency_coverage)} 人）")
        for item in self.competency_coverage:
            lines.append(f"  - {item['trainee_id']} {item['name']}")
            lines.append(f"      已覆盖：{item['covered'] or '无'}")
            if item["in_progress"]:
                lines.append(f"      在途将补齐：{item['in_progress']}")
            if item["missing"]:
                lines.append(f"      尚未覆盖：{item['missing']}")

        lines.append(f"\n四、尚未办结事件（{len(self.open_cases)}）")
        if self.open_cases:
            for c in self.open_cases:
                lines.append(
                    f"  - [{c['status']}] {c['case_id']} {c['kind']}（{c['level']}）"
                    f" 学员 {c['trainee_id']}：{c['title']}"
                )
                lines.append(
                    f"      可见：{'、'.join(c['visibility'])}；"
                    f"上报 {c['report_count']} 次；逾期升级 {c['escalations']} 次；"
                    f"截止 {c['deadline']}"
                )
        else:
            lines.append("  无")

        if self.escalated:
            lines.append(f"\n本次时钟推进新触发升级 {len(self.escalated)} 件：")
            lines.extend(f"  - {e}" for e in self.escalated)
        return "\n".join(lines)


def build_daily_report(service, *, sweep: bool = True) -> DailyReport:
    """以当前可控时钟时间生成汇总；sweep=True 时先处理逾期升级。"""
    clock = service.clock
    if sweep:
        escalated_cases = service.incidents.sweep_overdue()
    else:
        escalated_cases = []

    now = clock.now()
    report = DailyReport(
        as_of=f"{now:%Y-%m-%d %H:%M}",
        escalated=[f"{c.case_id} {c.title}" for c in escalated_cases],
    )

    # 1) 冲突：防御性全量扫描 + 待重新评估安排的具体原因
    report.conflicts.extend(service.scheduler.pairwise_conflicts())
    for a in service.assignments.values():
        if a.status == AssignmentStatus.NEEDS_REASSESSMENT:
            for reason in a.reassessment_reasons:
                report.conflicts.append(f"{a.assignment_id} 待重新评估：{reason}")
        if a.status == AssignmentStatus.STARTED and a.change_notices:
            report.conflicts.append(
                f"{a.assignment_id} 实践进行中但出现变更隐患（不自动改派）：{a.change_notices[-1]}"
            )

    # 2) 等待确认
    for a in service.assignments.values():
        if a.status in (AssignmentStatus.PROPOSED, AssignmentStatus.NEEDS_REASSESSMENT):
            report.awaiting_confirmation.append({
                "assignment_id": a.assignment_id,
                "trainee_id": a.trainee_id,
                "site_id": a.site_id,
                "mentor_id": a.mentor_id,
                "pending": [r.value for r in a.pending_parties()],
            })

    # 3) 能力覆盖
    active_gains: dict[str, set[Competency]] = {}
    for a in service.assignments.values():
        if a.status in (AssignmentStatus.CONFIRMED, AssignmentStatus.STARTED):
            active_gains.setdefault(a.trainee_id, set()).update(a.offered_competencies)
    all_competencies = list(Competency)
    for tid, trainee in service.trainees.items():
        covered = set(trainee.acquired_competencies)
        in_progress = active_gains.get(tid, set()) - covered
        missing = [c for c in all_competencies
                   if c not in covered and c not in active_gains.get(tid, set())]
        report.competency_coverage.append({
            "trainee_id": tid,
            "name": trainee.name,
            "covered": "、".join(c.value for c in sorted(covered, key=lambda x: x.value)),
            "in_progress": "、".join(c.value for c in sorted(in_progress, key=lambda x: x.value)),
            "missing": "、".join(c.value for c in missing),
        })

    # 4) 未办结事件（即中断恢复后的待办）
    for c in service.incidents.open_cases():
        report.open_cases.append({
            "case_id": c.case_id,
            "kind": c.kind.value,
            "level": c.level.name,
            "trainee_id": c.trainee_id,
            "title": c.title,
            "status": c.status.value,
            "visibility": [r.value for r in c.visibility],
            "report_count": c.report_count,
            "escalations": c.escalations,
            "deadline": f"{c.deadline:%Y-%m-%d %H:%M}" if c.deadline else "-",
        })
    return report
