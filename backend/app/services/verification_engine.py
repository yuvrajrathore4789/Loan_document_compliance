"""Configurable, deterministic compliance/verification engine.

* Every rule is a small pure function ``(ctx, rule) -> list[RuleResult]`` (independently testable).
* Rule metadata (severity, enabled flag, thresholds, version) lives in the ``verification_rules`` table.
* Every enabled rule records at least one result per run - including PASS - with the rule version.
* LLM output never reaches this module's decisions: rules read stored fields; an LLM can at most
  have helped fill a missing field earlier (flagged with method "llm" and lower confidence).

All rules here are DEMONSTRATION rules, not legal/RBI/regulatory requirements.
"""
from __future__ import annotations

import re
import statistics
import uuid
from dataclasses import dataclass, field as dfield
from datetime import date, datetime, timedelta
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import DEMO_RULES_NOTICE
from app.database import utcnow
from app.models import (Application, AppStatus, DocCategory, Document, DocStatus, ExtractedField, ModelRun,
                        Severity, TransactionRecord, VerificationResult, VerificationRule)
from app.services import audit_service as audit
from app.utils import normalization as nz

PASS, FAIL, WARN, SKIPPED = "PASS", "FAIL", "WARN", "SKIPPED"
_SEV_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
C = DocCategory

# --------------------------------------------------------------------------- default rules
DEFAULT_RULES: list[dict] = [
    dict(id="R001", name="PAN information missing", severity="HIGH",
         description="A PAN document must be present and its PAN number readable.", params={}),
    dict(id="R002", name="Applicant name mismatch", severity="HIGH",
         description="Applicant name on each document is compared (normalised, order/initial-insensitive, fuzzy) with the application record.",
         params={"match_threshold": 0.92, "review_threshold": 0.80}),
    dict(id="R003", name="Required bank statement missing", severity="MEDIUM",
         description="At least one bank statement must be uploaded.", params={}),
    dict(id="R004", name="Salary information inconsistent", severity="HIGH",
         description="Net salary on the salary slip is compared with salary-like credits in the bank statement.",
         params={"tolerance_pct": 10.0}),
    dict(id="R005", name="Duplicate document detected", severity="MEDIUM",
         description="Exact duplicate uploads (same SHA-256) within the application, or the same file under another application.", params={}),
    dict(id="R006", name="Statement period incomplete", severity="MEDIUM",
         description="Bank statement must cover a minimum number of months, be recent, and have activity in each month.",
         params={"min_months": 6, "max_age_days": 150}),
    dict(id="R007", name="Required ITR missing", severity="MEDIUM",
         description="ITR is required for the configured application types.", params={"required_for": ["SELF_EMPLOYED"]}),
    dict(id="R008", name="OCR confidence below threshold", severity="LOW",
         description="OCR-read documents with mean word confidence below the threshold need a human look.", params={"threshold": 0.70}),
    dict(id="R009", name="Bank account name mismatch", severity="HIGH",
         description="Bank statement account holder is compared with the application record (and the application form's account holder).",
         params={"match_threshold": 0.92, "review_threshold": 0.80}),
    dict(id="R010", name="Invalid document format", severity="MEDIUM",
         description="Corrupted, encrypted, empty or unreadable files, or extension/content mismatch. A processing issue, not an accusation.", params={}),
    dict(id="R011", name="Address inconsistency", severity="MEDIUM",
         description="Residential address on Aadhaar vs application form (abbreviation/format tolerant; pincode disagreement is material).",
         params={"match_threshold": 0.80, "review_threshold": 0.60}),
    dict(id="R012", name="Declared income inconsistent with ITR", severity="MEDIUM",
         description="Declared annual income (monthly x 12) is compared with the income declared in the ITR.",
         params={"tolerance_pct": 25.0}),
    dict(id="R013", name="Bank account used in another application", severity="HIGH",
         description="Same bank + masked account identifier appears in another application. Masked digits can collide by chance: manual check only.", params={}),
    dict(id="R014", name="Anomalous transactions", severity="MEDIUM",
         description="Statistical anomaly detection flagged transactions. An anomaly is not proof of fraud.", params={}),
    dict(id="R015", name="Other required documents missing", severity="MEDIUM",
         description="Other mandatory documents per application type.",
         params={"SALARIED": ["AADHAAR", "SALARY_SLIP", "LOAN_APPLICATION"],
                 "SELF_EMPLOYED": ["AADHAAR", "GST_CERTIFICATE", "BUSINESS_REGISTRATION", "LOAN_APPLICATION"]}),
    dict(id="R016", name="Manual verification required", severity="MEDIUM",
         description="Document type uncertain, or text contains instruction-like content (possible prompt injection).",
         params={"min_classification_confidence": 0.5}),
    dict(id="R017", name="Identifier format invalid", severity="MEDIUM",
         description="PAN / GSTIN format (and GSTIN checksum) validation.", params={}),
    dict(id="R018", name="Declared income vs observed credits", severity="LOW",
         description="Median monthly bank credits compared with declared monthly income.",
         params={"min_ratio": 0.5, "max_ratio": 2.0}),
    dict(id="R019", name="PAN number inconsistent across documents", severity="HIGH",
         description="PAN number on the PAN card, application form and ITR must match exactly.", params={}),
]
RULE_CATEGORY = {
    "R001": "Missing Document", "R002": "Identity Mismatch", "R003": "Missing Document", "R004": "Financial Mismatch",
    "R005": "Duplicate Document", "R006": "Incomplete Statement", "R007": "Missing Document", "R008": "Low OCR Confidence",
    "R009": "Identity Mismatch", "R010": "Invalid Document", "R011": "Identity Mismatch", "R012": "Financial Mismatch",
    "R013": "Manual Verification Required", "R014": "Anomalous Transaction", "R015": "Missing Document",
    "R016": "Manual Verification Required", "R017": "Invalid Document", "R018": "Financial Mismatch",
    "R019": "Identity Mismatch",
}
EXCEPTION_CATEGORIES = sorted(set(RULE_CATEGORY.values()))


