"""Synthetic (fictional) persons, documents and bank transactions for demos and tests.

Everything generated here is FICTIONAL and watermarked "SYNTHETIC SAMPLE". PAN-/GSTIN-shaped
identifiers are random strings in valid formats (GSTIN checksums are computed), Aadhaar numbers
are always masked, bank accounts are masked and unique per fictional person. They are not
real identifiers. Rendering uses reportlab (digital PDFs) and PIL/OpenCV-free degradation
(scans) so that the REAL OCR/extraction pipeline is exercised on them.
"""
from __future__ import annotations

import io
import random
from dataclasses import dataclass, field
from datetime import date, timedelta

from PIL import Image, ImageFilter
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from app.utils.normalization import gstin_checksum_char

WATERMARK = "SYNTHETIC SAMPLE - FICTIONAL DATA - NOT A REAL DOCUMENT"
FIRST = ["Aarav", "Vivaan", "Aditya", "Arjun", "Rohan", "Karan", "Ishaan", "Rahul", "Amit", "Vikram", "Siddharth",
         "Priya", "Ananya", "Kavya", "Neha", "Pooja", "Riya", "Sneha", "Divya", "Meera", "Nisha", "Tara", "Isha"]
MIDDLE = ["Kumar", "Lal", "Prasad", "Devi", "Raj", "Nath", "Singh", "Chandra", "Mohan", "Kishore"]
LAST = ["Sharma", "Verma", "Iyer", "Nair", "Reddy", "Patel", "Mehta", "Gupta", "Joshi", "Kulkarni", "Banerjee",
        "Chatterjee", "Pillai", "Menon", "Desai", "Bhatt", "Malhotra", "Saxena", "Tiwari", "Rao"]
BANKS = ["Sample National Bank", "Demo Commercial Bank", "Fictional Co-operative Bank"]
EMPLOYERS = ["Acme Synthetic Pvt Ltd", "Northwind Demo Technologies", "Contoso Fictional Services", "Globex Sample Industries",
             "Initech Demo Solutions", "Umbrella Mock Logistics", "Stark Imaginary Systems", "Wayne Fictional Retail"]
BUILDINGS = ["Lotus Heights", "Maple Residency", "Sunrise Apartments", "Green Meadows", "Orchid Towers", "Palm Court",
             "Blue Ridge Society", "Harmony Enclave", "Silver Oak Colony", "Rainbow Villas"]
STREETS = ["MG Road", "Station Road", "Park Street", "Lake View Road", "Temple Road", "Market Cross Road", "Ring Road"]
CITIES = [("Pune", "Maharashtra", "411"), ("Bengaluru", "Karnataka", "560"), ("Hyderabad", "Telangana", "500"),
          ("Chennai", "Tamil Nadu", "600"), ("Ahmedabad", "Gujarat", "380"), ("Jaipur", "Rajasthan", "302"),
          ("Kolkata", "West Bengal", "700"), ("Lucknow", "Uttar Pradesh", "226")]
STATE_CODES = {"Maharashtra": "27", "Karnataka": "29", "Telangana": "36", "Tamil Nadu": "33", "Gujarat": "24",
               "Rajasthan": "08", "West Bengal": "19", "Uttar Pradesh": "09"}
BUSINESS_WORDS = ["Traders", "Enterprises", "Industries", "Solutions", "Agencies", "Foods", "Textiles", "Hardware"]


@dataclass
class Person:
    name: str
    dob: date
    pan: str
    aadhaar_masked: str
    address: str
    city: str
    state: str
    employer: str
    gross: float
    deductions: float
    net: float
    bank_name: str
    account_masked: str
    app_type: str
    business_name: str = ""
    gstin: str = ""
    registration_no: str = ""
    annual_income: float = 0.0
    loan_amount: float = 0.0
    declared_monthly_income: float = 0.0


def _inr(x: float) -> str:
    """Indian digit grouping, 2 decimals: 1234567.5 -> 12,34,567.50"""
    s = f"{abs(x):.2f}"
    whole, frac = s.split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join(parts + [tail])
    return ("-" if x < 0 else "") + whole + "." + frac


_used_accounts: set[str] = set()


def unique_account(rng: random.Random) -> str:
    while True:
        a = "XXXXXXXX" + f"{rng.randint(1000, 9999)}"
        if a not in _used_accounts:
            _used_accounts.add(a)
            return a


