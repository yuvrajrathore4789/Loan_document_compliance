"""Exception lifecycle: creation from rule results, reviewer workflow, immutable history.

Status machine (reviewer actions):
  OPEN/REOPENED -> IN_REVIEW | AWAITING_DOCUMENTS | ESCALATED | RESOLVED
  IN_REVIEW     -> OPEN | AWAITING_DOCUMENTS | ESCALATED | RESOLVED
  AWAITING_DOCUMENTS -> IN_REVIEW | OPEN | ESCALATED | RESOLVED
  ESCALATED     -> IN_REVIEW | RESOLVED (resolving an escalated exception needs the admin role)
  RESOLVED      -> REOPENED
Every change writes a ``reviews`` row and an append-only audit event.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import utcnow
from app.models import Application, AppStatus, ExceptionRecord, ExcStatus, Review, VerificationResult
from app.services import audit_service as audit
from app.services.verification_engine import FAIL, WARN, exception_category

S = ExcStatus
TRANSITIONS: dict[str, set[str]] = {
    S.OPEN.value: {S.IN_REVIEW.value, S.AWAITING_DOCUMENTS.value, S.ESCALATED.value, S.RESOLVED.value},
    S.REOPENED.value: {S.IN_REVIEW.value, S.AWAITING_DOCUMENTS.value, S.ESCALATED.value, S.RESOLVED.value},
    S.IN_REVIEW.value: {S.OPEN.value, S.AWAITING_DOCUMENTS.value, S.ESCALATED.value, S.RESOLVED.value},
    S.AWAITING_DOCUMENTS.value: {S.IN_REVIEW.value, S.OPEN.value, S.ESCALATED.value, S.RESOLVED.value},
    S.ESCALATED.value: {S.IN_REVIEW.value, S.RESOLVED.value},
    S.RESOLVED.value: {S.REOPENED.value},
}
ACTION_FOR_STATUS = {S.IN_REVIEW.value: "START_REVIEW", S.RESOLVED.value: "RESOLVE", S.ESCALATED.value: "ESCALATE",
                     S.AWAITING_DOCUMENTS.value: "REQUEST_DOCUMENTS", S.REOPENED.value: "REOPEN", S.OPEN.value: "RELEASE"}
COMMENT_REQUIRED = {S.RESOLVED.value, S.ESCALATED.value, S.AWAITING_DOCUMENTS.value, S.REOPENED.value}


class ExceptionWorkflowError(ValueError):
    """Invalid transition / missing comment. ``status_code`` is used by the API layer."""

    def __init__(self, msg: str, status_code: int = 409):
        super().__init__(msg)
        self.status_code = status_code


def _state(e: ExceptionRecord) -> dict:
    return {"status": e.status, "assigned_reviewer": e.assigned_reviewer, "severity": e.severity}


def _dedupe_key(rule_id: str, field: str | None, doc_ids: list[str]) -> str:
    return f"{rule_id}|{field or ''}|{','.join(sorted(set(doc_ids)))}"[:300]


def sync_exceptions(db: Session, app: Application, run_id: str, results: list[VerificationResult], rules: dict,
                    actor: str) -> tuple[int, int]:
    """Create exceptions for FAIL/WARN results; auto-resolve open ones whose condition is gone.

    Re-running verification never duplicates exceptions (unique dedupe key) and never reopens an
    exception a human has resolved. Returns (created, auto_resolved)."""
    desired: dict[str, VerificationResult] = {}
    for r in results:
        if r.outcome in (FAIL, WARN):
            desired.setdefault(_dedupe_key(r.rule_id, r.field, r.document_ids or []), r)
    existing = {e.dedupe_key: e for e in db.scalars(select(ExceptionRecord).where(ExceptionRecord.application_id == app.id))}
    created = resolved = 0
    for key, r in desired.items():
        evidence = {"run_id": run_id, "rule_version": r.rule_version, "outcome": r.outcome, "field": r.field,
                    "expected": r.expected, "observed": r.observed, "document_ids": r.document_ids or [],
                    "details": getattr(r, "_evidence", {})}
        e = existing.get(key)
        if e:
            if e.status != S.RESOLVED.value:
                e.evidence, e.description, e.severity, e.run_id = evidence, r.explanation, r.severity, run_id
            continue
        rule = rules.get(r.rule_id)
        e = ExceptionRecord(id="EXC-" + uuid.uuid4().hex[:8].upper(), application_id=app.id, rule_id=r.rule_id,
                            category=exception_category(r.rule_id, rule.kind if rule else "builtin"), severity=r.severity,
                            description=r.explanation, evidence=evidence, status=S.OPEN.value, dedupe_key=key, run_id=run_id)
        db.add(e)
        db.flush()
        audit.log_event(db, actor, "EXCEPTION_CREATED", "exception", e.id, None, _state(e),
                        {"rule_id": e.rule_id, "rule_version": r.rule_version, "application_id": app.id, "category": e.category})
        created += 1
    for key, e in existing.items():
        if key not in desired and e.status != S.RESOLVED.value:
            prev = _state(e)
            e.status, e.resolved_at = S.RESOLVED.value, utcnow()
            e.resolution_seconds = (e.resolved_at - e.created_at).total_seconds()
            db.add(Review(exception_id=e.id, reviewer="system", action="AUTO_RESOLVE",
                          comment="Condition no longer detected on re-verification."))
            audit.log_event(db, "system", "EXCEPTION_AUTO_RESOLVED", "exception", e.id, prev, _state(e), {"run_id": run_id})
            resolved += 1
    db.flush()
    return created, resolved


def get_exception(db: Session, exception_id: str) -> ExceptionRecord:
    e = db.get(ExceptionRecord, exception_id)
    if e is None:
        raise ExceptionWorkflowError("Exception not found.", 404)
    return e


def _refresh_app_status(db: Session, app_id: str) -> None:
    app = db.get(Application, app_id)
    if app is None or app.last_verified_at is None:
        return
    open_n = db.scalar(select(ExceptionRecord.id).where(ExceptionRecord.application_id == app_id,
                                                        ExceptionRecord.status != S.RESOLVED.value).limit(1))
    app.status = AppStatus.EXCEPTION_DETECTED.value if open_n else AppStatus.VERIFIED.value


def change_status(db: Session, e: ExceptionRecord, new_status: str, actor: str, role: str,
                  comment: str | None = None, assignee: str | None = None) -> ExceptionRecord:
    if new_status not in {s.value for s in S}:
        raise ExceptionWorkflowError(f"Unknown status '{new_status}'.", 422)
    if new_status not in TRANSITIONS.get(e.status, set()):
        raise ExceptionWorkflowError(f"Cannot move an exception from {e.status} to {new_status}.", 409)
    if e.status == S.ESCALATED.value and new_status == S.RESOLVED.value and role != "admin":
        raise ExceptionWorkflowError("Only an administrator can resolve an escalated exception.", 403)
    if new_status in COMMENT_REQUIRED and not (comment and comment.strip()):
        raise ExceptionWorkflowError("A comment is required for this action.", 422)
    prev = _state(e)
    e.status = new_status
    if assignee is not None:
        e.assigned_reviewer = assignee
    elif new_status == S.IN_REVIEW.value and not e.assigned_reviewer:
        e.assigned_reviewer = actor
    if new_status == S.RESOLVED.value:
        e.resolved_at = utcnow()
        e.resolution_seconds = (e.resolved_at - e.created_at).total_seconds()
    elif new_status == S.REOPENED.value:
        e.resolved_at, e.resolution_seconds = None, None
    db.add(Review(exception_id=e.id, reviewer=actor, action=ACTION_FOR_STATUS[new_status], comment=(comment or "").strip() or None))
    audit.log_event(db, actor, f"EXCEPTION_{ACTION_FOR_STATUS[new_status]}", "exception", e.id, prev, _state(e),
                    {"comment": (comment or "").strip() or None, "application_id": e.application_id})
    db.flush()
    _refresh_app_status(db, e.application_id)
    return e


def add_comment(db: Session, e: ExceptionRecord, actor: str, comment: str) -> Review:
    if not comment or not comment.strip():
        raise ExceptionWorkflowError("Comment cannot be empty.", 422)
    rv = Review(exception_id=e.id, reviewer=actor, action="COMMENT", comment=comment.strip())
    db.add(rv)
    audit.log_event(db, actor, "EXCEPTION_COMMENTED", "exception", e.id, None, None,
                    {"comment": comment.strip(), "application_id": e.application_id})
    db.flush()
    return rv


def assign(db: Session, e: ExceptionRecord, reviewer: str | None, actor: str) -> ExceptionRecord:
    prev = _state(e)
    e.assigned_reviewer = reviewer
    db.add(Review(exception_id=e.id, reviewer=actor, action="ASSIGN", comment=f"Assigned to {reviewer or 'nobody'}"))
    audit.log_event(db, actor, "EXCEPTION_ASSIGNED", "exception", e.id, prev, _state(e), {"application_id": e.application_id})
    db.flush()
    return e