def exception_category(rule_id: str, kind: str = "builtin") -> str:
    if rule_id in RULE_CATEGORY:
        return RULE_CATEGORY[rule_id]
    return "Missing Document" if kind == "required_document" else "Manual Verification Required"


def seed_default_rules(db: Session, actor: str = "system") -> int:
    """Insert missing default rules (never overwrites admin changes)."""
    existing = set(db.scalars(select(VerificationRule.id)))
    n = 0
    for r in DEFAULT_RULES:
        if r["id"] in existing:
            continue
        rule = VerificationRule(id=r["id"], name=r["name"], description=r["description"], kind="builtin",
                                severity=r["severity"], enabled=True, params=r["params"], version=1,
                                is_demo_rule=True, updated_by=actor)
        db.add(rule)
        db.flush()
        audit.log_event(db, actor, "RULE_CREATED", "rule", rule.id, None, rule_state(rule), {"seeded": True})
        n += 1
    return n


def rule_state(rule: VerificationRule) -> dict:
    return {"id": rule.id, "name": rule.name, "severity": rule.severity, "enabled": rule.enabled,
            "params": rule.params, "version": rule.version, "kind": rule.kind}


# --------------------------------------------------------------------------- data classes
@dataclass
class RuleResult:
    rule_id: str
    outcome: str
    severity: str
    explanation: str
    document_ids: list[str] = dfield(default_factory=list)
    field: str | None = None
    expected: str | None = None
    observed: str | None = None
    evidence: dict = dfield(default_factory=dict)


@dataclass
class FieldRef:
    document: Document | None  # None => application record
    category: str
    name: str
    value: str | None
    normalized: str | None
    confidence: float | None
    page: int | None
    method: str = "regex"

    @property
    def doc_id(self) -> str | None:
        return self.document.id if self.document else None

    def as_evidence(self) -> dict:
        return {"document_id": self.doc_id, "source": self.category, "field": self.name, "value": self.value,
                "confidence": self.confidence, "page": self.page, "method": self.method}


@dataclass
class VerificationContext:
    application: Application
    all_documents: list[Document]
    fields: dict[str, dict[str, ExtractedField]]
    transactions: list[TransactionRecord] = dfield(default_factory=list)
    reference_date: date = dfield(default_factory=date.today)
    other_accounts: dict[tuple[str, str], list[str]] = dfield(default_factory=dict)  # (bank, acct) -> other app ids
    anomaly: object | None = None

    @property
    def documents(self) -> list[Document]:
        """Usable documents: processed OK, not duplicates, not rejected by a reviewer."""
        return [d for d in self.all_documents if d.duplicate_of is None and not d.processing_error
                and d.status != DocStatus.REJECTED.value and d.category != DocCategory.UNKNOWN.value]

    def docs(self, category: DocCategory | str) -> list[Document]:
        cat = category.value if isinstance(category, DocCategory) else category
        return [d for d in self.documents if d.category == cat]

    def refs(self, category: DocCategory | str, name: str) -> list[FieldRef]:
        out = []
        for d in self.docs(category):
            f = self.fields.get(d.id, {}).get(name)
            out.append(FieldRef(d, d.category, name, f.value if f else None, f.normalized_value if f else None,
                                f.confidence if f else None, f.page_number if f else None, f.method if f else "regex"))
        return out

    def record_name(self) -> FieldRef:
        n = self.application.applicant_name
        return FieldRef(None, "APPLICATION_RECORD", "applicant_name", n, nz.normalize_name(n), 1.0, None, "record")


def _sev(rule: VerificationRule | RuleConfigLike, outcome: str) -> str:
    sev = rule.severity
    if outcome == WARN and _SEV_ORDER[sev] > _SEV_ORDER["MEDIUM"]:
        return "MEDIUM"
    return sev


class RuleConfigLike:  # typing helper only
    severity: str
    params: dict | None


def mk(rule: VerificationRule, outcome: str, explanation: str, docs: list[str] | None = None, field: str | None = None,
       expected=None, observed=None, evidence: dict | None = None) -> RuleResult:
    return RuleResult(rule.id, outcome, _sev(rule, outcome), explanation, [d for d in (docs or []) if d], field,
                      None if expected is None else str(expected), None if observed is None else str(observed), evidence or {})


