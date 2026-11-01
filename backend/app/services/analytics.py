"""Dashboard analytics: named SQL queries (app/sql/analytics.sql) + overview aggregates."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models import Application, AppStatus, Document, DocStatus, ExceptionRecord, ExcStatus

SQL_FILE = Path(__file__).resolve().parents[1] / "sql" / "analytics.sql"
_cache: dict[str, str] | None = None


def load_queries() -> dict[str, str]:
    global _cache
    if _cache is None:
        queries: dict[str, str] = {}
        name, buf = None, []
        for line in SQL_FILE.read_text(encoding="utf-8").splitlines():
            m = re.match(r"--\s*name:\s*(\w+)", line)
            if m:
                if name:
                    queries[name] = "\n".join(buf).strip().rstrip(";")
                name, buf = m.group(1), []
            elif name and not line.strip().startswith("--"):
                buf.append(line)
        if name:
            queries[name] = "\n".join(buf).strip().rstrip(";")
        _cache = queries
    return _cache


def run_named(db: Session, name: str, params: dict | None = None) -> list[dict]:
    q = load_queries()
    if name not in q:
        raise KeyError(name)
    rows = db.execute(text(q[name]), params or {}).mappings().all()
    out = []
    for r in rows:
        d = {}
        for k, v in r.items():
            d[k] = round(v, 4) if isinstance(v, float) else v
        out.append(d)
    return out


def overview(db: Session) -> dict:
    n_apps = db.scalar(select(func.count(Application.id))) or 0
    n_docs = db.scalar(select(func.count(Document.id))) or 0
    processed = db.scalar(select(func.count(Document.id)).where(Document.processed_at.is_not(None))) or 0
    with_docs = db.scalar(select(func.count(func.distinct(Document.application_id)))) or 0
    verified = db.scalar(select(func.count(Application.id)).where(Application.last_verified_at.is_not(None))) or 0
    open_q = select(func.count(ExceptionRecord.id)).where(ExceptionRecord.status != ExcStatus.RESOLVED.value)
    pending = db.scalar(open_q) or 0
    high_open = db.scalar(open_q.where(ExceptionRecord.severity == "HIGH")) or 0
    resolved = db.scalar(select(func.count(ExceptionRecord.id)).where(ExceptionRecord.status == ExcStatus.RESOLVED.value)) or 0
    avg_proc = db.scalar(select(func.avg(Document.processing_seconds)).where(Document.processing_seconds.is_not(None)))
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=365)
    series: dict[str, int] = {}
    for (created,) in db.execute(select(Application.created_at).where(Application.created_at >= since)):
        key = created.strftime("%Y-%m-%d")
        series[key] = series.get(key, 0) + 1
    status_rows = db.execute(select(Application.status, func.count()).group_by(Application.status)).all()
    return {
        "total_applications": n_apps, "documents_total": n_docs, "documents_processed": processed,
        "verification_completion_rate": round(verified / with_docs, 4) if with_docs else 0.0,
        "pending_reviews": pending, "high_severity_open": high_open, "resolved_exceptions": resolved,
        "avg_processing_seconds": round(avg_proc, 3) if avg_proc is not None else None,
        "applications_over_time": [{"date": k, "applications": v} for k, v in sorted(series.items())],
        "verification_status": [{"status": s, "count": c} for s, c in status_rows],
        "documents_by_type": run_named(db, "documents_processed_by_category"),
    }


def exception_analytics(db: Session) -> dict:
    by_cat = db.execute(select(ExceptionRecord.category, ExceptionRecord.severity, func.count())
                        .group_by(ExceptionRecord.category, ExceptionRecord.severity)).all()
    cat: dict[str, dict] = {}
    for c, s, n in by_cat:
        cat.setdefault(c, {"category": c, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "total": 0})
        cat[c][s] += n
        cat[c]["total"] += n
    return {"by_category": sorted(cat.values(), key=lambda x: -x["total"]),
            "by_rule": run_named(db, "exception_frequency_by_rule"),
            "resolved_vs_unresolved": run_named(db, "resolved_vs_unresolved"),
            "reviewer_workload": run_named(db, "reviewer_workload"),
            "applications_missing_documents": run_named(db, "applications_with_missing_documents"),
            "high_severity_applications": run_named(db, "applications_with_high_severity_exceptions")[:20]}


def document_processing(db: Session) -> dict:
    return {"by_category": run_named(db, "documents_processed_by_category"),
            "processing_time": run_named(db, "average_processing_time"),
            "monthly_verification": run_named(db, "monthly_verification_statistics")}
