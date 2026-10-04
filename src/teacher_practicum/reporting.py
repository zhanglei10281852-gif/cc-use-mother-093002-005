"""实践办公室每日汇总：冲突安排、待确认方、能力覆盖与未办结事件。"""
from __future__ import annotations

from .arrangements import ACTIVE_STATUSES, ArrangementStatus
from .incidents import CaseStatus

_PARTY_LABELS = {"school": "学校", "mentor": "导师", "college": "学院"}
_TYPE_LABELS = {"leave": "请假", "teaching_accident": "教学事故", "safety": "安全事件"}
_STATUS_LABELS = {
    "open": "待受理",
    "acknowledged": "已受理",
    "resolved": "已处置",
    "retrospected": "已复盘",
}


def build_daily_summary(service) -> dict:
    conflicted = []
    pending = []
    for arr in sorted(service.arrangements.values(), key=lambda a: a.arrangement_id):
        if arr.status in ACTIVE_STATUSES and arr.conflicts:
            conflicted.append(
                {
                    "arrangement_id": arr.arrangement_id,
                    "trainee": service.trainees[arr.trainee_id].name,
                    "scenario": service.scenarios[arr.scenario_id].title,
                    "status": arr.status.value,
                    "conflicts": [f"{c.code}: {c.detail}" for c in arr.conflicts],
                }
            )
        waiting = arr.pending_parties()
        if waiting:
            pending.append(
                {
                    "arrangement_id": arr.arrangement_id,
                    "trainee": service.trainees[arr.trainee_id].name,
                    "scenario": service.scenarios[arr.scenario_id].title,
                    "waiting_on": [p.value for p in waiting],
                }
            )

    coverage = []
    planned_by_trainee: dict = {}
    for arr in service.arrangements.values():
        if arr.status in ACTIVE_STATUSES:
            planned_by_trainee.setdefault(arr.trainee_id, set()).update(
                service.scenarios[arr.scenario_id].competencies
            )
    for trainee in sorted(service.trainees.values(), key=lambda t: t.trainee_id):
        planned = planned_by_trainee.get(trainee.trainee_id, set())
        covered = set(trainee.covered_competencies)
        target = set(trainee.target_competencies)
        coverage.append(
            {
                "trainee_id": trainee.trainee_id,
                "name": trainee.name,
                "covered": sorted(covered),
                "planned": sorted(planned - covered),
                "target": sorted(target),
                "gap": sorted(target - covered - planned),
            }
        )

    unresolved = []
    for case in sorted(service.cases.values(), key=lambda c: c.case_id):
        if case.status == CaseStatus.CLOSED:
            continue
        unresolved.append(
            {
                "case_id": case.case_id,
                "type": case.incident_type.value,
                "level": int(case.level),
                "trainee": service.trainees[case.trainee_id].name,
                "status": case.status.value,
                "due_at": case.due_at,
                "escalated": case.escalated,
                "report_count": len(case.reports),
                "visible_to": sorted(service.case_visibility(case.case_id)),
            }
        )

    unassigned = [
        {"scenario_id": sid, "reasons": reasons}
        for sid, reasons in sorted(service.last_unassigned.items())
    ]
    return {
        "conflicted_arrangements": conflicted,
        "pending_confirmations": pending,
        "competency_coverage": coverage,
        "unresolved_cases": unresolved,
        "unassigned_scenarios": unassigned,
    }


def format_summary(summary: dict) -> str:
    lines = ["===== 实践办公室每日汇总 ====="]

    lines.append("\n[仍有冲突的安排]")
    if summary["conflicted_arrangements"]:
        for item in summary["conflicted_arrangements"]:
            lines.append(
                f"- {item['arrangement_id']} {item['trainee']} / {item['scenario']}"
                f"（{item['status']}）"
            )
            for conflict in item["conflicts"]:
                lines.append(f"    * {conflict}")
    else:
        lines.append("- 无")

    lines.append("\n[等待确认的安排]")
    if summary["pending_confirmations"]:
        for item in summary["pending_confirmations"]:
            waiting = "、".join(_PARTY_LABELS[p] for p in item["waiting_on"])
            lines.append(
                f"- {item['arrangement_id']} {item['trainee']} / {item['scenario']}：等待 {waiting} 确认"
            )
    else:
        lines.append("- 无")

    lines.append("\n[学员能力覆盖]")
    for item in summary["competency_coverage"]:
        covered = ",".join(item["covered"]) or "无"
        planned = ",".join(item["planned"]) or "无"
        gap = ",".join(item["gap"]) or "无"
        lines.append(
            f"- {item['name']}：已覆盖[{covered}] 计划中[{planned}] 缺口[{gap}]"
        )

    lines.append("\n[未办结事件]")
    if summary["unresolved_cases"]:
        for item in summary["unresolved_cases"]:
            label = _TYPE_LABELS.get(item["type"], item["type"])
            status = _STATUS_LABELS.get(item["status"], item["status"])
            flag = "，已升级" if item["escalated"] else ""
            lines.append(
                f"- {item['case_id']} {label} L{item['level']} {item['trainee']}：{status}{flag}"
                f"，上报 {item['report_count']} 次，可见范围 {','.join(item['visible_to'])}"
            )
    else:
        lines.append("- 无")

    if summary["unassigned_scenarios"]:
        lines.append("\n[未安排的课程场景]")
        for item in summary["unassigned_scenarios"]:
            lines.append(f"- {item['scenario_id']}")
            for reason in item["reasons"]:
                lines.append(f"    * {reason}")

    return "\n".join(lines)
