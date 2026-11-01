from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import database
from app.deps import CurrentUser, get_current_user
from app.models import (Application, Document, DocStatus, ExceptionRecord, ExcStatus, ExtractedField,
                        TransactionRecord, VerificationResult)
from app.schemas import api as S
from app.services import anomaly_detection, audit_service as audit, document_processor as dp
from app.services import verification_engine as ve
from app.services.llm_extractor import llm_summary
from app.utils.file_validation import UploadRejected

router = APIRouter(prefix="/api", tags=["applications"])
MAX_FILES_PER_REQUEST = 10


def _app_or_404(db: Session, app_id: str) -> Application:
    a = db.get(Application, app_id)
    if a is None:
        raise HTTPException(404, "Application not found.")
    return a


def _doc_or_404(db: Session, doc_id: str) -> Document:
    d = db.get(Document, doc_id)
    if d is None:
        raise HTTPException(404, "Document not found.")
    return d


def _app_out(db: Session, a: Application) -> S.ApplicationOut:
    open_q = select(func.count(ExceptionRecord.id)).where(ExceptionRecord.application_id == a.id, ExceptionRecord.status != ExcStatus.RESOLVED.value)
    out = S.ApplicationOut.model_validate(a)
    out.documents_count = db.scalar(select(func.count(Document.id)).where(Document.application_id == a.id)) or 0
    out.open_exceptions = db.scalar(open_q) or 0
    out.high_open_exceptions = db.scalar(open_q.where(ExceptionRecord.severity == "HIGH")) or 0
    return out


@router.post("/applications", response_model=S.ApplicationOut, status_code=201)
def create_application(body: S.ApplicationCreate, user: CurrentUser = Depends(get_current_user), db: Session = Depends(database.get_db)):
    a = dp.create_application(db, user.username, body.applicant_name, body.application_type, body.loan_amount,
                              body.declared_monthly_income, body.is_synthetic)
    db.commit()
    return _app_out(db, a)


@router.get("/applications", response_model=list[S.ApplicationOut])
def list_applications(status: str | None = None, q: str | None = Query(None, max_length=100), limit: int = Query(100, ge=1, le=500),
                      offset: int = Query(0, ge=0), _: CurrentUser = Depends(get_current_user), db: Session = Depends(database.get_db)):
    stmt = select(Application).order_by(Application.created_at.desc(), Application.id)
    if status:
        stmt = stmt.where(Application.status == status)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(Application.applicant_name.ilike(like) | Application.id.ilike(like))
    return [_app_out(db, a) for a in db.scalars(stmt.limit(limit).offset(offset))]


@router.get("/applications/{app_id}")
def get_application(app_id: str, _: CurrentUser = Depends(get_current_user), db: Session = Depends(database.get_db)):
    a = _app_or_404(db, app_id)
    docs = list(db.scalars(select(Document).where(Document.application_id == a.id).order_by(Document.uploaded_at)))
    return {"application": _app_out(db, a), "documents": [S.DocumentOut.model_validate(d) for d in docs]}


@router.post("/applications/{app_id}/documents", response_model=S.UploadOut)
async def upload_documents(app_id: str, files: list[UploadFile] = File(...), user: CurrentUser = Depends(get_current_user),
                           db: Session = Depends(database.get_db)):
    a = _app_or_404(db, app_id)
    if len(files) > MAX_FILES_PER_REQUEST:
        raise HTTPException(413, f"At most {MAX_FILES_PER_REQUEST} files per request.")
    from app.config import get_settings
    limit = get_settings().max_upload_bytes
    results: list[S.UploadItemResult] = []
    codes: list[int] = []
    for f in files:
        data = await f.read(limit + 1)  # bounded read: never buffer more than limit+1 bytes
        try:
            d = dp.ingest_upload(db, a, data, f.filename, user.username)
            db.commit()
            results.append(S.UploadItemResult(filename=d.original_filename, accepted=True, document_id=d.id, category=d.category, status=d.status,
                                              error=d.processing_error))
        except UploadRejected as exc:
            codes.append(exc.status_code)
            results.append(S.UploadItemResult(filename=(f.filename or "")[:100], accepted=False, error=str(exc)))
    if results and not any(r.accepted for r in results):
        raise HTTPException(codes[0], "; ".join(r.error or "rejected" for r in results))
    return S.UploadOut(application_id=a.id, results=results)


@router.get("/documents/{doc_id}", response_model=S.DocumentOut)
def get_document(doc_id: str, _: CurrentUser = Depends(get_current_user), db: Session = Depends(database.get_db)):
    return _doc_or_404(db, doc_id)


@router.get("/documents/{doc_id}/extraction", response_model=S.ExtractionOut)
def get_extraction(doc_id: str, _: CurrentUser = Depends(get_current_user), db: Session = Depends(database.get_db)):
    d = _doc_or_404(db, doc_id)
    fields = list(db.scalars(select(ExtractedField).where(ExtractedField.document_id == d.id).order_by(ExtractedField.field_name)))
    n = db.scalar(select(func.count(TransactionRecord.id)).where(TransactionRecord.document_id == d.id)) or 0
    return S.ExtractionOut(document=S.DocumentOut.model_validate(d), fields=[S.FieldOut.model_validate(f) for f in fields], transactions_count=n)