def _p(rule: VerificationRule, key: str, default):
    return (rule.params or {}).get(key, default)


# --------------------------------------------------------------------------- rule handlers
def r001_pan_missing(ctx: VerificationContext, rule: VerificationRule) -> list[RuleResult]:
    docs = ctx.docs(C.PAN)
    if not docs:
        return [mk(rule, FAIL, "No PAN document was uploaded (or it was rejected/unreadable).", field="pan_document",
                   expected="PAN document present", observed="missing")]
    refs = ctx.refs(C.PAN, "pan_number")
    if not any(r.value for r in refs):
        return [mk(rule, FAIL, "A PAN document is present but no PAN number could be extracted.", [docs[0].id],
                   "pan_number", "PAN number present", "not found")]
    return [mk(rule, PASS, "PAN document present and PAN number extracted.", [docs[0].id], "pan_number")]


def _compare_names(ctx, rule, sources: list[tuple[FieldRef, str]], label: str) -> list[RuleResult]:
    ref = ctx.record_name()
    match_t, review_t = _p(rule, "match_threshold", 0.92), _p(rule, "review_threshold", 0.80)
    out: list[RuleResult] = []
    for src, descr in sources:
        if not src.value:
            continue
        score = nz.name_similarity(ref.value, src.value)
        ev = {"similarity": score, "thresholds": {"match": match_t, "review": review_t},
              "compared": [ref.as_evidence(), src.as_evidence()]}
        if score >= match_t:
            out.append(mk(rule, PASS, f"{descr} matches the application record (similarity {score:.2f}).", [src.doc_id],
                          label, ref.value, src.value, ev))
        elif score >= review_t:
            out.append(mk(rule, WARN, f"{descr} is similar but not identical to the application record (similarity {score:.2f}): "
                          "possible spelling difference - please review manually.", [src.doc_id], label, ref.value, src.value, ev))
        else:
            out.append(mk(rule, FAIL, f"{descr} does not match the application record (similarity {score:.2f}).",
                          [src.doc_id], label, ref.value, src.value, ev))
    return out


def r002_name_mismatch(ctx, rule):
    sources = []
    for cat, fname, descr in [(C.PAN, "name", "Name on PAN"), (C.AADHAAR, "name", "Name on Aadhaar"),
                              (C.SALARY_SLIP, "employee_name", "Employee name on salary slip"),
                              (C.LOAN_APPLICATION, "applicant_name", "Applicant name on application form"),
                              (C.ITR, "taxpayer_name", "Taxpayer name on ITR")]:
        sources += [(r, descr) for r in ctx.refs(cat, fname)]
    results = _compare_names(ctx, rule, sources, "applicant_name")
    if not results:
        return [mk(rule, SKIPPED, "No identity documents with a readable name were available to compare.")]
    return results


def r003_bank_missing(ctx, rule):
    docs = ctx.docs(C.BANK_STATEMENT)
    if docs:
        return [mk(rule, PASS, f"{len(docs)} bank statement(s) present.", [d.id for d in docs])]
    return [mk(rule, FAIL, "No usable bank statement was uploaded.", field="bank_statement", expected="at least 1", observed="0")]


def _salary_credit(ctx: VerificationContext) -> tuple[float | None, int]:
    sal = [t.credit for t in ctx.transactions if t.is_salary_like and t.credit > 0]
    return (statistics.median(sal), len(sal)) if sal else (None, 0)


def r004_salary(ctx, rule):
    slips = ctx.refs(C.SALARY_SLIP, "net_salary")
    if not slips or not ctx.docs(C.BANK_STATEMENT):
        return [mk(rule, SKIPPED, "Needs both a salary slip and a bank statement to compare.")]
    tol = _p(rule, "tolerance_pct", 10.0) / 100
    out = []
    obs, n = _salary_credit(ctx)
    for s in slips:
        net = nz.parse_amount(s.value)
        if net is None:
            out.append(mk(rule, WARN, "Net salary on the salary slip could not be read.", [s.doc_id], "net_salary"))
            continue
        if obs is None:
            out.append(mk(rule, FAIL, "No salary-like credit was found in the bank statement to match the salary slip.",
                          [s.doc_id], "net_salary", f"{net:.2f}", "no salary credits", {"slip": s.as_evidence()}))
            continue
        diff = abs(obs - net) / net if net else 1.0
        ev = {"slip": s.as_evidence(), "median_salary_credit": obs, "n_salary_credits": n, "difference_pct": round(diff * 100, 2),
              "tolerance_pct": tol * 100}
        if diff <= tol:
            out.append(mk(rule, PASS, f"Net salary {net:,.2f} is within {tol * 100:.0f}% of bank salary credits (median {obs:,.2f}).",
                          [s.doc_id], "net_salary", f"{net:.2f}", f"{obs:.2f}", ev))
        else:
            out.append(mk(rule, FAIL, f"Net salary {net:,.2f} differs from the median salary credit {obs:,.2f} by {diff * 100:.1f}% "
                          f"(tolerance {tol * 100:.0f}%).", [s.doc_id], "net_salary", f"{net:.2f}", f"{obs:.2f}", ev))
    return out


