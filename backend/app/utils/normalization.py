"""Field normalisation and comparison helpers (names, addresses, amounts, dates, identifiers).

Comparisons are deliberately NOT plain string equality:
* names: case/punctuation/title-insensitive, token-order-insensitive, initial-aware, fuzzy scoring
* addresses: abbreviation-normalised token overlap + fuzzy ratio, ignoring formatting noise
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime

from rapidfuzz import fuzz
from rapidfuzz.distance import JaroWinkler

_TITLES = {"mr", "mrs", "ms", "miss", "shri", "shrimati", "smt", "sri", "dr", "prof", "mx", "m/s", "ms."}
_NAME_SUFFIX = {"jr", "sr"}


def _ascii(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")


def normalize_name(name: str | None) -> str:
    """Lower-case, strip titles/punctuation, collapse whitespace. '' for empty input."""
    if not name:
        return ""
    s = _ascii(name).lower()
    s = re.sub(r"[^a-z\s]", " ", s)
    toks = [t for t in s.split() if t not in _TITLES and t not in _NAME_SUFFIX]
    return " ".join(toks)


def _initial_aware_match(a: list[str], b: list[str]) -> bool:
    """True if one name is the other abbreviated with initials, e.g. 'r k sharma' ~ 'rahul kumar sharma'."""
    if len(a) != len(b):
        return False
    return all(x == y or (len(x) == 1 and y.startswith(x)) or (len(y) == 1 and x.startswith(y)) for x, y in zip(a, b))


def name_similarity(a: str | None, b: str | None) -> float:
    """Similarity in [0,1]. Order-insensitive; initials treated as matches; fuzzy for typos."""
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ta, tb = na.split(), nb.split()
    if sorted(ta) == sorted(tb):
        return 0.99
    if _initial_aware_match(ta, tb) or _initial_aware_match(sorted(ta), sorted(tb)):
        return 0.95
    token_sort = fuzz.token_sort_ratio(na, nb) / 100
    jw = JaroWinkler.normalized_similarity(" ".join(sorted(ta)), " ".join(sorted(tb)))
    # a missing/extra middle name should not look like a different person
    token_set = fuzz.token_set_ratio(na, nb) / 100
    return round(max(token_sort, jw * 0.98, token_set * 0.9), 4)


_ADDR_ABBR = {
    "road": "rd", "street": "st", "avenue": "ave", "apartment": "apt", "apartments": "apt", "flat": "flat",
    "near": "nr", "opposite": "opp", "building": "bldg", "floor": "fl", "nagar": "nagar", "sector": "sec",
    "no": "", "number": "", "cross": "cross", "main": "main", "layout": "lyt", "colony": "col",
    "society": "soc", "behind": "bhd", "block": "blk", "phase": "ph",
}
_ADDR_STOP = {"the", "of", "and", "at", "in", "india", "ind"}


def normalize_address(addr: str | None) -> str:
    if not addr:
        return ""
    s = _ascii(addr).lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    toks = []
    for t in s.split():
        if t in _ADDR_STOP:
            continue
        t = _ADDR_ABBR.get(t, t)
        if t:
            toks.append(t)
    return " ".join(toks)


def extract_pincode(addr: str | None) -> str | None:
    m = re.search(r"\b(\d{6})\b", addr or "")
    return m.group(1) if m else None


def address_similarity(a: str | None, b: str | None) -> float:
    """Similarity in [0,1]; pincode disagreement caps the score (material difference)."""
    na, nb = normalize_address(a), normalize_address(b)
    if not na or not nb:
        return 0.0
    ta, tb = set(na.split()), set(nb.split())
    jacc = len(ta & tb) / len(ta | tb)
    containment = len(ta & tb) / min(len(ta), len(tb))
    score = max(fuzz.token_set_ratio(na, nb) / 100 * 0.9, jacc, containment * 0.9)
    pa, pb = extract_pincode(a), extract_pincode(b)
    if pa and pb and pa != pb:
        score = min(score, 0.5)
    return round(score, 4)


# ------------------------------------------------------------------ amounts / dates
def parse_amount(s: str | float | int | None) -> float | None:
    """'₹ 1,23,456.78', 'Rs. 45000', 'INR 8,40,000/-' -> float. None if unparseable."""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    t = re.sub(r"(?i)\b(rs|inr|rupees)\b\.?|₹|/-", "", str(s))
    t = re.sub(r"(?i)\s*(cr|dr)\.?\s*$", "", t.strip())
    t = t.replace(",", "").strip()
    m = re.fullmatch(r"-?\d+(?:\.\d+)?", t)
    return float(t) if m else None


_DATE_FORMATS = ["%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d %b %Y", "%d %B %Y", "%d-%b-%Y", "%Y-%m-%d",
                 "%d/%m/%y", "%d-%b-%y"]


def parse_date(s: str | None) -> date | None:
    if not s:
        return None
    t = re.sub(r"\s+", " ", str(s).strip().strip(".,"))
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(t, fmt).date()
        except ValueError:
            continue
    return None


def parse_month_year(s: str | None) -> date | None:
    """'September 2026' / 'Sep 2026' / '09/2026' -> first of month."""
    if not s:
        return None
    t = re.sub(r"\s+", " ", str(s).strip())
    for fmt in ("%B %Y", "%b %Y", "%m/%Y", "%b-%Y", "%B-%Y"):
        try:
            return datetime.strptime(t, fmt).date().replace(day=1)
        except ValueError:
            continue
    return None


# ------------------------------------------------------------------ identifiers
PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
_GST_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def is_valid_pan(pan: str | None) -> bool:
    return bool(pan and PAN_RE.match(pan.strip().upper()))


def gstin_checksum_char(first14: str) -> str:
    """Standard GSTIN mod-36 check character (public algorithm)."""
    total = 0
    for i, ch in enumerate(first14):
        v = _GST_CHARS.index(ch) * (1 if i % 2 == 0 else 2)
        total += v // 36 + v % 36
    return _GST_CHARS[(36 - total % 36) % 36]


def is_valid_gstin(g: str | None) -> bool:
    if not g:
        return False
    g = g.strip().upper()
    return bool(GSTIN_RE.match(g)) and gstin_checksum_char(g[:14]) == g[14]


def mask_identifier(value: str | None, keep: int = 4) -> str | None:
    if not value:
        return None
    digits = re.sub(r"\s", "", value)
    return "X" * max(len(digits) - keep, 0) + digits[-keep:]


_FULL_AADHAAR = re.compile(r"\b(\d{4})[ -]?(\d{4})[ -]?(\d{4})\b")


def redact_full_aadhaar(text: str) -> tuple[str, int]:
    """Replace any 12-digit Aadhaar-like number with a masked form BEFORE storage. Returns (text, count)."""
    return _FULL_AADHAAR.subn(lambda m: f"XXXX XXXX {m.group(3)}", text)