@router.put("/documents/{doc_id}/fields/{field_name}", response_model=S.FieldOut)
def correct_field(doc_id: str, field_name: str, body: S.FieldCorrection, user: CurrentUser = Depends(get_current_user),
                  db: Session = Depends(database.get_db)):
    from app.services.extractor import ALLOWED_FIELDS
    d = _doc_or_404(db, doc_id)
    if field_name not in set().union(*ALLOWED_FIELDS.values()):
        raise HTTPException(422, f"Unknown field '{field_name}'.")
    f = dp.correct_field(db, d, field_name, body.value, user.username, body.reason)
    db.commit()
    return f


@router.post("/documents/{doc_id}/reject", response_model=S.DocumentOut)
def reject_document(doc_id: str, body: S.CommentIn, user: CurrentUser = Depends(get_current_user), db: Session = Depends(database.get_db)):
    """Reviewer marks a document unusable (e.g. unreadable). Does not approve or reject the loan."""
    d = _doc_or_404(db, doc_id)
    prev = {"status": d.status}
    d.status = DocStatus.REJECTED.value
    audit.log_event(db, user.username, "DOCUMENT_REJECTED", "document", d.id, prev, {"status": d.status}, {"reason": body.comment})
    db.commit()
    return d


@router.get("/documents/{doc_id}/file")
def download_file(doc_id: str, user: CurrentUser = Depends(get_current_user), db: Session = Depends(database.get_db)):
    d = _doc_or_404(db, doc_id)
    if not d.stored_path or not Path(d.stored_path).is_file():
        raise HTTPException(404, "Stored file not available.")
    audit.log_event(db, user.username, "DOCUMENT_VIEWED", "document", d.id, None, None, {"application_id": d.application_id})
    db.commit()
    return FileResponse(d.stored_path, media_type=d.content_type, filename=d.original_filename)


@router.post("/applications/{app_id}/verify", response_model=S.VerificationOut)
def verify(app_id: str, user: CurrentUser = Depends(get_current_user), db: Session = Depends(database.get_db)):
    a = _app_or_404(db, app_id)
    outcome = ve.run_verification(db, a, user.username)
    db.commit()
    return _verification_payload(db, a, outcome.run_id)


def _verification_payload(db: Session, a: Application, run_id: str | None, with_ai: bool = True) -> S.VerificationOut:
    summary = ve.verification_summary(db, a)
    rows = list(db.scalars(select(VerificationResult).where(VerificationResult.run_id == run_id).order_by(VerificationResult.id))) if run_id else []
    ai = None
    if with_ai and rows and summary.get("top_issues"):
        ai = llm_summary({"headline": summary["headline"], "counts": summary["counts"], "top_issues": summary["top_issues"]})
    return S.VerificationOut(application_id=a.id, summary=summary, results=[S.ResultOut.model_validate(r) for r in rows], ai_summary=ai,
                             ai_summary_notice="Narrative generated by an LLM from the deterministic results above; it does not determine compliance." if ai else None)


@router.get("/applications/{app_id}/verification", response_model=S.VerificationOut)
def get_verification(app_id: str, _: CurrentUser = Depends(get_current_user), db: Session = Depends(database.get_db)):
    a = _app_or_404(db, app_id)
    run = db.scalar(select(VerificationResult.run_id).where(VerificationResult.application_id == a.id).order_by(VerificationResult.id.desc()).limit(1))
    return _verification_payload(db, a, run, with_ai=False)


@router.get("/applications/{app_id}/exceptions", response_model=list[S.ExceptionOut])
def app_exceptions(app_id: str, _: CurrentUser = Depends(get_current_user), db: Session = Depends(database.get_db)):
    a = _app_or_404(db, app_id)
    return list(db.scalars(select(ExceptionRecord).where(ExceptionRecord.application_id == a.id).order_by(ExceptionRecord.created_at)))


@router.get("/applications/{app_id}/transactions")
def app_transactions(app_id: str, only_anomalous: bool = False, limit: int = Query(500, ge=1, le=2000), _: CurrentUser = Depends(get_current_user),
                     db: Session = Depends(database.get_db)):
    a = _app_or_404(db, app_id)
    q = select(TransactionRecord).where(TransactionRecord.application_id == a.id).order_by(TransactionRecord.txn_date, TransactionRecord.id)
    rows = list(db.scalars(q))
    flagged = [r for r in rows if r.is_anomalous]
    out_rows = flagged if only_anomalous else rows
    import pandas as pd
    comparison = {}
    if rows:
        df = pd.DataFrame([{"date": r.txn_date, "description": r.description, "credit": r.credit, "debit": r.debit} for r in rows])
        sc = anomaly_detection.score_transactions(df, a.declared_monthly_income)
        comparison = {"isolation_forest": int(sc["if_flag"].sum()), "robust_z": int(sc["z_flag"].sum()),
                      "simple_rule": int(sc["rule_flag"].sum()), "combined_flag": int(sc["is_anomalous"].sum())}
    return {"application_id": a.id, "total": len(rows), "flagged": len(flagged), "detector_comparison": comparison,
            "account_findings": anomaly_detection.account_level_findings(
                pd.DataFrame([{"date": r.txn_date, "description": r.description, "credit": r.credit, "debit": r.debit, "is_salary_like": r.is_salary_like} for r in rows]),
                a.declared_monthly_income) if rows else [],
            "transactions": [S.TransactionOut.model_validate(r) for r in out_rows[:limit]],
            "notice": "Statistical anomalies are prompts for human review, not evidence of fraud."}