def r005_duplicates(ctx, rule):
    out = []
    for d in ctx.all_documents:
        if d.duplicate_of:
            out.append(mk(rule, FAIL, f"'{d.original_filename}' is an exact duplicate (same SHA-256) of {d.duplicate_of}.",
                          [d.id, d.duplicate_of], "sha256", "unique file", d.sha256[:16] + "...", {"sha256": d.sha256}))
        for w in d.warnings or []:
            if "also submitted under application" in w:
                out.append(mk(rule, WARN, f"'{d.original_filename}': {w}", [d.id], "sha256", evidence={"sha256": d.sha256}))
    return out or [mk(rule, PASS, "No duplicate documents detected.")]


def _months_between(a: date, b: date) -> float:
    return (b - a).days / 30.4375


def r006_statement_period(ctx, rule):
    docs = ctx.docs(C.BANK_STATEMENT)
    if not docs:
        return [mk(rule, SKIPPED, "No bank statement to check.")]
    min_m, max_age = _p(rule, "min_months", 6), _p(rule, "max_age_days", 150)
    out = []
    for d in docs:
        f = ctx.fields.get(d.id, {})
        start = nz.parse_date(f["period_start"].value) if f.get("period_start") and f["period_start"].value else None
        end = nz.parse_date(f["period_end"].value) if f.get("period_end") and f["period_end"].value else None
        if not start or not end or end < start:
            out.append(mk(rule, FAIL, "The statement period could not be determined from the document.", [d.id], "statement_period",
                          f">= {min_m} months", "unreadable"))
            continue
        months = _months_between(start, end)
        ev = {"period_start": start.isoformat(), "period_end": end.isoformat(), "months": round(months, 1)}
        problems, warns = [], []
        if months < min_m - 0.25:
            problems.append(f"covers only {months:.1f} months (minimum {min_m})")
        if (ctx.reference_date - end).days > max_age:
            warns.append(f"ends {(ctx.reference_date - end).days} days before the application (max {max_age})")
        txn_months = {t.txn_date[:7] for t in ctx.transactions if t.document_id == d.id}
        cur, empty = date(start.year, start.month, 1), []
        while cur <= end and txn_months:
            if cur.strftime("%Y-%m") not in txn_months:
                empty.append(cur.strftime("%Y-%m"))
            cur = (cur + timedelta(days=32)).replace(day=1)
        if empty:
            warns.append(f"no transactions in {', '.join(empty)}")
        ev["empty_months"] = empty
        if problems:
            out.append(mk(rule, FAIL, "Statement period incomplete: " + "; ".join(problems + warns) + ".", [d.id], "statement_period",
                          f">= {min_m} months", f"{months:.1f} months", ev))
        elif warns:
            out.append(mk(rule, WARN, "Statement period needs attention: " + "; ".join(warns) + ".", [d.id], "statement_period",
                          f">= {min_m} months", f"{months:.1f} months", ev))
        else:
            out.append(mk(rule, PASS, f"Statement covers {months:.1f} months ({start} to {end}).", [d.id], "statement_period",
                          f">= {min_m} months", f"{months:.1f} months", ev))
    return out


def r007_itr_missing(ctx, rule):
    if ctx.application.application_type not in _p(rule, "required_for", ["SELF_EMPLOYED"]):
        return [mk(rule, SKIPPED, f"ITR is not required for {ctx.application.application_type} applications under this rule.")]
    docs = ctx.docs(C.ITR)
    if docs:
        return [mk(rule, PASS, "ITR document present.", [docs[0].id])]
    return [mk(rule, FAIL, "A required ITR document is missing.", field="itr", expected="ITR present", observed="missing")]


def r008_ocr_conf(ctx, rule):
    thr = _p(rule, "threshold", 0.70)
    low = [d for d in ctx.all_documents if d.ocr_confidence is not None and d.ocr_confidence < thr and not d.duplicate_of]
    if not low:
        return [mk(rule, PASS, f"All OCR-read documents have confidence >= {thr:.2f} (or no OCR was needed).")]
    return [mk(rule, FAIL, f"OCR confidence {d.ocr_confidence:.2f} is below {thr:.2f} for '{d.original_filename}'; extracted values may be unreliable.",
               [d.id], "ocr_confidence", f">= {thr:.2f}", f"{d.ocr_confidence:.2f}", {"category": d.category}) for d in low]


def r009_bank_name(ctx, rule):
    docs = ctx.docs(C.BANK_STATEMENT)
    if not docs:
        return [mk(rule, SKIPPED, "No bank statement to compare.")]
    sources = [(r, "Account holder on bank statement") for r in ctx.refs(C.BANK_STATEMENT, "account_holder")]
    sources += [(r, "Account holder named on application form") for r in ctx.refs(C.LOAN_APPLICATION, "account_holder")]
    res = _compare_names(ctx, rule, sources, "account_holder")
    return res or [mk(rule, WARN, "Account holder name could not be read from the bank statement.", [docs[0].id], "account_holder")]


