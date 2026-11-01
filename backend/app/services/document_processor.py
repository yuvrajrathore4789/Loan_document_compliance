"""Upload -> validate -> classify -> OCR/extract -> normalise -> persist pipeline (synchronous).

Unreadable/corrupt documents become *processing exceptions* (status "Exception Detected" with a
neutral error message), never fraud accusations. Unsupported formats are rejected outright.
"""
from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import utcnow
from app.models import (Application, AppStatus, DocCategory, Document, DocStatus, ExtractedField, ModelRun,
                        TransactionRecord)
from app.services import audit_service as audit
from app.services.classifier import classify
from app.services.extractor import ExtractedDocument, extract_fields
from app.services.llm_extractor import detect_prompt_injection, fill_missing_with_llm
from app.services.ocr_service import DocumentUnreadable, extract_text
from app.utils.file_validation import UploadRejected, validate_upload
from app.utils.normalization import redact_full_aadhaar

logger = logging.getLogger(__name__)
SALARY_HINT = ("salary", "sal cr", "payroll", "sal-", "wages")


def new_id(prefix: str, n: int = 8) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:n].upper()}"


def create_application(db: Session, actor: str, applicant_name: str, application_type: str,
                       loan_amount: float | None = None, declared_monthly_income: float | None = None,
                       is_synthetic: bool = True, scenario_label: str | None = None) -> Application:
    app = Application(id=new_id("APP"), applicant_name=applicant_name.strip(), application_type=application_type,
                      loan_amount=loan_amount, declared_monthly_income=declared_monthly_income,
                      status=AppStatus.DRAFT.value, is_synthetic=is_synthetic, scenario_label=scenario_label)
    db.add(app)
    db.flush()
    audit.log_event(db, actor, "APPLICATION_CREATED", "application", app.id, None,
                    {"application_type": application_type, "status": app.status}, {"synthetic": is_synthetic})
    return app


def refresh_application_status(db: Session, app: Application) -> str:
    docs = list(db.scalars(select(Document).where(Document.application_id == app.id)))
    if not docs:
        new = AppStatus.DRAFT.value
    elif any(d.status in (DocStatus.UPLOADED.value, DocStatus.PROCESSING.value) for d in docs):
        new = AppStatus.DOCUMENTS_UPLOADED.value
    elif app.last_verified_at is None or any(d.status in (DocStatus.PROCESSED.value, DocStatus.VERIFICATION_PENDING.value) for d in docs):
        new = AppStatus.VERIFICATION_PENDING.value
    else:
        new = app.status if app.status in (AppStatus.VERIFIED.value, AppStatus.EXCEPTION_DETECTED.value) else AppStatus.VERIFICATION_PENDING.value
    app.status = new
    return new


def _store_file(app_id: str, doc_id: str, ext: str, data: bytes) -> Path:
    folder = get_settings().upload_dir / app_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{doc_id}{ext}"  # server-generated name; the client filename is never used as a path
    path.write_bytes(data)
    return path


def ingest_upload(db: Session, app: Application, data: bytes, filename: str | None, actor: str,
                  process: bool = True) -> Document:
    """Validate + store + (optionally) process one uploaded file. Raises UploadRejected for bad files."""
    s = get_settings()
    try:
        v = validate_upload(data, filename, s.max_upload_bytes)
    except UploadRejected as exc:
        audit.log_event(db, actor, "UPLOAD_REJECTED", "application", app.id, None, None,
                        {"reason": str(exc), "status_code": exc.status_code})
        db.commit()
        raise
    doc_id = new_id("DOC", 10)
    original = db.scalar(select(Document).where(Document.application_id == app.id, Document.sha256 == v.sha256,
                                                 Document.duplicate_of.is_(None)))
    other_app = db.scalar(select(Document).where(Document.sha256 == v.sha256, Document.application_id != app.id))
    doc = Document(id=doc_id, application_id=app.id, original_filename=v.safe_name, content_type=v.content_type,
                   size_bytes=v.size, sha256=v.sha256, uploaded_by=actor, status=DocStatus.UPLOADED.value, warnings=[])
    if v.extension_mismatch:
        doc.warnings.append("File extension does not match its actual content type.")
    if other_app is not None:
        doc.warnings.append(f"Identical file (same SHA-256) was also submitted under application {other_app.application_id}.")
    if original is not None:  # exact duplicate within the application: keep a record, skip re-processing
        doc.duplicate_of = original.id
        doc.category = original.category
        doc.status = DocStatus.EXCEPTION_DETECTED.value
        doc.processing_error = None
        doc.warnings.append(f"Exact duplicate of {original.id}.")
        db.add(doc)
        db.flush()
        audit.log_event(db, actor, "DOCUMENT_UPLOADED", "document", doc.id, None,
                        {"status": doc.status, "duplicate_of": original.id}, {"application_id": app.id})
        refresh_application_status(db, app)
        return doc
    doc.stored_path = str(_store_file(app.id, doc_id, v.extension, data))
    db.add(doc)
    db.flush()
    audit.log_event(db, actor, "DOCUMENT_UPLOADED", "document", doc.id, None, {"status": doc.status},
                    {"application_id": app.id, "size_bytes": v.size, "sha256": v.sha256})
    if process:
        process_document(db, doc, actor)
    refresh_application_status(db, app)
    return doc


