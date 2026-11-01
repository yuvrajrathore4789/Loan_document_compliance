"""Statistical anomaly detection on bank-statement transactions.

Detectors (compared side by side):
  * Isolation Forest on scale-free transaction features (unsupervised, per account)
  * Robust z-score (median/MAD) on amounts per direction (credit/debit)
  * A simple rule baseline (amount >> median or >> declared income)
A transaction is ``is_anomalous`` only when Isolation Forest flags it AND there is an interpretable
corroboration (robust z or amount ratio) - this keeps the explanation honest and cuts the
"always flags the top x%" behaviour of contamination-based forests.
Account-level checks cover monthly credit jumps, salary-credit consistency and frequency bursts.
Anomalies are prompts for human review. They are never evidence of fraud.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
from sqlalchemy.orm import Session

from app.database import utcnow
from app.models import Application, ModelRun, TransactionRecord

PARAMS = {"contamination": 0.03, "n_estimators": 200, "random_state": 42, "z_threshold": 3.5,
          "ratio_threshold": 5.0, "min_txns_for_iforest": 30, "monthly_spike_ratio": 2.5, "salary_cv_threshold": 0.25,
          "frequency_ratio": 1.8}


@dataclass
class AnomalyReport:
    n_transactions: int = 0
    n_flagged: int = 0
    method: str = "none"
    account_findings: list[dict] = field(default_factory=list)
    params: dict = field(default_factory=lambda: dict(PARAMS))
    comparison: dict = field(default_factory=dict)


def robust_z(x: np.ndarray, mad_floor: float = 0.0) -> np.ndarray:
    """0.6745*(x-median)/MAD. ``mad_floor`` stops near-constant series (e.g. fixed salary credits)
    from producing absurd z-scores. Falls back to the std when MAD is 0; zeros when no spread."""
    x = np.asarray(x, dtype=float)
    if x.size == 0:
        return x
    med = np.median(x)
    mad = max(np.median(np.abs(x - med)), mad_floor)
    if mad > 0:
        return 0.6745 * (x - med) / mad
    sd = x.std()
    return (x - med) / sd if sd > 0 else np.zeros_like(x)


def _features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["amount"] = np.where(df["credit"] > 0, df["credit"], df["debit"])
    df["is_credit"] = (df["credit"] > 0).astype(int)
    df["month"] = df["date"].str[:7]
    med_by_dir = df.groupby("is_credit")["amount"].transform("median").replace(0, np.nan)
    df["ratio_to_median"] = (df["amount"] / med_by_dir).fillna(1.0)
    df["log_amount"] = np.log1p(df["amount"])
    df["month_count"] = df.groupby("month")["amount"].transform("size")
    df["day"] = pd.to_datetime(df["date"], errors="coerce").dt.day.fillna(15)
    # regular payments (salary, EMI, rent): same description in >=3 months with stable amounts
    desc = df["description"] if "description" in df else pd.Series("", index=df.index)
    df["desc_key"] = desc.fillna("").str.lower().str.replace(r"\d+", "", regex=True).str.strip()
    recurring: set = set()
    for (key, _), g in df.groupby(["desc_key", "is_credit"]):
        if key and g["month"].nunique() >= 3 and g["amount"].mean() > 0 and g["amount"].std(ddof=0) / g["amount"].mean() < 0.2:
            recurring.update(g.index)
    df["recurring"] = df.index.isin(recurring)
    return df


def score_transactions(df: pd.DataFrame, declared_monthly_income: float | None = None, params: dict | None = None) -> pd.DataFrame:
    """Score a transaction frame (columns: date ISO str, credit, debit). Pure function (used by eval script too).

    Adds: if_score (0-1, higher=more unusual), if_flag, robust_z, z_flag, rule_flag, is_anomalous, reasons.
    """
    p = {**PARAMS, **(params or {})}
    if df.empty:
        return df.assign(if_score=[], if_flag=[], robust_z=[], z_flag=[], rule_flag=[], is_anomalous=[], reasons=[])
    f = _features(df)
    z = np.zeros(len(f))
    for _, idx in f.groupby("is_credit").groups.items():
        pos = f.index.get_indexer(idx)
        z[pos] = robust_z(np.log1p(f.loc[idx, "amount"].to_numpy()), mad_floor=0.25)
    f["robust_z"] = z
    f["z_flag"] = (f["robust_z"] >= p["z_threshold"]) & (f["ratio_to_median"] >= 2.0) & ~f["recurring"]
    f["rule_flag"] = f["ratio_to_median"] >= p["ratio_threshold"]
    if declared_monthly_income:
        f["rule_flag"] |= f["credit"] > 3 * declared_monthly_income
    if len(f) >= p["min_txns_for_iforest"]:
        X = StandardScaler().fit_transform(f[["log_amount", "ratio_to_median", "is_credit", "month_count", "day"]])
        iso = IsolationForest(n_estimators=p["n_estimators"], contamination=p["contamination"], random_state=p["random_state"]).fit(X)
        raw = -iso.score_samples(X)
        span = raw.max() - raw.min()
        f["if_score"] = (raw - raw.min()) / span if span > 0 else 0.0
        f["if_flag"] = iso.predict(X) == -1
    else:  # too few rows for a meaningful forest: fall back to |z| as the score
        f["if_score"] = np.clip(np.abs(f["robust_z"]) / 10, 0, 1)
        f["if_flag"] = False
    # a big one-off debit is ordinary spending; only large credits (which could inflate apparent income) pass on ratio alone
    corroborated = (f["robust_z"] >= 3.0) | ((f["ratio_to_median"] >= p["ratio_threshold"]) & (f["is_credit"] == 1))
    f["is_anomalous"] = ((f["if_flag"] & corroborated) | (f["z_flag"] & (f["ratio_to_median"] >= p["ratio_threshold"]))) & ~f["recurring"]
    reasons = []
    for r in f.itertuples():
        rs = []
        direction = "credit" if r.is_credit else "debit"
        if r.ratio_to_median >= 3:
            rs.append(f"{direction} of {r.amount:,.0f} is {r.ratio_to_median:.1f}x the median {direction} ({r.amount / r.ratio_to_median:,.0f})")
        if r.robust_z >= 3.0:
            rs.append(f"robust z-score {r.robust_z:.1f} on log-amount")
        if r.if_flag:
            rs.append(f"Isolation Forest outlier (score {r.if_score:.2f})")
        reasons.append(rs)
    f["reasons"] = reasons
    return f


def account_level_findings(df: pd.DataFrame, declared_monthly_income: float | None, params: dict | None = None) -> list[dict]:
    p = {**PARAMS, **(params or {})}
    out: list[dict] = []
    if df.empty:
        return out
    f = _features(df)
    months = sorted(f["month"].unique())
    if len(months) >= 3:
        credits = f.groupby("month")["credit"].sum().reindex(months)
        med = float(np.median(credits))
        if med > 0:
            for m, v in credits.items():
                if v / med >= p["monthly_spike_ratio"]:
                    out.append({"kind": "monthly_credit_spike", "months": [m], "message":
                                f"Total credits in {m} ({v:,.0f}) are {v / med:.1f}x the median month ({med:,.0f})."})
        counts = f.groupby("month").size().reindex(months)
        mc = float(np.median(counts))
        zc = robust_z(counts.to_numpy())
        for m, c, zz in zip(months, counts, zc):
            if c >= p["frequency_ratio"] * mc and zz >= 3.0:
                out.append({"kind": "transaction_frequency", "months": [m], "message":
                            f"{m} has {int(c)} transactions versus a median of {mc:.0f} (robust z {zz:.1f}): unusual transaction frequency."})
    sal = df[df["is_salary_like"]] if "is_salary_like" in df else df.iloc[0:0]
    if len(sal) >= 3:
        amounts = sal["credit"].to_numpy()
        cv = float(amounts.std() / amounts.mean()) if amounts.mean() else 0
        if cv > p["salary_cv_threshold"]:
            out.append({"kind": "inconsistent_salary", "months": [], "message":
                        f"Salary-like credits vary a lot (coefficient of variation {cv:.2f})."})
        sal_months = set(sal["date"].str[:7])
        missing = [m for m in months if m not in sal_months]
        if missing and len(sal_months) >= len(months) / 2:
            out.append({"kind": "missing_salary_month", "months": missing, "message":
                        f"No salary-like credit in {', '.join(missing)} although other months have one."})
    return out


def analyze_application(db: Session, app: Application, txns: list[TransactionRecord]) -> AnomalyReport:
    """Score the application's transactions, persist scores/reasons, log a model run."""
    started = utcnow()
    rep = AnomalyReport(n_transactions=len(txns))
    if not txns:
        return rep
    df = pd.DataFrame([{"id": t.id, "date": t.txn_date, "description": t.description, "credit": t.credit, "debit": t.debit,
                        "is_salary_like": t.is_salary_like}
                       for t in txns])
    scored = score_transactions(df, app.declared_monthly_income)
    by_id = {t.id: t for t in txns}
    for r in scored.itertuples():
        t = by_id[r.id]
        t.anomaly_score, t.robust_z = round(float(r.if_score), 4), round(float(r.robust_z), 3)
        t.is_anomalous, t.anomaly_reasons = bool(r.is_anomalous), list(r.reasons)
    rep.account_findings = account_level_findings(df, app.declared_monthly_income)
    rep.n_flagged = int(scored["is_anomalous"].sum())
    rep.method = "isolation_forest+robust_z" if len(df) >= PARAMS["min_txns_for_iforest"] else "robust_z_only"
    rep.comparison = {"isolation_forest": int(scored["if_flag"].sum()), "robust_z": int(scored["z_flag"].sum()),
                      "simple_rule": int(scored["rule_flag"].sum()), "combined_flag": rep.n_flagged,
                      "if_and_rule_overlap": int((scored["if_flag"] & scored["rule_flag"]).sum())}
    db.add(ModelRun(run_type="anomaly", model_name="IsolationForest+RobustZ", application_id=app.id, params=PARAMS,
                    metrics={**rep.comparison, "account_findings": len(rep.account_findings)}, n_records=len(df),
                    started_at=started, finished_at=utcnow()))
    db.flush()
    return rep


def compare_detectors(scored: pd.DataFrame, truth: pd.Series) -> dict[str, dict[str, float]]:
    """Precision/recall of each detector against labelled (synthetic) anomalies."""
    out = {}
    for name, col in [("isolation_forest_alone", "if_flag"), ("robust_z_alone", "z_flag"), ("simple_rule", "rule_flag"),
                      ("combined (used in app)", "is_anomalous")]:
        pred, t = scored[col].astype(bool), truth.astype(bool)
        tp = int((pred & t).sum()); fp = int((pred & ~t).sum()); fn = int((~pred & t).sum())
        out[name] = {"precision": tp / (tp + fp) if tp + fp else 0.0, "recall": tp / (tp + fn) if tp + fn else 0.0,
                     "flagged": int(pred.sum()), "tp": tp, "fp": fp, "fn": fn}
    return out