def r010_invalid_format(ctx, rule):
    bad = [d for d in ctx.all_documents if d.processing_error]
    mism = [d for d in ctx.all_documents if any("extension does not match" in w for w in (d.warnings or []))]
    out = [mk(rule, FAIL, f"'{d.original_filename}' could not be processed: {d.processing_error} "
              "(a processing issue - please request a new copy; this is not a fraud finding).", [d.id], "file", "readable PDF/PNG/JPEG",
              "unreadable") for d in bad]
    out += [mk(rule, WARN, f"'{d.original_filename}': file extension does not match its actual content type.", [d.id], "file_type") for d in mism]
    return out or [mk(rule, PASS, "All uploaded files were readable and well-formed.")]


def r011_address(ctx, rule):
    a, b = ctx.refs(C.AADHAAR, "address"), ctx.refs(C.LOAN_APPLICATION, "address")
    if not a or not b:
        return [mk(rule, SKIPPED, "Needs both an Aadhaar and an application form to compare addresses.")]
    ra, rb = next((r for r in a if r.value), None), next((r for r in b if r.value), None)
    if ra is None or rb is None:
        who = "Aadhaar" if ra is None else "application form"
        return [mk(rule, WARN, f"Address could not be read from the {who}.", [a[0].doc_id, b[0].doc_id], "address")]
    match_t, review_t = _p(rule, "match_threshold", 0.80), _p(rule, "review_threshold", 0.60)
    score = nz.address_similarity(ra.value, rb.value)
    ev = {"similarity": score, "compared": [ra.as_evidence(), rb.as_evidence()],
          "pincodes": [nz.extract_pincode(ra.value), nz.extract_pincode(rb.value)]}
    docs = [ra.doc_id, rb.doc_id]
    if score >= match_t:
        return [mk(rule, PASS, f"Addresses are consistent (similarity {score:.2f}; formatting differences ignored).", docs, "address", rb.value, ra.value, ev)]
    if score >= review_t:
        return [mk(rule, WARN, f"Addresses partly differ (similarity {score:.2f}); review manually.", docs, "address", rb.value, ra.value, ev)]
    return [mk(rule, FAIL, f"Addresses are materially different (similarity {score:.2f}).", docs, "address", rb.value, ra.value, ev)]


def r012_income_itr(ctx, rule):
    itr = [r for r in ctx.refs(C.ITR, "declared_income") if r.value]
    if not itr:
        return [mk(rule, SKIPPED, "No ITR income available to compare.")]
    declared = ctx.application.declared_monthly_income
    form = [nz.parse_amount(r.value) for r in ctx.refs(C.LOAN_APPLICATION, "declared_monthly_income") if r.value]
    declared = declared if declared else (form[0] if form and form[0] else None)
    if not declared:
        return [mk(rule, SKIPPED, "No declared income on the application to compare with the ITR.")]
    tol = _p(rule, "tolerance_pct", 25.0) / 100
    itr_income = nz.parse_amount(itr[0].value)
    if itr_income is None:
        return [mk(rule, WARN, "ITR income could not be read.", [itr[0].doc_id], "declared_income")]
    annual = declared * 12
    diff = abs(itr_income - annual) / annual
    ev = {"declared_annual": annual, "itr_income": itr_income, "difference_pct": round(diff * 100, 2), "tolerance_pct": tol * 100,
          "itr": itr[0].as_evidence()}
    if diff <= tol:
        return [mk(rule, PASS, f"Declared annual income {annual:,.0f} is within {tol * 100:.0f}% of ITR income {itr_income:,.0f}.",
                   [itr[0].doc_id], "declared_income", f"{annual:.0f}", f"{itr_income:.0f}", ev)]
    return [mk(rule, FAIL, f"Declared annual income {annual:,.0f} differs from ITR income {itr_income:,.0f} by {diff * 100:.1f}% "
               f"(tolerance {tol * 100:.0f}%).", [itr[0].doc_id], "declared_income", f"{annual:.0f}", f"{itr_income:.0f}", ev)]


def r013_dup_account(ctx, rule):
    out = []
    for d in ctx.docs(C.BANK_STATEMENT):
        f = ctx.fields.get(d.id, {})
        bank = (f.get("bank_name").value if f.get("bank_name") else None) or ""
        acct = (f.get("account_number_masked").value if f.get("account_number_masked") else None) or ""
        if not acct:
            continue
        others = ctx.other_accounts.get((bank.strip().lower(), acct.strip().upper()), [])
        if others:
            out.append(mk(rule, WARN, f"The masked account identifier {acct} at {bank} also appears in application(s) {', '.join(others)}. "
                          "Masked identifiers can coincide by chance; verify manually.", [d.id], "account_number_masked",
                          "unique across applications", ", ".join(others), {"other_applications": others}))
    return out or [mk(rule, PASS, "No other application uses the same bank account identifier.")]