def make_person(rng: random.Random, app_type: str = "SALARIED", ref: date = date(2026, 10, 31)) -> Person:
    name = f"{rng.choice(FIRST)} {rng.choice(MIDDLE)} {rng.choice(LAST)}" if rng.random() < 0.6 else f"{rng.choice(FIRST)} {rng.choice(LAST)}"
    surname = name.split()[-1]
    pan = "".join(rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZ") for _ in range(3)) + "P" + surname[0].upper() \
        + f"{rng.randint(1000, 9999)}" + rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZ")
    city, state, pin = rng.choice(CITIES)
    address = f"Flat {rng.randint(101, 909)}, {rng.choice(BUILDINGS)}, {rng.choice(STREETS)}, {city}, {state} {pin}{rng.randint(100, 999)}"
    gross = float(rng.choice(range(30000, 150001, 2500)))
    deductions = round(gross * rng.uniform(0.08, 0.16), 2)
    net = round(gross - deductions, 2)
    p = Person(name=name, dob=date(rng.randint(1970, 2000), rng.randint(1, 12), rng.randint(1, 28)), pan=pan,
               aadhaar_masked=f"XXXX XXXX {rng.randint(1000, 9999)}", address=address, city=city, state=state,
               employer=rng.choice(EMPLOYERS), gross=gross, deductions=deductions, net=net,
               bank_name=rng.choice(BANKS), account_masked=unique_account(rng), app_type=app_type)
    if app_type == "SELF_EMPLOYED":
        p.business_name = f"{surname} {rng.choice(BUSINESS_WORDS)}"
        p.annual_income = float(rng.choice(range(600000, 2400001, 50000)))
        body = pan[:10]
        first14 = f"{STATE_CODES[state]}{body}1Z"
        p.gstin = first14 + gstin_checksum_char(first14)
        p.registration_no = f"U{rng.randint(10000, 99999)}{state[:2].upper()}{rng.randint(2010, 2022)}PTC{rng.randint(100000, 999999)}"
        p.declared_monthly_income = round(p.annual_income / 12, 2)
    else:
        p.annual_income = round(gross * 12, 2)
        p.declared_monthly_income = net
    p.loan_amount = float(rng.choice(range(100000, 2500001, 50000)))
    return p


# ------------------------------------------------------------------ name / value perturbations
def perturb_name_material(name: str, rng: random.Random) -> str:
    """A materially different name (different surname)."""
    parts = name.split()
    others = [s for s in LAST if s != parts[-1]]
    parts[-1] = rng.choice(others)
    return " ".join(parts)


def perturb_name_typo(name: str) -> str:
    """A small spelling variation (one letter changed in the first name)."""
    parts = name.split()
    f = parts[0]
    parts[0] = f[:-1] + ("a" if f[-1] != "a" else "e") if len(f) > 3 else f + "h"
    return " ".join(parts)


# ------------------------------------------------------------------ PDF rendering
def _pdf_from_lines(lines: list[str], font: str = "Helvetica", size: int = 11, lines_per_page: int = 52,
                    title: str | None = None) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    pages = [lines[i:i + lines_per_page] for i in range(0, len(lines), lines_per_page)] or [[]]
    for pi, chunk in enumerate(pages):
        y = h - 60
        if title and pi == 0:
            c.setFont("Helvetica-Bold", 15)
            c.drawString(50, y, title)
            y -= 30
        c.setFont(font, size)
        for ln in chunk:
            c.drawString(50, y, ln)
            y -= size + 5
        c.setFont("Helvetica-Oblique", 8)
        c.drawString(50, 30, f"{WATERMARK}   (page {pi + 1}/{len(pages)})")
        c.showPage()
    c.save()
    return buf.getvalue()


def render_pan(p: Person, name: str | None = None, pan: str | None = None) -> bytes:
    return _pdf_from_lines([
        "GOVT. OF INDIA", "PERMANENT ACCOUNT NUMBER CARD", "",
        f"Name: {(name or p.name).upper()}", "Father's Name: (not recorded in sample)",
        f"Date of Birth: {p.dob.strftime('%d/%m/%Y')}", f"Permanent Account Number: {pan or p.pan}",
    ], title="INCOME TAX DEPARTMENT")


def render_aadhaar(p: Person, name: str | None = None, address: str | None = None) -> bytes:
    return _pdf_from_lines([
        "Unique Identification Authority of India (sample layout)", "",
        f"Name: {name or p.name}", f"Date of Birth: {p.dob.strftime('%d/%m/%Y')}",
        f"Address: {address or p.address}", f"Aadhaar No: {p.aadhaar_masked}",
    ], title="Aadhaar (Synthetic Sample)")


def render_salary_slip(p: Person, name: str | None = None, net: float | None = None, month: str = "September 2026") -> bytes:
    net_v = p.net if net is None else net
    gross_v = round(net_v + p.deductions, 2)
    return _pdf_from_lines([
        f"Employer: {p.employer}", f"Employee Name: {name or p.name}", "Employee ID: SYN-0001",
        f"Pay Period: {month}", "", f"Gross Salary: {_inr(gross_v)}", f"Total Deductions: {_inr(p.deductions)}",
        f"Net Salary: {_inr(net_v)}",
    ], title="SALARY SLIP")


