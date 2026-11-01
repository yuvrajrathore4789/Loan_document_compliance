"""Deterministic structured-field extraction (regex over labelled lines + table/row parsing).

Rules: unavailable fields are ``None`` (never fabricated); each field carries confidence, page
number and method; full Aadhaar numbers are redacted before anything is stored.
Extracted != verified: ``is_verified`` stays False until a human confirms a value.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from app.models import DocCategory
from app.services.ocr_service import ExtractionResult
from app.utils import normalization as nz


@dataclass
class FieldValue:
    name: str
    value: str | None
    confidence: float | None
    page: int | None = None
    method: str = "regex"
    normalized: str | None = None


@dataclass
class Txn:
    txn_date: date
    description: str
    credit: float
    debit: float
    balance: float | None
    page: int | None = None


@dataclass
class ExtractedDocument:
    category: DocCategory
    fields: dict[str, FieldValue]
    transactions: list[Txn] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# field -> label alternatives. Order = priority.
LABELS: dict[DocCategory, dict[str, list[str]]] = {
    DocCategory.PAN: {
        "name": ["Name", "Cardholder Name", "Name of Holder"],
        "pan_number": ["Permanent Account Number", "PAN Number", "PAN No", "PAN"],
        "date_of_birth": ["Date of Birth", "DOB"],
    },
    DocCategory.AADHAAR: {
        "name": ["Name"],
        "address": ["Address"],
        "aadhaar_masked": ["Aadhaar No", "Aadhaar Number", "Aadhar No", "VID"],
    },
    DocCategory.BANK_STATEMENT: {
        "account_holder": ["Account Holder", "Account Holder Name", "Customer Name", "Name"],
        "account_number_masked": ["Account Number", "Account No", "A/c No"],
        "bank_name": ["Bank Name", "Bank"],
        "statement_period": ["Statement Period", "Period"],
        "closing_balance": ["Closing Balance"],
        "opening_balance": ["Opening Balance"],
    },
    DocCategory.SALARY_SLIP: {
        "employee_name": ["Employee Name", "Name of Employee", "Name"],
        "employer_name": ["Employer", "Employer Name", "Company Name", "Company"],
        "gross_salary": ["Gross Salary", "Gross Earnings", "Gross Pay"],
        "net_salary": ["Net Salary", "Net Pay", "Net Payable"],
        "deductions": ["Total Deductions", "Deductions"],
        "pay_period": ["Pay Period", "Salary Month", "Month"],
    },
    DocCategory.ITR: {
        "taxpayer_name": ["Name of Assessee", "Taxpayer Name", "Name"],
        "pan_number": ["PAN", "Permanent Account Number"],
        "assessment_year": ["Assessment Year", "AY"],
        "declared_income": ["Total Income", "Gross Total Income", "Declared Income"],
        "filing_date": ["Date of Filing", "Filing Date", "Filed On"],
        "acknowledgement_number": ["Acknowledgement Number", "Acknowledgment Number", "Acknowledgement No"],
    },
    DocCategory.GST_CERTIFICATE: {
        "business_name": ["Legal Name", "Trade Name", "Business Name"],
        "gstin": ["GSTIN", "Registration Number", "GST Number"],
        "registration_status": ["Registration Status", "Status"],
        "address": ["Address of Principal Place of Business", "Business Address", "Address"],
    },
    DocCategory.BUSINESS_REGISTRATION: {
        "business_name": ["Name of Enterprise", "Company Name", "Name of the Company", "Business Name", "Name"],
        "registration_number": ["Registration Number", "CIN", "Udyam Registration Number", "Registration No"],
        "address": ["Registered Office", "Address", "Business Address"],
        "incorporation_date": ["Date of Incorporation", "Date of Registration"],
    },
    DocCategory.LOAN_APPLICATION: {
        "applicant_name": ["Applicant Name", "Name of Applicant", "Name"],
        "pan_number": ["PAN", "PAN Number"],
        "date_of_birth": ["Date of Birth", "DOB"],
        "address": ["Residential Address", "Address"],
        "employer_name": ["Employer", "Employer Name", "Company Name"],
        "declared_monthly_income": ["Monthly Income", "Declared Monthly Income", "Net Monthly Income"],
        "loan_amount": ["Loan Amount", "Loan Amount Requested", "Amount Requested"],
        "bank_account_masked": ["Bank Account Number", "Account Number"],
        "account_holder": ["Account Holder Name", "Account Holder"],
    },
}
REQUIRED_FIELDS: dict[DocCategory, list[str]] = {
    DocCategory.PAN: ["name", "pan_number"],
    DocCategory.AADHAAR: ["name", "aadhaar_masked"],
    DocCategory.BANK_STATEMENT: ["account_holder", "account_number_masked", "statement_period"],
    DocCategory.SALARY_SLIP: ["employee_name", "gross_salary", "net_salary"],
    DocCategory.ITR: ["taxpayer_name", "assessment_year", "declared_income"],
    DocCategory.GST_CERTIFICATE: ["business_name", "gstin"],
    DocCategory.BUSINESS_REGISTRATION: ["business_name", "registration_number"],
    DocCategory.LOAN_APPLICATION: ["applicant_name"],
}
ALLOWED_FIELDS = {cat: set(m) for cat, m in LABELS.items()}
BASE_CONF = 0.92
MONEY_FIELDS = {"gross_salary", "net_salary", "deductions", "declared_income", "closing_balance",
                "opening_balance", "declared_monthly_income", "loan_amount"}


def _label_regex(labels: list[str]) -> re.Pattern:
    alt = "|".join(re.escape(l).replace(r"\ ", r"\s+") for l in labels)
    return re.compile(rf"^\s*(?:{alt})\s*[:\-–=]\s*(?P<v>\S.*?)\s*$", re.IGNORECASE)


def _clean_value(v: str) -> str:
    return re.sub(r"\s+", " ", v).strip(" \t|_")


def find_labelled(result: ExtractionResult, labels: list[str]) -> tuple[str, int, str] | None:
    """First 'Label: value' line (priority = order of labels). Returns (value, page, matched_label)."""
    for label in labels:
        rx = _label_regex([label])
        for page in result.pages:
            for line in page.text.splitlines():
                m = rx.match(line)
                if m:
                    return _clean_value(m.group("v")), page.page, label
    return None


def _page_conf(result: ExtractionResult, page: int) -> float:
    for p in result.pages:
        if p.page == page:
            return 1.0 if p.confidence is None else p.confidence
    return 1.0


def _normalize(name: str, value: str) -> str | None:
    if name in MONEY_FIELDS:
        amt = nz.parse_amount(value)
        return None if amt is None else f"{amt:.2f}"
    if name in {"pan_number", "gstin"}:
        return re.sub(r"\s", "", value).upper()
    if name in {"date_of_birth", "filing_date", "incorporation_date"}:
        d = nz.parse_date(value)
        return d.isoformat() if d else None
    if name in {"name", "employee_name", "taxpayer_name", "applicant_name", "account_holder"}:
        return nz.normalize_name(value) or None
    if name == "address":
        return nz.normalize_address(value) or None
    return value.strip().lower()


def _validate_confidence(name: str, value: str, base: float) -> float:
    """Format validation nudges confidence (never decides compliance)."""
    if name == "pan_number":
        return base if nz.is_valid_pan(re.sub(r"\s", "", value).upper()) else min(base, 0.5)
    if name == "gstin":
        return base if nz.is_valid_gstin(re.sub(r"\s", "", value)) else min(base, 0.5)
    if name in MONEY_FIELDS:
        return base if nz.parse_amount(value) is not None else min(base, 0.4)
    return base


# ------------------------------------------------------------------ bank statement parsing
_AMT = r"(?:\d[\d,]*\.\d{2}|-)"
_DATE = r"\d{2}[\s/\-](?:[A-Za-z]{3}|\d{2})[\s/\-]\d{2,4}"
_TXN_RX = re.compile(rf"^\s*(?P<date>{_DATE})\s+(?P<desc>.+?)\s+(?P<a>{_AMT})\s+(?P<b>{_AMT})(?:\s+(?P<c>{_AMT}))?\s*$")


def parse_transactions(result: ExtractionResult) -> list[Txn]:
    """Parse transaction rows. 3 amount columns = Debit|Credit|Balance ('-' for empty);
    2 columns = Amount|Balance with the direction inferred from the running balance."""
    txns: list[Txn] = []
    prev_balance: float | None = None
    for page in result.pages:
        rows = page.rows or page.text.splitlines()
        for line in rows:
            m = _TXN_RX.match(line)
            if not m:
                continue
            d = nz.parse_date(re.sub(r"\s+", " ", m.group("date")))
            if d is None:
                continue

            def amt_of(x: str | None) -> float | None:
                return None if x is None else (0.0 if x == "-" else nz.parse_amount(x))

            a, b, c = amt_of(m.group("a")), amt_of(m.group("b")), amt_of(m.group("c"))
            if c is not None:  # debit | credit | balance
                debit, credit, bal = a or 0.0, b or 0.0, c
            else:              # amount | balance
                amt, bal = a or 0.0, b
                if prev_balance is not None and bal is not None:
                    credit, debit = (amt, 0.0) if abs(prev_balance + amt - bal) <= abs(prev_balance - amt - bal) else (0.0, amt)
                else:
                    credit, debit = 0.0, amt
            prev_balance = bal if bal is not None else prev_balance
            txns.append(Txn(d, _clean_value(m.group("desc")), float(credit), float(debit), bal, page.page))
    return txns


def _parse_period(value: str | None) -> tuple[date, date] | None:
    if not value:
        return None
    parts = re.split(r"\s+(?:to|-|–)\s+", value.strip(), maxsplit=1, flags=re.IGNORECASE)
    if len(parts) != 2:
        return None
    a, b = nz.parse_date(parts[0]), nz.parse_date(parts[1])
    return (a, b) if a and b else None


# ------------------------------------------------------------------ main
def extract_fields(result: ExtractionResult, category: DocCategory) -> ExtractedDocument:
    doc = ExtractedDocument(category, {})
    labels = LABELS.get(category)
    if not labels:
        return doc
    for fname, label_list in labels.items():
        hit = find_labelled(result, label_list)
        if hit is None:
            doc.fields[fname] = FieldValue(fname, None, None)
            continue
        value, page, _ = hit
        value = re.sub(r"\s*\|.*$", "", value) if fname in {"name"} else value
        conf = _validate_confidence(fname, value, round(BASE_CONF * _page_conf(result, page), 4))
        doc.fields[fname] = FieldValue(fname, value, conf, page, "regex", _normalize(fname, value))
    # PAN can also be recognised without a label (digital docs) - only when label lookup failed
    if "pan_number" in doc.fields and doc.fields["pan_number"].value is None:
        m = re.search(r"\b([A-Z]{5}\d{4}[A-Z])\b", result.text)
        if m:
            doc.fields["pan_number"] = FieldValue("pan_number", m.group(1), round(0.7 * _page_conf(result, 1), 4), 1,
                                                  "regex", m.group(1))
    if category == DocCategory.BANK_STATEMENT:
        doc.transactions = parse_transactions(result)
        per = _parse_period(doc.fields["statement_period"].value)
        if per:
            doc.fields["period_start"] = FieldValue("period_start", per[0].isoformat(), doc.fields["statement_period"].confidence,
                                                    doc.fields["statement_period"].page, "regex", per[0].isoformat())
            doc.fields["period_end"] = FieldValue("period_end", per[1].isoformat(), doc.fields["statement_period"].confidence,
                                                  doc.fields["statement_period"].page, "regex", per[1].isoformat())
        else:
            doc.fields["period_start"] = FieldValue("period_start", None, None)
            doc.fields["period_end"] = FieldValue("period_end", None, None)
            if doc.fields["statement_period"].value:
                doc.warnings.append("Statement period text could not be parsed into two dates.")
        if not doc.transactions:
            doc.warnings.append("No transaction rows could be parsed from the statement.")
    if category == DocCategory.AADHAAR:
        v = doc.fields["aadhaar_masked"].value
        if v and re.search(r"\d{12}", re.sub(r"\D", "", v)) and "X" not in v.upper():
            doc.fields["aadhaar_masked"].value = nz.mask_identifier(v)
            doc.warnings.append("Full Aadhaar-like number detected and masked before storage.")
    missing = [f for f in REQUIRED_FIELDS.get(category, []) if doc.fields.get(f) is None or doc.fields[f].value is None]
    if missing:
        doc.warnings.append(f"Required fields not found: {', '.join(missing)}")
    return doc


def missing_required(doc: ExtractedDocument) -> list[str]:
    return [f for f in REQUIRED_FIELDS.get(doc.category, []) if doc.fields.get(f) is None or doc.fields[f].value is None]