def r014_anomalies(ctx, rule):
    rep = ctx.anomaly
    if rep is None or not getattr(rep, "n_transactions", 0):
        return [mk(rule, SKIPPED, "No parsed transactions available for anomaly analysis.")]
    flagged = [t for t in ctx.transactions if t.is_anomalous]
    if not flagged and not getattr(rep, "account_findings", []):
        return [mk(rule, PASS, f"No statistically unusual transactions among {rep.n_transactions} (not proof of anything either way).")]
    out = []
    if flagged:
        top = sorted(flagged, key=lambda t: -(t.anomaly_score or 0))[:5]
        out.append(mk(rule, WARN, f"{len(flagged)} transaction(s) look statistically unusual (e.g. {top[0].txn_date}: "
                      f"{top[0].credit or top[0].debit:,.2f}; {'; '.join(top[0].anomaly_reasons or [])}). "
                      "Statistical anomalies are prompts for review, not evidence of fraud.", [flagged[0].document_id], "transactions",
                      "typical pattern", f"{len(flagged)} unusual",
                      {"flagged": [{"date": t.txn_date, "description": t.description, "credit": t.credit, "debit": t.debit,
                                    "score": t.anomaly_score, "robust_z": t.robust_z, "reasons": t.anomaly_reasons} for t in top]}))
    for fnd in getattr(rep, "account_findings", []):
        out.append(mk(rule, WARN, fnd["message"], [], fnd["kind"], evidence=fnd))
    return out


def r015_other_required(ctx, rule):
    required = (rule.params or {}).get(ctx.application.application_type, [])
    missing = [c for c in required if not ctx.docs(c)]
    if not missing:
        return [mk(rule, PASS, f"All other required documents present ({', '.join(required) or 'none required'}).")]
    return [mk(rule, FAIL, f"Required document missing: {c.replace('_', ' ').title()}.", field=c.lower(), expected="present",
               observed="missing") for c in missing]


def r016_manual(ctx, rule):
    thr = _p(rule, "min_classification_confidence", 0.5)
    out = []
    for d in ctx.all_documents:
        if d.duplicate_of or d.processing_error:
            continue
        if d.category == DocCategory.UNKNOWN.value:
            out.append(mk(rule, FAIL, f"'{d.original_filename}' could not be classified confidently (confidence "
                          f"{(d.classification_confidence or 0):.2f}); a reviewer should identify it.", [d.id], "document_type",
                          f"confidence >= {thr}", f"{(d.classification_confidence or 0):.2f}"))
        if any("prompt injection" in w for w in (d.warnings or [])):
            out.append(mk(rule, FAIL, f"'{d.original_filename}' contains instruction-like text addressed to an AI system. It was treated as "
                          "data and ignored; manual verification is required.", [d.id], "document_text"))
    return out or [mk(rule, PASS, "All documents classified confidently with no embedded-instruction warnings.")]


def r017_identifiers(ctx, rule):
    out, checked = [], 0
    for cat, name, fn, label in [(C.PAN, "pan_number", nz.is_valid_pan, "PAN"), (C.ITR, "pan_number", nz.is_valid_pan, "PAN"),
                                 (C.LOAN_APPLICATION, "pan_number", nz.is_valid_pan, "PAN"),
                                 (C.GST_CERTIFICATE, "gstin", nz.is_valid_gstin, "GSTIN")]:
        for r in ctx.refs(cat, name):
            if not r.value:
                continue
            checked += 1
            v = re.sub(r"\s", "", r.value).upper()
            if not fn(v):
                out.append(mk(rule, FAIL, f"{label} '{v}' on {cat.replace('_', ' ').title()} has an invalid format" +
                              (" or checksum" if label == "GSTIN" else "") + ". (Format check only - not verified against any registry.)",
                              [r.doc_id], name, f"valid {label} format", v, {"source": r.as_evidence()}))
    return out or [mk(rule, PASS, f"{checked} identifier(s) have a valid format (format check only).")]


def r018_income_credits(ctx, rule):
    declared = ctx.application.declared_monthly_income
    if not declared or not ctx.transactions:
        return [mk(rule, SKIPPED, "Needs declared monthly income and parsed bank transactions.")]
    monthly: dict[str, float] = {}
    for t in ctx.transactions:  # median monthly total: robust to a single large one-off credit
        monthly[t.txn_date[:7]] = monthly.get(t.txn_date[:7], 0.0) + t.credit
    avg = statistics.median(monthly.values())
    ratio = avg / declared
    lo, hi = _p(rule, "min_ratio", 0.5), _p(rule, "max_ratio", 2.0)
    ev = {"median_monthly_credits": round(avg, 2), "declared_monthly_income": declared, "ratio": round(ratio, 2)}
    if lo <= ratio <= hi:
        return [mk(rule, PASS, f"Median monthly credits {avg:,.0f} are {ratio:.2f}x declared income.", [], "monthly_credits", f"{lo}-{hi}x", f"{ratio:.2f}x", ev)]
    return [mk(rule, WARN, f"Median monthly credits {avg:,.0f} are {ratio:.2f}x the declared monthly income {declared:,.0f} (expected {lo}-{hi}x).",
               [], "monthly_credits", f"{lo}-{hi}x", f"{ratio:.2f}x", ev)]