def render_itr(p: Person, income: float | None = None, name: str | None = None) -> bytes:
    return _pdf_from_lines([
        "Assessment Year: 2026-27", f"Name of Assessee: {name or p.name}", f"PAN: {p.pan}",
        f"Total Income: {_inr(income if income is not None else p.annual_income)}",
        "Date of Filing: 28/07/2026", f"Acknowledgement Number: {abs(hash(p.pan)) % 10**15:015d}",
    ], title="INCOME TAX RETURN ACKNOWLEDGEMENT (ITR-V)")


def render_gst(p: Person, gstin: str | None = None) -> bytes:
    return _pdf_from_lines([
        "Goods and Services Tax - Registration Certificate (sample layout)", "",
        f"GSTIN: {gstin or p.gstin}", f"Legal Name: {p.business_name}", f"Trade Name: {p.business_name}",
        f"Address of Principal Place of Business: {p.address}", "Registration Status: Active",
    ], title="GST REGISTRATION CERTIFICATE")


def render_business_registration(p: Person) -> bytes:
    return _pdf_from_lines([
        "Registrar of Companies (sample layout)", "",
        f"Name of Enterprise: {p.business_name} Private Limited", f"Registration Number: {p.registration_no}",
        f"Registered Office: {p.address}", "Date of Incorporation: 12/05/2018",
    ], title="CERTIFICATE OF INCORPORATION")


def render_application_form(p: Person, name: str | None = None, address: str | None = None,
                            account_holder: str | None = None, income: float | None = None,
                            extra_lines: list[str] | None = None) -> bytes:
    lines = [
        f"Applicant Name: {name or p.name}", f"Date of Birth: {p.dob.strftime('%d/%m/%Y')}", f"PAN: {p.pan}",
        f"Residential Address: {address or p.address}", f"Employer: {p.employer if p.app_type == 'SALARIED' else p.business_name}",
        f"Monthly Income: {_inr(income if income is not None else p.declared_monthly_income)}",
        f"Loan Amount: {_inr(p.loan_amount)}", "Tenure: 36 months", "Purpose of Loan: Personal use (sample)",
        f"Bank Account Number: {p.account_masked}", f"Account Holder Name: {account_holder or name or p.name}",
    ] + (extra_lines or [])
    return _pdf_from_lines(lines, title="LOAN APPLICATION FORM")


# ------------------------------------------------------------------ transactions + statements
@dataclass
class SynTxn:
    d: date
    desc: str
    debit: float
    credit: float
    balance: float = 0.0
    anomalous: bool = False


def _month_start(d: date, back: int) -> date:
    y, m = d.year, d.month - back
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, 1)


