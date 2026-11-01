"""Append-only audit trail.

* ``log_event`` only ever INSERTs. There is no update/delete function and no API for them.
* ORM listeners raise on UPDATE/DELETE of AuditLog objects, and SQLite triggers (see models)
  reject raw UPDATE/DELETE statements as defence in depth.

NOTE: application-level append-only logging is NOT equivalent to independently tamper-proof
regulatory storage (WORM storage, external hash-chaining/anchoring, restricted DB credentials).
Anyone with direct database administrator access could still alter this table.
"""
from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime
from typing import Any, Iterable

from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.models import AuditLog

CSV_COLUMNS = ["event_id", "created_at", "actor", "action", "resource_type", "resource_id",
               "previous_state", "new_state", "details"]


class AuditImmutableError(RuntimeError):
    pass


@event.listens_for(AuditLog, "before_update")
def _block_update(mapper, connection, target):  # noqa: ANN001
    raise AuditImmutableError("Audit events are append-only and cannot be modified.")


@event.listens_for(AuditLog, "before_delete")
def _block_delete(mapper, connection, target):  # noqa: ANN001
    raise AuditImmutableError("Audit events are append-only and cannot be deleted.")


def log_event(db: Session, actor: str, action: str, resource_type: str, resource_id: str,
              previous_state: dict | None = None, new_state: dict | None = None,
              details: dict | None = None) -> AuditLog:
    """Record one event (flushed, committed with the caller's transaction)."""
    ev = AuditLog(event_id=str(uuid.uuid4()), actor=actor, action=action, resource_type=resource_type,
                  resource_id=str(resource_id), previous_state=previous_state, new_state=new_state, details=details)
    db.add(ev)
    db.flush()
    return ev


def query_events(db: Session, resource_type: str | None = None, resource_id: str | None = None,
                 action: str | None = None, actor: str | None = None, since: datetime | None = None,
                 until: datetime | None = None, limit: int = 500, offset: int = 0) -> list[AuditLog]:
    q = select(AuditLog).order_by(AuditLog.id.desc())
    if resource_type:
        q = q.where(AuditLog.resource_type == resource_type)
    if resource_id:
        q = q.where(AuditLog.resource_id == resource_id)
    if action:
        q = q.where(AuditLog.action == action)
    if actor:
        q = q.where(AuditLog.actor == actor)
    if since:
        q = q.where(AuditLog.created_at >= since)
    if until:
        q = q.where(AuditLog.created_at <= until)
    return list(db.scalars(q.limit(max(1, min(limit, 5000))).offset(max(0, offset))))


def _csv_safe(v: Any) -> str:
    """Neutralise spreadsheet formula injection in exported cells."""
    s = "" if v is None else (v if isinstance(v, str) else __import__("json").dumps(v, default=str, sort_keys=True))
    return "'" + s if s[:1] in "=+-@\t\r" else s


def events_to_csv(events: Iterable[AuditLog]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_COLUMNS)
    for e in events:
        w.writerow([e.event_id, e.created_at.isoformat(timespec="seconds"), _csv_safe(e.actor), _csv_safe(e.action),
                    _csv_safe(e.resource_type), _csv_safe(e.resource_id), _csv_safe(e.previous_state), _csv_safe(e.new_state), _csv_safe(e.details)])
    return buf.getvalue()
