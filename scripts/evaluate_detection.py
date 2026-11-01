#!/usr/bin/env python
"""Compare what the rule engine flagged against the injected (synthetic) scenarios, and compare anomaly detectors.

Results describe behaviour on SYNTHETIC data only. They are not evidence of real-world accuracy.
Usage: python scripts/evaluate_detection.py [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    args = ap.parse_args()
    import pandas as pd
    from sqlalchemy import select
    from app import database
    from app.models import Application, ExceptionRecord, TransactionRecord
    from app.services.anomaly_detection import compare_detectors, score_transactions

    manifest = json.loads((ROOT / "data" / "demo_manifest.json").read_text())["applications"]
    exp = {m["application_id"]: set(m["expected_rules"]) for m in manifest}
    with database.SessionLocal() as db:
        apps = {a.id: a for a in db.scalars(select(Application))}
        found: dict[str, set[str]] = defaultdict(set)
        for e in db.scalars(select(ExceptionRecord)):  # includes resolved ones: detection, not workflow
            found[e.application_id].add(e.rule_id)
        per: dict[str, dict] = defaultdict(lambda: {"n": 0, "hit": 0, "extra": defaultdict(int)})
        for aid, a in apps.items():
            sc = a.scenario_label
            e, f = exp.get(aid, set()), found.get(aid, set())
            per[sc]["n"] += 1
            per[sc]["hit"] += int(e <= f) if e else int(not (f & {"R002"}) if sc == "name_typo" else not f)
            for r in f - e:
                per[sc]["extra"][r] += 1
        clean = [a for a in apps.values() if a.scenario_label == "clean"]
        fp = sum(1 for a in clean if found.get(a.id))
        # anomaly detector comparison on labelled transactions
        # Collective anomalies (credit spike, burst) are made of individually ordinary transactions and are detected at the
        # account level (see the scenario table). Transaction-level scoring is therefore evaluated on point anomalies only.
        collective = {a.id for a in apps.values() if a.scenario_label in ("anomalous_credit_spike", "anomalous_burst")}
        rows = [{"app": t.application_id, "date": t.txn_date, "description": t.description, "credit": t.credit, "debit": t.debit,
                 "label": bool(t.injected_label)} for t in db.scalars(select(TransactionRecord)) if t.application_id not in collective]
    df = pd.DataFrame(rows)
    scored_parts = []
    for aid, g in df.groupby("app"):
        s = score_transactions(g.reset_index(drop=True)[["date", "description", "credit", "debit"]], apps[aid].declared_monthly_income)
        s["label"] = g["label"].to_numpy()
        scored_parts.append(s)
    scored = pd.concat(scored_parts, ignore_index=True)
    det = compare_detectors(scored, scored["label"])

    print("\nScenario detection (expected rule(s) raised / app count):")
    result = {}
    for sc, v in sorted(per.items()):
        extra = ", ".join(f"{r}x{n}" for r, n in sorted(v["extra"].items()))
        print(f"  {sc:26s} {v['hit']:>3}/{v['n']:<3} extra rules: {extra or '-'}")
        result[sc] = {"hit": v["hit"], "n": v["n"], "extra_rules": dict(v["extra"])}
    print(f"\nClean applications with any exception: {fp}/{len(clean)}")
    print("\nTransaction-level detectors vs injected point anomalies (large one-off credit; collective scenarios excluded):")
    for k, m in det.items():
        print(f"  {k:26s} precision {m['precision']:.2f}  recall {m['recall']:.2f}  flagged {m['flagged']}  (tp {m['tp']}, fp {m['fp']}, fn {m['fn']})")
    if args.json:
        Path(args.json).write_text(json.dumps({"scenarios": result, "clean_false_positive_apps": fp, "clean_total": len(clean), "detectors": det}, indent=2))


if __name__ == "__main__":
    main()
