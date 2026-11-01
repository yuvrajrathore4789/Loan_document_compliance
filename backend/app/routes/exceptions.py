from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import database
from app.deps import CurrentUser, get_current_user
from app.models import Document, ExceptionRecord, Review
from app.schemas import api as S
from app.services import exception_manager as em

router = APIRouter(prefix="/api/exceptions", tags=["exceptions"])


def _get(db: Session, exc_id: str) -> ExceptionRecord:
    try:
        return em.get_exception(db, exc_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(404, "Exception not found.") from exc


def _wrap(fn):
    try:
        return fn()
    except em.ExceptionWorkflowError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


@router.get("", response_model=list[S.ExceptionOut])
def list_exceptions(status: str | None = None, severity: str | None = None, category: str | None = None, assigned: str | None = None,
                    application_id: str | None = None, limit: int = Query(200, ge=1, le=1000), offset: int = Query(0, ge=0),
                    _: CurrentUser = Depends(get_current_user), db: Session = Depends(database.get_db)):
    q = select(ExceptionRecord)
    for col, val in ((ExceptionRecord.status, status), (ExceptionRecord.severity, severity), (ExceptionRecord.category, category),
                     (ExceptionRecord.assigned_reviewer, assigned), (ExceptionRecord.application_id, application_id)):
        if val:
            q = q.where(col == val)
    q = q.order_by(ExceptionRecord.created_at.desc(), ExceptionRecord.id).limit(limit).offset(offset)
    return list(db.scalars(q))


@router.get("/{exc_id}", response_model=S.ExceptionDetail)
def detail(exc_id: str, _: CurrentUser = Depends(get_current_user), db: Session = Depends(database.get_db)):
    e = _get(db, exc_id)
    reviews = list(db.scalars(select(Review).where(Review.exception_id == e.id).order_by(Review.id)))
    ids = (e.evidence or {}).get("document_ids", [])
    docs = list(db.scalars(select(Document).where(Document.id.in_(ids)))) if ids else []
    out = S.ExceptionDetail.model_validate(e)
    out.reviews = [S.ReviewOut.model_validate(r) for r in reviews]
    out.documents = [S.DocumentOut.model_validate(d) for d in docs]
    return out


@router.patch("/{exc_id}/status", response_model=S.ExceptionOut)
def patch_status(exc_id: str, body: S.StatusPatch, user: CurrentUser = Depends(get_current_user), db: Session = Depends(database.get_db)):
    e = _get(db, exc_id)
    _wrap(lambda: em.change_status(db, e, body.status, user.username, user.role, body.comment, body.assigned_reviewer))
    db.commit()
    return e


@router.post("/{exc_id}/comments", response_model=S.ReviewOut, status_code=201)
def comment(exc_id: str, body: S.CommentIn, user: CurrentUser = Depends(get_current_user), db: Session = Depends(database.get_db)):
    e = _get(db, exc_id)
    rv = _wrap(lambda: em.add_comment(db, e, user.username, body.comment))
    db.commit()
    return rv


@router.post("/{exc_id}/assign", response_model=S.ExceptionOut)
def assign(exc_id: str, body: S.AssignIn, user: CurrentUser = Depends(get_current_user), db: Session = Depends(database.get_db)):
    e = _get(db, exc_id)
    em.assign(db, e, body.reviewer, user.username)
    db.commit()
    return e
