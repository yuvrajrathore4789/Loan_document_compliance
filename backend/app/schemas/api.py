"""Pydantic request/response models."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    username: str


class UserOut(ORM):
    username: str
    role: str
    full_name: str | None = None


class ApplicationCreate(BaseModel):
    applicant_name: str = Field(min_length=2, max_length=200)
    application_type: Literal["SALARIED", "SELF_EMPLOYED"]
    loan_amount: float | None = Field(default=None, ge=0, le=1e10)
    declared_monthly_income: float | None = Field(default=None, ge=0, le=1e9)
    is_synthetic: bool = True

    @field_validator("applicant_name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = " ".join(v.split())
        if len(v) < 2:
            raise ValueError("applicant_name too short")
        return v


class ApplicationOut(ORM):
    id: str
    applicant_name: str
    application_type: str
    loan_amount: float | None
    declared_monthly_income: float | None
    status: str
    is_synthetic: bool
    scenario_label: str | None = None
    created_at: datetime
    last_verified_at: datetime | None = None
    documents_count: int = 0
    open_exceptions: int = 0
    high_open_exceptions: int = 0


class DocumentOut(ORM):
    id: str
    application_id: str
    original_filename: str
    content_type: str
    size_bytes: int
    sha256: str
    category: str
    classification_confidence: float | None
    status: str
    page_count: int | None
    text_method: str | None
    ocr_confidence: float | None
    extraction_method: str | None
    warnings: list[str] | None
    processing_error: str | None
    duplicate_of: str | None
    uploaded_at: datetime
    processed_at: datetime | None
    processing_seconds: float | None


class FieldOut(ORM):
    field_name: str
    value: str | None
    confidence: float | None
    page_number: int | None
    method: str
    is_verified: bool
    verified_by: str | None = None


class ExtractionOut(BaseModel):
    document: DocumentOut
    fields: list[FieldOut]
    transactions_count: int
    notice: str = "Extracted values are machine-read and UNVERIFIED unless is_verified is true."


class FieldCorrection(BaseModel):
    value: str | None = Field(default=None, max_length=500)
    reason: str = Field(min_length=3, max_length=500)


class UploadItemResult(BaseModel):
    filename: str
    accepted: bool
    document_id: str | None = None
    category: str | None = None
    status: str | None = None
    error: str | None = None


class UploadOut(BaseModel):
    application_id: str
    results: list[UploadItemResult]


class ResultOut(ORM):
    id: int
    run_id: str
    rule_id: str
    rule_version: int
    document_ids: list[str] | None
    field: str | None
    expected: str | None
    observed: str | None
    outcome: str
    severity: str
    explanation: str
    created_at: datetime


class VerificationOut(BaseModel):
    application_id: str
    summary: dict[str, Any]
    results: list[ResultOut]
    ai_summary: str | None = None
    ai_summary_notice: str | None = None


class ReviewOut(ORM):
    id: int
    reviewer: str
    action: str
    comment: str | None
    created_at: datetime


class ExceptionOut(ORM):
    id: str
    application_id: str
    rule_id: str
    category: str
    severity: str
    description: str
    status: str
    assigned_reviewer: str | None
    created_at: datetime
    resolved_at: datetime | None


class ExceptionDetail(ExceptionOut):
    evidence: dict[str, Any] | None
    reviews: list[ReviewOut] = []
    documents: list[DocumentOut] = []


class StatusPatch(BaseModel):
    status: Literal["OPEN", "IN_REVIEW", "AWAITING_DOCUMENTS", "ESCALATED", "RESOLVED", "REOPENED"]
    comment: str | None = Field(default=None, max_length=2000)
    assigned_reviewer: str | None = Field(default=None, max_length=64)


class CommentIn(BaseModel):
    comment: str = Field(min_length=1, max_length=2000)


class AssignIn(BaseModel):
    reviewer: str | None = Field(default=None, max_length=64)


class RuleOut(ORM):
    id: str
    name: str
    description: str | None
    kind: str
    severity: str
    enabled: bool
    params: dict[str, Any] | None
    version: int
    is_demo_rule: bool
    updated_by: str | None
    updated_at: datetime


class RuleCreate(BaseModel):
    id: str = Field(pattern=r"^R\d{3,4}$")
    name: str = Field(min_length=3, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    kind: Literal["required_document", "field_present"]
    severity: Literal["LOW", "MEDIUM", "HIGH"] = "MEDIUM"
    params: dict[str, Any]


class RulePatch(BaseModel):
    name: str | None = Field(default=None, min_length=3, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    severity: Literal["LOW", "MEDIUM", "HIGH"] | None = None
    enabled: bool | None = None
    params: dict[str, Any] | None = None
    reason: str = Field(min_length=3, max_length=500)


class AuditOut(ORM):
    event_id: str
    actor: str
    action: str
    resource_type: str
    resource_id: str
    previous_state: dict[str, Any] | None
    new_state: dict[str, Any] | None
    details: dict[str, Any] | None
    created_at: datetime


class TransactionOut(ORM):
    id: int
    document_id: str
    txn_date: str
    description: str | None
    credit: float
    debit: float
    balance: float | None
    is_salary_like: bool
    anomaly_score: float | None
    robust_z: float | None
    is_anomalous: bool
    anomaly_reasons: list[str] | None