def r019_pan_consistency(ctx, rule):
    refs = [r for cat in (C.PAN, C.LOAN_APPLICATION, C.ITR) for r in ctx.refs(cat, "pan_number") if r.value]
    if len(refs) < 2:
        return [mk(rule, SKIPPED, "Fewer than two documents carry a PAN number to compare.")]
    base = refs[0]
    vals = {re.sub(r"\s", "", r.value).upper() for r in refs}
    if len(vals) == 1:
        return [mk(rule, PASS, f"PAN number is identical on {len(refs)} documents.", [r.doc_id for r in refs], "pan_number")]
    bad = [r for r in refs[1:] if re.sub(r"\s", "", r.value).upper() != re.sub(r"\s", "", base.value).upper()]
    return [mk(rule, FAIL, f"PAN number on {r.category.replace('_', ' ').title()} ({r.value}) differs from {base.category.replace('_', ' ').title()} ({base.value}).",
               [base.doc_id, r.doc_id], "pan_number", base.value, r.value,
               {"compared": [base.as_evidence(), r.as_evidence()]}) for r in bad]


# --- generic, admin-creatable rule kinds
def generic_required_document(ctx, rule):
    cat = _p(rule, "category", "")
    types = _p(rule, "application_types", None)
    if types and ctx.application.application_type not in types:
        return [mk(rule, SKIPPED, f"Not applicable to {ctx.application.application_type} applications.")]
    if ctx.docs(cat):
        return [mk(rule, PASS, f"{cat} document present.", [ctx.docs(cat)[0].id])]
    return [mk(rule, FAIL, f"Required document {cat} is missing.", field=cat.lower(), expected="present", observed="missing")]


def generic_field_present(ctx, rule):
    cat, fname = _p(rule, "category", ""), _p(rule, "field", "")
    refs = ctx.refs(cat, fname)
    if not refs:
        return [mk(rule, SKIPPED, f"No {cat} document to check.")]
    missing = [r for r in refs if not r.value]
    if missing:
        return [mk(rule, FAIL, f"Field '{fname}' not found on {cat} document.", [r.doc_id], fname, "present", "missing") for r in missing]
    return [mk(rule, PASS, f"Field '{fname}' present on {cat}.", [refs[0].doc_id], fname)]


BUILTIN: dict[str, Callable[[VerificationContext, VerificationRule], list[RuleResult]]] = {
    "R001": r001_pan_missing, "R002": r002_name_mismatch, "R003": r003_bank_missing, "R004": r004_salary,
    "R005": r005_duplicates, "R006": r006_statement_period, "R007": r007_itr_missing, "R008": r008_ocr_conf,
    "R009": r009_bank_name, "R010": r010_invalid_format, "R011": r011_address, "R012": r012_income_itr,
    "R013": r013_dup_account, "R014": r014_anomalies, "R015": r015_other_required, "R016": r016_manual,
    "R017": r017_identifiers, "R018": r018_income_credits, "R019": r019_pan_consistency,
}
GENERIC = {"required_document": generic_required_document, "field_present": generic_field_present}


def evaluate_rule(ctx: VerificationContext, rule: VerificationRule) -> list[RuleResult]:
    """Run a single rule; guarantees at least one result and isolates rule failures."""
    if not rule.enabled:
        return [RuleResult(rule.id, SKIPPED, rule.severity, "Rule is disabled by an administrator.")]
    handler = GENERIC.get(rule.kind) if rule.kind != "builtin" else BUILTIN.get(rule.id)
    if handler is None:
        return [RuleResult(rule.id, SKIPPED, rule.severity, f"No handler registered for rule kind '{rule.kind}'.")]
    try:
        res = handler(ctx, rule)
    except Exception as exc:  # noqa: BLE001 - a broken rule must not abort the whole run
        return [RuleResult(rule.id, WARN, "LOW", f"Rule could not be evaluated ({type(exc).__name__}); manual check advised.")]
    return res or [mk(rule, PASS, "No issues found.")]


# --------------------------------------------------------------------------- orchestration
def build_context(db: Session, app: Application) -> VerificationContext:
    docs = list(db.scalars(select(Document).where(Document.application_id == app.id).order_by(Document.uploaded_at)))
    fields: dict[str, dict[str, ExtractedField]] = {}
    for f in db.scalars(select(ExtractedField).where(ExtractedField.document_id.in_([d.id for d in docs]) if docs else False)):
        fields.setdefault(f.document_id, {})[f.field_name] = f
    txns = list(db.scalars(select(TransactionRecord).where(TransactionRecord.application_id == app.id).order_by(TransactionRecord.txn_date)))
    other: dict[tuple[str, str], list[str]] = {}
    rows = db.execute(select(Document.application_id, ExtractedField.document_id, ExtractedField.field_name, ExtractedField.value)
                      .join(ExtractedField, ExtractedField.document_id == Document.id)
                      .where(Document.category == DocCategory.BANK_STATEMENT.value, Document.application_id != app.id,
                             ExtractedField.field_name.in_(["bank_name", "account_number_masked"]))).all()
    by_doc: dict[str, dict] = {}
    for app_id, doc_id, fname, val in rows:
        by_doc.setdefault(doc_id, {"app": app_id})[fname] = (val or "").strip()
    for info in by_doc.values():
        if info.get("account_number_masked"):
            other.setdefault((info.get("bank_name", "").lower(), info["account_number_masked"].upper()), []).append(info["app"])
    return VerificationContext(app, docs, fields, txns, app.created_at.date() if app.created_at else date.today(), other)


