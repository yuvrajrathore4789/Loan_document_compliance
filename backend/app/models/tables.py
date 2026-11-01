"""ORM tables (11): the 10 requested plus ``users`` for authentication.

Generic SQLAlchemy types only (String/Integer/Float/Text/JSON/Boolean/DateTime) so the same
schema works on SQLite and PostgreSQL. All timestamps are naive UTC.
"""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (JSON, Boolean, DDL, DateTime, Float, ForeignKey, Index, Integer, String, Text,
                        UniqueConstraint, event)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, utcnow


class DocCategory(str, enum.Enum):
    PAN = "PAN"
    AADHAAR = "AADHAAR"
    BANK_STATEMENT = "BANK_STATEMENT"
    SALARY_SLIP = "SALARY_SLIP"
    ITR = "ITR"
    GST_CERTIFICATE = "GST_CERTIFICATE"
    BUSINESS_REGISTRATION = "BUSINESS_REGISTRATION"
    LOAN_APPLICATION = "LOAN_APPLICATION"
    UNKNOWN = "UNKNOWN"


class DocStatus(str, enum.Enum):
    UPLOADED = "Uploaded"
    PROCESSING = "Processing"
    PROCESSED = "Processed"
    VERIFICATION_PENDING = "Verification Pending"
    VERIFIED = "Verified"
    EXCEPTION_DETECTED = "Exception Detected"
    REJECTED = "Rejected by Reviewer"


class AppStatus(str, enum.Enum):
    DRAFT = "Draft"
    DOCUMENTS_UPLOADED = "Documents Uploaded"
    VERIFICATION_PENDING = "Verification Pending"
    VERIFIED = "Verified"
    EXCEPTION_DETECTED = "Exception Detected"


class Severity(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ExcStatus(str, enum.Enum):
    OPEN = "OPEN"
    IN_REVIEW = "IN_REVIEW"
    AWAITING_DOCUMENTS = "AWAITING_DOCUMENTS"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"
    REOPENED = "REOPENED"


class Timestamped:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class User(Base, Timestamped):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # reviewer | admin
    full_name: Mapped[str | None] = mapped_column(String(128))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Application(Base, Timestamped):
    __tablename__ = "applications"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # APP-XXXXXXXX
    applicant_name: Mapped[str] = mapped_column(String(200), nullable=False)
    application_type: Mapped[str] = mapped_column(String(20), nullable=False)  # SALARIED | SELF_EMPLOYED
    loan_amount: Mapped[float | None] = mapped_column(Float)
    declared_monthly_income: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32), default=AppStatus.DRAFT.value, nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    scenario_label: Mapped[str | None] = mapped_column(String(64))  # synthetic ground-truth tag (demo only)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    documents: Mapped[list["Document"]] = relationship(back_populates="application", cascade="all, delete-orphan")
    __table_args__ = (Index("ix_applications_status", "status"), Index("ix_applications_created", "created_at"))


class Document(Base, Timestamped):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # DOC-XXXXXXXXXX
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_path: Mapped[str | None] = mapped_column(String(500))
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str] = mapped_column(String(32), default=DocCategory.UNKNOWN.value, nullable=False)
    classification_confidence: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32), default=DocStatus.UPLOADED.value, nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer)
    text_method: Mapped[str | None] = mapped_column(String(24))  # pdf_text | ocr | mixed
    ocr_confidence: Mapped[float | None] = mapped_column(Float)  # null for digital text
    extraction_method: Mapped[str | None] = mapped_column(String(32))  # deterministic | deterministic+llm
    extracted_text: Mapped[str | None] = mapped_column(Text)  # sensitive: redacted, never logged
    warnings: Mapped[list | None] = mapped_column(JSON)
    processing_error: Mapped[str | None] = mapped_column(Text)
    duplicate_of: Mapped[str | None] = mapped_column(String(32))
    uploaded_by: Mapped[str | None] = mapped_column(String(64))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime)
    processing_seconds: Mapped[float | None] = mapped_column(Float)
    application: Mapped[Application] = relationship(back_populates="documents")
    fields: Mapped[list["ExtractedField"]] = relationship(back_populates="document", cascade="all, delete-orphan")
    __table_args__ = (Index("ix_documents_app", "application_id"), Index("ix_documents_sha", "sha256"),
                      Index("ix_documents_category", "category"))


class ExtractedField(Base, Timestamped):
    __tablename__ = "extracted_fields"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    field_name: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[str | None] = mapped_column(Text)  # null = not found (never fabricated)
    normalized_value: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    page_number: Mapped[int | None] = mapped_column(Integer)
    method: Mapped[str] = mapped_column(String(24), default="regex", nullable=False)  # regex | table | llm | manual
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)  # extracted != verified
    verified_by: Mapped[str | None] = mapped_column(String(64))
    document: Mapped[Document] = relationship(back_populates="fields")
    __table_args__ = (UniqueConstraint("document_id", "field_name", name="uq_field_per_document"),
                      Index("ix_fields_doc", "document_id"))


