"""Keyword + filename document classifier (deterministic, explainable).

Returns the category, a confidence and the signals that fired. Low confidence => manual review.
A recognised category does NOT mean the document is genuine.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.config import get_settings
from app.models import DocCategory

# (regex, weight). Weights are heuristic; they were tuned only on the synthetic templates.
KEYWORDS: dict[DocCategory, list[tuple[str, float]]] = {
    DocCategory.PAN: [(r"permanent\s+account\s+number", 5), (r"income\s+tax\s+department", 3),
                      (r"\bpan\s+card\b", 3), (r"\b[A-Z]{5}\d{4}[A-Z]\b", 1.0)],
    DocCategory.AADHAAR: [(r"\baadh?aa?r\b", 5), (r"unique\s+identification", 3), (r"\buidai\b", 3),
                          (r"\bX{4}\s?X{4}\s?\d{4}\b", 3), (r"\benrolment\b", 1)],
    DocCategory.BANK_STATEMENT: [(r"statement\s+of\s+account", 5), (r"account\s+(number|no)", 2),
                                 (r"closing\s+balance", 3), (r"\bdebit\b", 1), (r"\bcredit\b", 1),
                                 (r"\bifsc\b", 1.5), (r"opening\s+balance", 2), (r"statement\s+period", 2)],
    DocCategory.SALARY_SLIP: [(r"(salary|pay)\s*slip", 5), (r"gross\s+(salary|pay|earnings)", 3),
                              (r"net\s+(salary|pay)", 3), (r"\bdeductions?\b", 2), (r"\bemployee\b", 1.5),
                              (r"pay\s+period", 2)],
    DocCategory.ITR: [(r"income\s+tax\s+return", 4), (r"\bitr[\s\-]?v?\b", 3), (r"assessment\s+year", 4),
                      (r"acknowledg(e)?ment\s+(number|no)", 3), (r"total\s+income", 2)],
    DocCategory.GST_CERTIFICATE: [(r"\bgstin\b", 4), (r"goods\s+and\s+services\s+tax", 4),
                                  (r"registration\s+certificate", 3), (r"\bgst\b", 2),
                                  (r"legal\s+name", 1.5), (r"trade\s+name", 1.5)],
    DocCategory.BUSINESS_REGISTRATION: [(r"certificate\s+of\s+incorporation", 5), (r"\budyam\b", 5),
                                        (r"registrar\s+of\s+companies", 3), (r"ministry\s+of\s+corporate", 3),
                                        (r"\bcin\b", 3), (r"partnership\s+deed", 3),
                                        (r"shop\s+(and|&)\s+establishment", 4), (r"registration\s+(number|no)", 1)],
    DocCategory.LOAN_APPLICATION: [(r"loan\s+application", 5), (r"\bapplicant\b", 2), (r"loan\s+amount", 3),
                                   (r"\btenure\b", 2), (r"purpose\s+of\s+(the\s+)?loan", 3)],
}
FILENAME_HINTS: dict[DocCategory, str] = {
    DocCategory.PAN: r"\bpan\b|pan[_\-\s]?card",
    DocCategory.AADHAAR: r"aadh?aa?r",
    DocCategory.BANK_STATEMENT: r"bank|statement",
    DocCategory.SALARY_SLIP: r"salary|payslip|pay[_\-\s]?slip",
    DocCategory.ITR: r"\bitr\b|income[_\-\s]?tax",
    DocCategory.GST_CERTIFICATE: r"\bgst",
    DocCategory.BUSINESS_REGISTRATION: r"incorporation|udyam|registration|business",
    DocCategory.LOAN_APPLICATION: r"application|loan[_\-\s]?form",
}
FULL_SCORE = 8.0
FILENAME_BONUS = 2.0


@dataclass
class ClassificationResult:
    category: DocCategory
    confidence: float
    needs_manual_review: bool
    scores: dict[str, float] = field(default_factory=dict)
    signals: list[str] = field(default_factory=list)


def classify(text: str, filename: str | None = None) -> ClassificationResult:
    scores: dict[DocCategory, float] = {}
    signals: dict[DocCategory, list[str]] = {}
    sample = text or ""
    for cat, kws in KEYWORDS.items():
        total, hits = 0.0, []
        for pattern, weight in kws:
            flags = 0 if pattern.startswith(r"\b[A-Z]{5}") else re.IGNORECASE
            if re.search(pattern, sample, flags):
                total += weight
                hits.append(pattern)
        scores[cat], signals[cat] = total, hits
    name = (filename or "").lower()
    for cat, pat in FILENAME_HINTS.items():
        if name and re.search(pat, name):
            scores[cat] += FILENAME_BONUS
            signals[cat].append(f"filename:{pat}")
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    (best_cat, best), (_, second) = ranked[0], ranked[1]
    min_conf = get_settings().classification_min_confidence
    if best <= 0:
        return ClassificationResult(DocCategory.UNKNOWN, 0.0, True, {c.value: s for c, s in scores.items()}, [])
    margin = (best - second) / best
    confidence = round(min(1.0, best / FULL_SCORE) * (0.5 + 0.5 * margin), 4)
    low = confidence < min_conf
    return ClassificationResult(DocCategory.UNKNOWN if low else best_cat, confidence, low,
                                {c.value: round(s, 2) for c, s in scores.items()}, signals[best_cat])