@dataclass
class VerificationOutcome:
    run_id: str
    results: list[VerificationResult]
    exceptions_created: int = 0
    exceptions_auto_resolved: int = 0


def run_verification(db: Session, app: Application, actor: str = "system") -> VerificationOutcome:
    """Execute anomaly detection + all rules for an application, persist results and sync exceptions."""
    from app.services import anomaly_detection, exception_manager  # local imports avoid cycles

    run_id = "RUN-" + uuid.uuid4().hex[:10].upper()
    started = utcnow()
    ctx = build_context(db, app)
    ctx.anomaly = anomaly_detection.analyze_application(db, app, ctx.transactions)
    ctx.transactions = list(db.scalars(select(TransactionRecord).where(TransactionRecord.application_id == app.id).order_by(TransactionRecord.txn_date)))
    rules = list(db.scalars(select(VerificationRule).order_by(VerificationRule.id)))
    stored: list[VerificationResult] = []
    for rule in rules:
        for r in evaluate_rule(ctx, rule):
            vr = VerificationResult(run_id=run_id, application_id=app.id, rule_id=rule.id, rule_version=rule.version,
                                    document_ids=r.document_ids, field=r.field, expected=r.expected, observed=r.observed,
                                    outcome=r.outcome, severity=r.severity, explanation=r.explanation)
            vr._evidence = r.evidence  # transient: used when creating exceptions
            db.add(vr)
            stored.append(vr)
    db.flush()
    created, resolved = exception_manager.sync_exceptions(db, app, run_id, stored, {r.id: r for r in rules}, actor)
    _update_statuses(db, app)
    app.last_verified_at = utcnow()
    n_fail = sum(1 for v in stored if v.outcome in (FAIL, WARN))
    audit.log_event(db, actor, "VERIFICATION_RUN", "application", app.id, None, {"status": app.status},
                    {"run_id": run_id, "rules_evaluated": len(rules), "results": len(stored), "failed_or_warned": n_fail,
                     "rule_versions": {r.id: r.version for r in rules}, "exceptions_created": created, "auto_resolved": resolved,
                     "notice": DEMO_RULES_NOTICE})
    db.add(ModelRun(run_type="verification", model_name="rule_engine", application_id=app.id, params={"run_id": run_id},
                    metrics={"results": len(stored), "failed_or_warned": n_fail}, n_records=len(stored),
                    started_at=started, finished_at=utcnow()))
    return VerificationOutcome(run_id, stored, created, resolved)


def _update_statuses(db: Session, app: Application) -> None:
    from app.models import ExceptionRecord, ExcStatus
    open_exc = list(db.scalars(select(ExceptionRecord).where(ExceptionRecord.application_id == app.id,
                                                             ExceptionRecord.status != ExcStatus.RESOLVED.value)))
    flagged_docs = {d for e in open_exc for d in (e.evidence or {}).get("document_ids", [])}
    for d in db.scalars(select(Document).where(Document.application_id == app.id)):
        if d.status == DocStatus.REJECTED.value:
            continue
        if d.processing_error or d.duplicate_of or d.id in flagged_docs:
            d.status = DocStatus.EXCEPTION_DETECTED.value
        else:
            d.status = DocStatus.VERIFIED.value
    app.status = AppStatus.EXCEPTION_DETECTED.value if open_exc else AppStatus.VERIFIED.value


def verification_summary(db: Session, app: Application) -> dict:
    """Deterministic, human-readable summary of the latest run (the LLM narrative, if any, is separate)."""
    last = db.scalar(select(VerificationResult.run_id).where(VerificationResult.application_id == app.id)
                     .order_by(VerificationResult.id.desc()).limit(1))
    if not last:
        return {"run_id": None, "headline": "Verification has not been run for this application.", "counts": {}}
    rows = list(db.scalars(select(VerificationResult).where(VerificationResult.run_id == last)))
    counts = {o: sum(1 for r in rows if r.outcome == o) for o in (PASS, FAIL, WARN, SKIPPED)}
    bad = [r for r in rows if r.outcome in (FAIL, WARN)]
    high = [r for r in bad if r.severity == "HIGH"]
    headline = (f"{counts[FAIL]} failed and {counts[WARN]} warning result(s) ({len(high)} high severity) need human review."
                if bad else "No exceptions were raised by the automated checks. A human decision is still required.")
    return {"run_id": last, "headline": headline, "counts": counts,
            "top_issues": [{"rule_id": r.rule_id, "severity": r.severity, "explanation": r.explanation} for r in
                           sorted(bad, key=lambda r: -_SEV_ORDER[r.severity])[:5]],
            "notice": "Automated pre-check only. It does not approve or reject any loan. " + DEMO_RULES_NOTICE}