class VerificationRule(Base, Timestamped):
    __tablename__ = "verification_rules"
    id: Mapped[str] = mapped_column(String(16), primary_key=True)  # R001..
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(32), default="builtin", nullable=False)  # builtin|required_document|field_present
    severity: Mapped[str] = mapped_column(String(8), default=Severity.MEDIUM.value, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    params: Mapped[dict | None] = mapped_column(JSON)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_demo_rule: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    updated_by: Mapped[str | None] = mapped_column(String(64))


class VerificationResult(Base):
    __tablename__ = "verification_results"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(32), nullable=False)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), nullable=False)
    rule_id: Mapped[str] = mapped_column(ForeignKey("verification_rules.id"), nullable=False)
    rule_version: Mapped[int] = mapped_column(Integer, nullable=False)
    document_ids: Mapped[list | None] = mapped_column(JSON)
    field: Mapped[str | None] = mapped_column(String(100))
    expected: Mapped[str | None] = mapped_column(Text)
    observed: Mapped[str | None] = mapped_column(Text)
    outcome: Mapped[str] = mapped_column(String(10), nullable=False)  # PASS | FAIL | WARN | SKIPPED
    severity: Mapped[str] = mapped_column(String(8), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    __table_args__ = (Index("ix_results_app_run", "application_id", "run_id"), Index("ix_results_rule", "rule_id"))


class ExceptionRecord(Base, Timestamped):
    __tablename__ = "exceptions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # EXC-XXXXXXXX
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), nullable=False)
    rule_id: Mapped[str] = mapped_column(ForeignKey("verification_rules.id"), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    severity: Mapped[str] = mapped_column(String(8), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(24), default=ExcStatus.OPEN.value, nullable=False)
    assigned_reviewer: Mapped[str | None] = mapped_column(String(64))
    dedupe_key: Mapped[str] = mapped_column(String(300), nullable=False)
    run_id: Mapped[str | None] = mapped_column(String(32))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
    resolution_seconds: Mapped[float | None] = mapped_column(Float)
    __table_args__ = (UniqueConstraint("application_id", "dedupe_key", name="uq_exception_dedupe"),
                      Index("ix_exceptions_status", "status"), Index("ix_exceptions_severity", "severity"),
                      Index("ix_exceptions_app", "application_id"))


class Review(Base):
    __tablename__ = "reviews"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    exception_id: Mapped[str] = mapped_column(ForeignKey("exceptions.id", ondelete="CASCADE"), nullable=False)
    reviewer: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    __table_args__ = (Index("ix_reviews_exception", "exception_id"),)


class AuditLog(Base):
    """Append-only (application level + SQLite triggers). See services/audit_service.py."""
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(48), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_state: Mapped[dict | None] = mapped_column(JSON)
    new_state: Mapped[dict | None] = mapped_column(JSON)
    details: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    __table_args__ = (Index("ix_audit_resource", "resource_type", "resource_id"), Index("ix_audit_created", "created_at"),
                      Index("ix_audit_action", "action"))


# Defence in depth: SQLite triggers reject UPDATE/DELETE on audit_logs. (Application-level only;
# anyone with direct database access can drop the trigger - this is NOT tamper-proof storage.)
event.listen(AuditLog.__table__, "after_create", DDL(
    "CREATE TRIGGER IF NOT EXISTS audit_logs_no_update BEFORE UPDATE ON audit_logs "
    "BEGIN SELECT RAISE(ABORT, 'audit_logs is append-only'); END").execute_if(dialect="sqlite"))
event.listen(AuditLog.__table__, "after_create", DDL(
    "CREATE TRIGGER IF NOT EXISTS audit_logs_no_delete BEFORE DELETE ON audit_logs "
    "BEGIN SELECT RAISE(ABORT, 'audit_logs is append-only'); END").execute_if(dialect="sqlite"))


class TransactionRecord(Base):
    __tablename__ = "transaction_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), nullable=False)
    txn_date: Mapped[str] = mapped_column(String(10), nullable=False)  # ISO date
    description: Mapped[str | None] = mapped_column(String(300))
    credit: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    debit: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    balance: Mapped[float | None] = mapped_column(Float)
    is_salary_like: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    anomaly_score: Mapped[float | None] = mapped_column(Float)  # higher = more unusual (Isolation Forest)
    robust_z: Mapped[float | None] = mapped_column(Float)
    is_anomalous: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    anomaly_reasons: Mapped[list | None] = mapped_column(JSON)
    injected_label: Mapped[bool | None] = mapped_column(Boolean)  # synthetic ground truth (demo/eval only)
    __table_args__ = (Index("ix_txn_app", "application_id"), Index("ix_txn_doc", "document_id"))


class ModelRun(Base):
    __tablename__ = "model_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_type: Mapped[str] = mapped_column(String(32), nullable=False)  # anomaly | verification | llm_extraction
    model_name: Mapped[str] = mapped_column(String(64), nullable=False)
    application_id: Mapped[str | None] = mapped_column(String(32))
    params: Mapped[dict | None] = mapped_column(JSON)
    metrics: Mapped[dict | None] = mapped_column(JSON)
    n_records: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    __table_args__ = (Index("ix_model_runs_type", "run_type"),)