def _persist_fields(db: Session, doc: Document, extracted: ExtractedDocument, method: str) -> None:
    for old in list(doc.fields):
        db.delete(old)
    db.flush()
    for fv in extracted.fields.values():
        db.add(ExtractedField(document_id=doc.id, field_name=fv.name, value=fv.value, normalized_value=fv.normalized,
                              confidence=fv.confidence, page_number=fv.page, method=fv.method))
    db.query(TransactionRecord).filter(TransactionRecord.document_id == doc.id).delete()
    for t in extracted.transactions:
        desc = (t.description or "")[:300]
        db.add(TransactionRecord(document_id=doc.id, application_id=doc.application_id, txn_date=t.txn_date.isoformat(),
                                 description=desc, credit=t.credit, debit=t.debit, balance=t.balance,
                                 is_salary_like=t.credit > 0 and any(h in desc.lower() for h in SALARY_HINT)))


def process_document(db: Session, doc: Document, actor: str = "system") -> Document:
    """OCR/extract/classify a stored document and persist results. Never raises for bad documents."""
    t0 = time.perf_counter()
    prev = {"status": doc.status}
    doc.status = DocStatus.PROCESSING.value
    db.flush()
    try:
        result = extract_text(doc.stored_path, doc.content_type)
    except DocumentUnreadable as exc:
        doc.status = DocStatus.EXCEPTION_DETECTED.value
        doc.processing_error = str(exc)
        doc.processing_seconds = round(time.perf_counter() - t0, 3)
        doc.processed_at = utcnow()
        audit.log_event(db, actor, "DOCUMENT_PROCESSING_FAILED", "document", doc.id, prev,
                        {"status": doc.status}, {"error": str(exc)})
        return doc

    text, n_redacted = redact_full_aadhaar(result.text)
    for p in result.pages:  # keep per-page text redacted too
        p.text, _ = redact_full_aadhaar(p.text)
        p.rows = [redact_full_aadhaar(r)[0] for r in p.rows]
    cls = classify(text, doc.original_filename)
    doc.category = cls.category.value
    doc.classification_confidence = cls.confidence
    doc.page_count = result.page_count
    doc.text_method = result.method
    doc.ocr_confidence = result.ocr_confidence
    doc.warnings = list(doc.warnings or [])
    if n_redacted:
        doc.warnings.append(f"{n_redacted} full Aadhaar-like number(s) were masked before storage.")
    inj = detect_prompt_injection(text)
    if inj:
        doc.warnings.append("Document text contains instruction-like content (possible prompt injection); "
                            "it was treated as data and the document needs manual verification.")
    extracted = extract_fields(result, cls.category)
    method = "deterministic"
    if cls.category != DocCategory.UNKNOWN and not inj:  # never send suspicious text to the LLM
        extracted, method = fill_missing_with_llm(extracted, text)
        if method != "deterministic":
            db.add(ModelRun(run_type="llm_extraction", model_name=get_settings().llm_model, application_id=doc.application_id,
                            params={"document_id": doc.id}, n_records=sum(1 for f in extracted.fields.values() if f.method == "llm"),
                            finished_at=utcnow()))
    doc.extraction_method = method
    doc.warnings.extend(extracted.warnings)
    doc.extracted_text = text
    _persist_fields(db, doc, extracted, method)
    doc.status = DocStatus.VERIFICATION_PENDING.value
    doc.processing_error = None
    doc.processing_seconds = round(time.perf_counter() - t0, 3)
    doc.processed_at = utcnow()
    audit.log_event(db, actor, "DOCUMENT_PROCESSED", "document", doc.id, prev, {"status": doc.status},
                    {"category": doc.category, "classification_confidence": cls.confidence,
                     "text_method": doc.text_method, "ocr_confidence": doc.ocr_confidence,
                     "extraction_method": method, "fields_found": sum(1 for f in extracted.fields.values() if f.value is not None),
                     "seconds": doc.processing_seconds})
    return doc


def correct_field(db: Session, doc: Document, field_name: str, new_value: str | None, actor: str, reason: str) -> ExtractedField:
    """Reviewer correction of an extracted value (audited). Marks the value as human-verified."""
    from app.services.extractor import _normalize
    f = db.scalar(select(ExtractedField).where(ExtractedField.document_id == doc.id, ExtractedField.field_name == field_name))
    if f is None:
        f = ExtractedField(document_id=doc.id, field_name=field_name)
        db.add(f)
    prev = {"value": f.value, "confidence": f.confidence, "method": f.method, "is_verified": f.is_verified}
    f.value, f.normalized_value = new_value, (_normalize(field_name, new_value) if new_value else None)
    f.method, f.confidence, f.is_verified, f.verified_by = "manual", 1.0, True, actor
    db.flush()
    audit.log_event(db, actor, "FIELD_CORRECTED", "document", doc.id,
                    {"field": field_name, **prev}, {"field": field_name, "value": new_value, "is_verified": True},
                    {"reason": reason})
    doc.status = DocStatus.VERIFICATION_PENDING.value
    return f
