"""JSON 快照持久化：支持实践办公室中断后恢复全部在排与在办状态。"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from .clock import Clock
from .contracts import PracticumSiteVersion, TraineeProfile
from .domain import (
    Competency,
    CourseScenario,
    DateRange,
    EventLevel,
    Language,
    LanguageRequirement,
    Mentor,
    PartnerSite,
    ReportScope,
    Role,
    Trainee,
)
from .incidents import (
    Case,
    CaseStatus,
    IncidentKind,
    IncidentRegistry,
    TimelineEntry,
)
from .scheduler import Assignment, AssignmentStatus
from .service import PracticumService


def _d(d: date) -> str:
    return d.isoformat()


def _date(s: str) -> date:
    return date.fromisoformat(s)


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def _range(rng: DateRange) -> list[str]:
    return [_d(rng.start), _d(rng.end)]


def _unrange(pair: list[str]) -> DateRange:
    return DateRange(_date(pair[0]), _date(pair[1]))


def save(service: PracticumService, path: str | Path) -> None:
    data = {
        "clock": service.clock.now().isoformat(timespec="seconds"),
        "seq": service._seq,
        "incident_seq": service.incidents._seq,
        "sites": [_encode_site(s) for s in service.sites.values()],
        "mentors": [_encode_mentor(m) for m in service.mentors.values()],
        "trainees": [_encode_trainee(t) for t in service.trainees.values()],
        "assignments": [_encode_assignment(a) for a in service.assignments.values()],
        "cases": [_encode_case(c) for c in service.incidents.cases.values()],
    }
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load(path: str | Path, clock: Clock | None = None) -> PracticumService:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    service = PracticumService(clock=clock or Clock(_dt(data["clock"])))

    for raw in data["sites"]:
        scope = raw["report_scope"]
        service.sites[raw["site_id"]] = PartnerSite(
            version=PracticumSiteVersion(raw["site_id"], raw["name"], raw["revision"]),
            country=raw["country"],
            windows=[_unrange(w) for w in raw["windows"]],
            scenarios=[
                CourseScenario(
                    scenario_id=s["scenario_id"], title=s["title"],
                    learner_type=s["learner_type"],
                    language_requirement=LanguageRequirement(
                        Language(s["language"]), s["min_level"]),
                    competencies=frozenset(Competency(c) for c in s["competencies"]),
                )
                for s in raw["scenarios"]
            ],
            report_scope=(ReportScope(
                threshold=EventLevel(scope["threshold"]),
                extra_recipients=frozenset(Role(r) for r in scope["extra_recipients"]),
            ) if scope else None),
        )

    for raw in data["mentors"]:
        service.mentors[raw["mentor_id"]] = Mentor(
            mentor_id=raw["mentor_id"], name=raw["name"], site_id=raw["site_id"],
            capacity=raw["capacity"], revision=raw["revision"],
            language_requirements=frozenset(
                LanguageRequirement(Language(r["language"]), r["min_level"])
                for r in raw["language_requirements"]),
            competencies=frozenset(Competency(c) for c in raw["competencies"]),
            unavailable=[_unrange(w) for w in raw["unavailable"]],
        )

    for raw in data["trainees"]:
        service.trainees[raw["trainee_id"]] = Trainee(
            profile=TraineeProfile(raw["record_id"], raw["trainee_id"], raw["category"]),
            name=raw["name"],
            languages={Language(k): v for k, v in raw["languages"].items()},
            acquired_competencies={Competency(c) for c in raw["competencies"]},
            unavailable=[_unrange(w) for w in raw["unavailable"]],
        )

    for raw in data["assignments"]:
        service.assignments[raw["assignment_id"]] = Assignment(
            assignment_id=raw["assignment_id"], trainee_id=raw["trainee_id"],
            site_id=raw["site_id"], site_revision=raw["site_revision"],
            mentor_id=raw["mentor_id"], mentor_revision=raw["mentor_revision"],
            scenario_id=raw["scenario_id"], window=_unrange(raw["window"]),
            offered_competencies=frozenset(Competency(c) for c in raw["offered_competencies"]),
            expected_gain=frozenset(Competency(c) for c in raw["expected_gain"]),
            score=raw["score"], explanation=list(raw["explanation"]),
            status=AssignmentStatus(raw["status"]),
            confirmations={Role(k): _dt(v) for k, v in raw["confirmations"].items()},
            reassessment_reasons=list(raw["reassessment_reasons"]),
            change_notices=list(raw["change_notices"]),
            revision_notes=list(raw.get("revision_notes", [])),
            superseded_by=raw["superseded_by"],
            created_at=_dt(raw["created_at"]) if raw["created_at"] else None,
            updated_at=_dt(raw["updated_at"]) if raw["updated_at"] else None,
            started_at=_dt(raw["started_at"]) if raw["started_at"] else None,
            completed_at=_dt(raw["completed_at"]) if raw["completed_at"] else None,
            log=list(raw["log"]),
        )

    reg = service.incidents
    for raw in data["cases"]:
        reg.cases[raw["case_id"]] = Case(
            case_id=raw["case_id"], trainee_id=raw["trainee_id"],
            kind=IncidentKind(raw["kind"]), level=EventLevel(raw["level"]),
            title=raw["title"], occurred_from=_date(raw["occurred_from"]),
            occurred_to=_date(raw["occurred_to"]),
            assignment_id=raw["assignment_id"], site_id=raw["site_id"],
            visibility=frozenset(Role(r) for r in raw["visibility"]),
            status=CaseStatus(raw["status"]),
            created_at=_dt(raw["created_at"]) if raw["created_at"] else None,
            updated_at=_dt(raw["updated_at"]) if raw["updated_at"] else None,
            deadline=_dt(raw["deadline"]) if raw["deadline"] else None,
            escalations=raw["escalations"], report_count=raw["report_count"],
            review=raw["review"], resolution=raw["resolution"],
            timeline=[TimelineEntry(_dt(t["at"]), Role(t["actor"]), t["text"])
                      for t in raw["timeline"]],
        )

    service._seq = data["seq"]
    reg._seq = data["incident_seq"]
    return service


# ---------------------------------------------------------------------------
# 编码
# ---------------------------------------------------------------------------

def _encode_site(s: PartnerSite) -> dict:
    return {
        "site_id": s.site_id, "name": s.version.display_name, "revision": s.revision,
        "country": s.country,
        "windows": [_range(w) for w in s.windows],
        "scenarios": [{
            "scenario_id": sc.scenario_id, "title": sc.title,
            "learner_type": sc.learner_type,
            "language": sc.language_requirement.language.value,
            "min_level": sc.language_requirement.min_level,
            "competencies": [c.value for c in sc.competencies],
        } for sc in s.scenarios],
        "report_scope": (None if s.report_scope is None else {
            "threshold": int(s.report_scope.threshold),
            "extra_recipients": [r.value for r in s.report_scope.extra_recipients],
        }),
    }


def _encode_mentor(m: Mentor) -> dict:
    return {
        "mentor_id": m.mentor_id, "name": m.name, "site_id": m.site_id,
        "capacity": m.capacity, "revision": m.revision,
        "language_requirements": [
            {"language": r.language.value, "min_level": r.min_level}
            for r in m.language_requirements],
        "competencies": [c.value for c in m.competencies],
        "unavailable": [_range(u) for u in m.unavailable],
    }


def _encode_trainee(t: Trainee) -> dict:
    return {
        "trainee_id": t.trainee_id, "record_id": t.profile.record_id,
        "category": t.profile.category, "name": t.name,
        "languages": {k.value: v for k, v in t.languages.items()},
        "competencies": [c.value for c in t.acquired_competencies],
        "unavailable": [_range(u) for u in t.unavailable],
    }


def _encode_assignment(a: Assignment) -> dict:
    return {
        "assignment_id": a.assignment_id, "trainee_id": a.trainee_id,
        "site_id": a.site_id, "site_revision": a.site_revision,
        "mentor_id": a.mentor_id, "mentor_revision": a.mentor_revision,
        "scenario_id": a.scenario_id, "window": _range(a.window),
        "offered_competencies": [c.value for c in a.offered_competencies],
        "expected_gain": [c.value for c in a.expected_gain],
        "score": a.score, "explanation": a.explanation, "status": a.status.value,
        "confirmations": {k.value: v.isoformat(timespec="seconds")
                          for k, v in a.confirmations.items()},
        "reassessment_reasons": a.reassessment_reasons,
        "change_notices": a.change_notices,
        "revision_notes": a.revision_notes, "superseded_by": a.superseded_by,
        "created_at": a.created_at.isoformat(timespec="seconds") if a.created_at else None,
        "updated_at": a.updated_at.isoformat(timespec="seconds") if a.updated_at else None,
        "started_at": a.started_at.isoformat(timespec="seconds") if a.started_at else None,
        "completed_at": a.completed_at.isoformat(timespec="seconds") if a.completed_at else None,
        "log": a.log,
    }


def _encode_case(c: Case) -> dict:
    return {
        "case_id": c.case_id, "trainee_id": c.trainee_id, "kind": c.kind.value,
        "level": int(c.level), "title": c.title,
        "occurred_from": _d(c.occurred_from), "occurred_to": _d(c.occurred_to),
        "assignment_id": c.assignment_id, "site_id": c.site_id,
        "visibility": [r.value for r in c.visibility], "status": c.status.value,
        "created_at": c.created_at.isoformat(timespec="seconds") if c.created_at else None,
        "updated_at": c.updated_at.isoformat(timespec="seconds") if c.updated_at else None,
        "deadline": c.deadline.isoformat(timespec="seconds") if c.deadline else None,
        "escalations": c.escalations, "report_count": c.report_count,
        "review": c.review, "resolution": c.resolution,
        "timeline": [{"at": f"{e.at:%Y-%m-%dT%H:%M:%S}", "actor": e.actor.value,
                      "text": e.text} for e in c.timeline],
    }
