from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app import database
from app.config import SYNTHETIC_NOTICE
from app.deps import CurrentUser, get_current_user
from app.schemas import api as S
from app.services import analytics, audit_service as audit

router = APIRouter(prefix="/api", tags=["analytics & audit"])
AUDIT_NOTICE = ("Application-level append-only audit log (ORM guards + SQLite triggers). It is NOT independently tamper-proof "
                "regulatory storage: a database administrator could still alter it.")


@router.get("/analytics/overview")
def overview(_: CurrentUser = Depends(get_current_user), db: Session = Depends(database.get_db)):
    return {**analytics.overview(db), "notice": SYNTHETIC_NOTICE}


@router.get("/analytics/exceptions")
def exceptions(_: CurrentUser = Depends(get_current_user), db: Session = Depends(database.get_db)):
    return analytics.exception_analytics(db)


@router.get("/analytics/document-processing")
def doc_processing(_: CurrentUser = Depends(get_current_user), db: Session = Depends(database.get_db)):
    return analytics.document_processing(db)


@router.get("/analytics/audit")
def audit_stats(_: CurrentUser = Depends(get_current_user), db: Session = Depends(database.get_db)):
    from sqlalchemy import func, select
    from app.models import AuditLog
    by_action = db.execute(select(AuditLog.action, func.count()).group_by(AuditLog.action).order_by(func.count().desc())).all()
    by_actor = db.execute(select(AuditLog.actor, func.count()).group_by(AuditLog.actor).order_by(func.count().desc()).limit(10)).all()
    return {"total_events": db.scalar(select(func.count(AuditLog.id))) or 0,
            "by_action": [{"action": a, "count": c} for a, c in by_action],
            "by_actor": [{"actor": a, "count": c} for a, c in by_actor], "notice": AUDIT_NOTICE}


def _events(db, resource_type, resource_id, action, actor, since, until, limit, offset):
    return audit.query_events(db, resource_type, resource_id, action, actor, since, until, limit, offset)


@router.get("/audit", response_model=list[S.AuditOut])
def audit_events(resource_type: str | None = None, resource_id: str | None = None, action: str | None = None, actor: str | None = None,
                 since: datetime | None = None, until: datetime | None = None, limit: int = Query(200, ge=1, le=5000),
                 offset: int = Query(0, ge=0), _: CurrentUser = Depends(get_current_user), db: Session = Depends(database.get_db)):
    return _events(db, resource_type, resource_id, action, actor, since, until, limit, offset)


@router.get("/audit/export.csv", response_class=PlainTextResponse)
def audit_csv(resource_type: str | None = None, resource_id: str | None = None, action: str | None = None, actor: str | None = None,
              since: datetime | None = None, until: datetime | None = None, limit: int = Query(5000, ge=1, le=5000),
              user: CurrentUser = Depends(get_current_user), db: Session = Depends(database.get_db)):
    ev = _events(db, resource_type, resource_id, action, actor, since, until, limit, 0)
    audit.log_event(db, user.username, "AUDIT_EXPORTED", "audit", "csv", None, None, {"rows": len(ev)})
    db.commit()
    return PlainTextResponse(audit.events_to_csv(ev), media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="audit_log.csv"'})