def generate_transactions(rng: random.Random, p: Person, months: int = 6, end: date = date(2026, 9, 30),
                          salary_amount: float | None = None, anomaly: str | None = None,
                          opening: float | None = None) -> tuple[list[SynTxn], float]:
    """Plausible monthly activity. anomaly in {None,'large_credit','credit_spike','burst','missing_salary'}."""
    opening = opening if opening is not None else float(rng.randint(20000, 90000))
    txns: list[SynTxn] = []
    sal = salary_amount if salary_amount is not None else p.net
    starts = [_month_start(end, i) for i in range(months - 1, -1, -1)]
    anomaly_month = starts[len(starts) // 2 + (1 if len(starts) > 3 else 0)] if starts else None
    for ms in starts:
        nm = _month_start(ms + timedelta(days=32), 0)
        last_day = (nm - timedelta(days=1)).day
        if p.app_type == "SALARIED":
            if not (anomaly == "missing_salary" and ms == anomaly_month):
                txns.append(SynTxn(ms.replace(day=rng.randint(1, 3)), f"SALARY CREDIT {p.employer.upper()}", 0.0,
                                   round(sal * rng.uniform(0.995, 1.005), 2)))
        else:
            for _ in range(rng.randint(3, 6)):
                txns.append(SynTxn(ms.replace(day=rng.randint(1, last_day)), f"NEFT CR CUSTOMER {rng.randint(100, 999)}", 0.0,
                                   round(p.declared_monthly_income / 4.5 * rng.uniform(0.6, 1.5), 2)))
        txns.append(SynTxn(ms.replace(day=rng.randint(4, 8)), "EMI/RENT PAYMENT", round(p.declared_monthly_income * rng.uniform(0.18, 0.28), 2), 0.0))
        for _ in range(rng.randint(10, 18)):
            kind = rng.choice(["UPI/GROCERY", "UPI/FOOD DELIVERY", "POS/RETAIL", "ATM WDL", "BILL PAY/UTILITY", "UPI/FUEL", "UPI/TRANSFER"])
            txns.append(SynTxn(ms.replace(day=rng.randint(1, last_day)), kind, round(rng.lognormvariate(7.0, 0.7), 2), 0.0))
        if rng.random() < 0.35:
            txns.append(SynTxn(ms.replace(day=rng.randint(10, last_day)), "UPI/RECEIVED FROM FRIEND", 0.0, round(rng.uniform(500, 5000), 2)))
    if anomaly == "large_credit" and anomaly_month:
        txns.append(SynTxn(anomaly_month.replace(day=15), "NEFT CR UNKNOWN REMITTER", 0.0, round(p.declared_monthly_income * rng.uniform(9, 14), 2), anomalous=True))
    if anomaly == "credit_spike" and anomaly_month:
        for k in range(4):
            txns.append(SynTxn(anomaly_month.replace(day=8 + 4 * k), "IMPS CR CASH DEPOSIT", 0.0, round(p.declared_monthly_income * rng.uniform(1.5, 2.2), 2), anomalous=True))
    if anomaly == "burst" and anomaly_month:
        for k in range(28):
            txns.append(SynTxn(anomaly_month.replace(day=18 + k % 8), "UPI/TRANSFER", round(rng.uniform(190, 260), 2), 0.0, anomalous=True))
    txns.sort(key=lambda t: (t.d, t.credit == 0))
    bal = opening
    for t in txns:
        bal = round(bal + t.credit - t.debit, 2)
        t.balance = bal
    return txns, opening


def render_bank_statement(p: Person, txns: list[SynTxn], opening: float, start: date, end: date,
                          holder: str | None = None, three_columns: bool = True) -> bytes:
    closing = txns[-1].balance if txns else opening
    head = [f"Account Holder: {holder or p.name}", f"Account Number: {p.account_masked}", f"Bank Name: {p.bank_name}",
            "IFSC: SMPL0000123 (synthetic)", f"Statement Period: {start.strftime('%d %b %Y')} to {end.strftime('%d %b %Y')}",
            f"Opening Balance: {_inr(opening)}", "",
            f"{'Date':<13}{'Description':<42}{'Debit':>13}{'Credit':>13}{'Balance':>15}"]
    rows = []
    for t in txns:
        deb = _inr(t.debit) if t.debit else "-"
        cre = _inr(t.credit) if t.credit else "-"
        rows.append(f"{t.d.strftime('%d %b %Y'):<13}{t.desc[:40]:<42}{deb:>13}{cre:>13}{_inr(t.balance):>15}")
    foot = ["", f"Closing Balance: {_inr(closing)}"]
    return _pdf_from_lines(head + rows + foot, font="Courier", size=8, lines_per_page=62, title=f"{p.bank_name} - Statement of Account")


# ------------------------------------------------------------------ scans / degradation
def pdf_to_png(pdf_bytes: bytes, dpi: int = 150, page: int = 0) -> bytes:
    import pymupdf as fitz
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        return doc[page].get_pixmap(dpi=dpi).tobytes("png")


def degrade_png(png: bytes, level: str = "good", seed: int = 0) -> bytes:
    """Simulate a scan. level: good (mild noise/skew) | poor (heavy blur, noise, rotation, low contrast)."""
    import numpy as np
    rng = np.random.default_rng(seed)
    img = Image.open(io.BytesIO(png)).convert("L")
    if level == "good":
        img = img.rotate(0.6, expand=True, fillcolor=255).filter(ImageFilter.GaussianBlur(0.4))
        arr = np.array(img, dtype=np.int16) + rng.normal(0, 6, np.array(img).shape).astype(np.int16)
    else:  # tuned empirically to give OCR confidence ~0.6 while text stays partly readable
        img = img.resize((int(img.width * 0.7), int(img.height * 0.7)), Image.BILINEAR)
        img = img.rotate(2.0, expand=True, fillcolor=255).filter(ImageFilter.GaussianBlur(1.0))
        arr = np.array(img, dtype=np.float32) * 0.75 + 255 * 0.25 * 0.5
        arr = arr + rng.normal(0, 14, arr.shape)
    out = Image.fromarray(np.clip(arr, 0, 255).astype("uint8"))
    buf = io.BytesIO()
    out.save(buf, "PNG")
    return buf.getvalue()


def corrupt_pdf(pdf_bytes: bytes) -> bytes:
    """Truncate to simulate a damaged upload (keeps the %PDF header so it passes the magic-byte check)."""
    return pdf_bytes[: max(80, len(pdf_bytes) // 5)]
