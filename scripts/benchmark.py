"""Offline detection benchmark for DataSentry.

Runs the same monitoring pipeline the API uses (``datasentry_core.monitor.run_monitoring``) over
seeded synthetic scenarios with known injected defects, then scores the findings against that
ground truth. Every number in docs/benchmark.md comes from this script; rerun it to reproduce.

    cd backend && python ../scripts/benchmark.py --seeds 30 --out ../docs

Scoring
-------
* An *alert* is a finding with severity ``warning`` or ``critical`` (``info`` findings are shown in
  the UI but never page anyone, so they are excluded).
* A batch is *detected* when at least one alert matches an injected defect.
* An alert *matches* a defect when it is on the injected column (or its renamed successor) or is of
  a kind that only that defect can explain (duplicate rows, schema contract, freshness).
* Recall = detected injected batches / injected batches.
* False-positive rate (FPR) = healthy control batches with any alert / healthy batches.
* Precision = matching alerts / all alerts, over injected batches. An unrelated alert on a
  defective batch lowers precision even though the batch was detected.

The synthetic data is generated, not production data. Results describe how the detectors behave on
these specific, clearly labelled scenarios and should not be read as accuracy on real pipelines.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from datasentry_core import synthetic  # noqa: E402
from datasentry_core.drift import evaluate_drift  # noqa: E402
from datasentry_core.io import infer_schema, normalize_frame  # noqa: E402
from datasentry_core.model_metrics import classification_metrics, compare_performance  # noqa: E402
from datasentry_core.monitor import MonitorInput, run_monitoring  # noqa: E402

ALERT = {"warning", "critical"}

# Kinds of finding that are themselves evidence of a specific defect, whatever column they name.
KIND_MATCHES = {
    "duplicates": {"duplicate_rows", "unique", "duplicate_increase"},
    "schema": {"schema", "column_removed", "column_added", "column_renamed", "rename_candidate"},
    "freshness": {"freshness"},
}
RENAMES = {"amount": "transaction_amount"}


def prepare(df):
    schema = infer_schema(df)
    return MonitorInput(normalize_frame(df, schema), schema)


def matches(finding: dict[str, Any], injected: list[dict[str, Any]]) -> bool:
    cols = {finding.get("column"), *(finding.get("columns") or [])} - {None}
    for inj in injected:
        targets = {inj["column"], RENAMES.get(inj["column"])} - {None}
        if cols & targets:
            return True
        if finding["kind"] in KIND_MATCHES.get(inj["kind"], set()):
            return True
    return False


def run_data(seeds: int, n: int) -> dict[str, Any]:
    per: dict[str, dict[str, Any]] = {}
    for name in synthetic.SCENARIOS:
        detected = alerts = matched = 0
        timings: list[float] = []
        unrelated: dict[str, int] = {}
        for s in range(seeds):
            sc = synthetic.scenario(name, seed=1000 + s * 17, n=n)
            ref, cur = prepare(sc.baseline), prepare(sc.modified)
            t0 = time.perf_counter()
            res = run_monitoring(cur, ref, sc.expected_rules, as_of=synthetic.DEFAULT_AS_OF)
            timings.append((time.perf_counter() - t0) * 1000)
            batch_alerts = [f for f in res.findings if f["severity"] in ALERT]
            alerts += len(batch_alerts)
            hit = [f for f in batch_alerts if sc.injected and matches(f, sc.injected)]
            matched += len(hit)
            detected += bool(hit) if sc.injected else bool(batch_alerts)
            for f in batch_alerts:
                if not (sc.injected and matches(f, sc.injected)):
                    key = f"{f['source']}:{f['kind']}:{f.get('column')}"
                    unrelated[key] = unrelated.get(key, 0) + 1
        per[name] = {
            "batches": seeds,
            "injected": name != "healthy",
            "batches_with_alert" if name == "healthy" else "detected": detected,
            "alerts": alerts,
            "matching_alerts": matched,
            "unrelated_alerts": dict(sorted(unrelated.items(), key=lambda kv: -kv[1])),
            "ms_median": round(statistics.median(timings), 1),
            "ms_p95": round(float(np.percentile(timings, 95)), 1),
        }
    injected = [v for v in per.values() if v["injected"]]
    tot_batches = sum(v["batches"] for v in injected)
    tot_detected = sum(v["detected"] for v in injected)
    tot_alerts = sum(v["alerts"] for v in injected)
    tot_matched = sum(v["matching_alerts"] for v in injected)
    healthy = per["healthy"]
    return {
        "rows_per_batch": n,
        "scenarios": per,
        "overall": {
            "recall": round(tot_detected / tot_batches, 4),
            "precision": round(tot_matched / tot_alerts, 4) if tot_alerts else None,
            "false_positive_rate": round(healthy["batches_with_alert"] / healthy["batches"], 4),
            "injected_batches": tot_batches,
            "healthy_batches": healthy["batches"],
        },
    }


def run_sensitivity(seeds: int, n: int) -> dict[str, Any]:
    """Detection rate as the injected defect gets smaller, to show where the detectors stop seeing it."""
    sweeps: dict[str, list[float]] = {
        "amount_scale": [1.0, 1.05, 1.1, 1.2, 1.3, 1.5],
        "segment_missing_fraction": [0.0, 0.005, 0.01, 0.02, 0.05],
        "mobile_share_shift": [0.0, 0.05, 0.1, 0.15, 0.2, 0.3],
    }
    out: dict[str, Any] = {}
    for sweep, levels in sweeps.items():
        rows = []
        for level in levels:
            hits = 0
            for s in range(seeds):
                seed = 5000 + s * 31
                base = synthetic.transactions(n, seed)
                cur = synthetic.transactions(n, seed + 1000, id_offset=n)
                rng = np.random.default_rng(seed + 3)
                if sweep == "amount_scale":
                    cur["amount"] = np.round(cur["amount"] * level, 2)
                    col = "amount"
                elif sweep == "segment_missing_fraction":
                    idx = rng.choice(n, int(level * n), replace=False)
                    cur.loc[idx, "segment"] = None
                    col = "segment"
                else:
                    p_web, p_mobile = 0.5 - level, 0.4 + level
                    cur["channel"] = rng.choice(synthetic.CHANNELS, n, p=[p_web, p_mobile, 0.1])
                    col = "channel"
                res = run_monitoring(prepare(cur), prepare(base), synthetic.default_rules(), as_of=synthetic.DEFAULT_AS_OF)
                hits += any(f["severity"] in ALERT and f.get("column") == col for f in res.findings)
            rows.append({"level": level, "detection_rate": round(hits / seeds, 4)})
        out[sweep] = rows
    return {"rows_per_batch": n, "batches_per_level": seeds, "sweeps": out}


def run_scaling(sizes: list[int]) -> list[dict[str, Any]]:
    out = []
    for n in sizes:
        sc = synthetic.scenario("numeric_drift", seed=7, n=n)
        ref, cur = prepare(sc.baseline), prepare(sc.modified)
        runs = []
        for _ in range(3):
            t0 = time.perf_counter()
            run_monitoring(cur, ref, sc.expected_rules, as_of=synthetic.DEFAULT_AS_OF)
            runs.append(time.perf_counter() - t0)
        best = min(runs)
        out.append({"rows": n, "seconds_best_of_3": round(best, 3), "rows_per_second": int(n / best)})
    return out


def run_model(seeds: int, n: int) -> dict[str, Any]:
    from sklearn.linear_model import LogisticRegression

    feats = ["income", "debt_ratio", "utilization", "late_payments", "age"]
    cases = {"control": {}, "input_shift": {"shift": 1.0}, "concept_change": {"concept_change": True}}
    results: dict[str, Any] = {k: {"batches": seeds, "input_drift_alert": 0, "performance_degraded": 0,
                                   "performance_inconclusive": 0} for k in cases}
    for s in range(seeds):
        train = synthetic.credit_applications(4000, seed=200 + s)
        holdout = synthetic.credit_applications(n, seed=400 + s)
        clf = LogisticRegression(max_iter=1000).fit(train[feats], train["defaulted"])
        base = classification_metrics(holdout["defaulted"].tolist(), clf.predict(holdout[feats]).tolist(), positive_label=1)
        types = {f: "numeric" for f in feats}
        for case, kw in cases.items():
            cur = synthetic.credit_applications(n, seed=600 + s, **kw)
            drift = evaluate_drift(holdout[feats], cur[feats], types)
            if any(f["status"] == "drift" and f["severity"] in ALERT for f in drift["features"]):
                results[case]["input_drift_alert"] += 1
            cur_m = classification_metrics(cur["defaulted"].tolist(), clf.predict(cur[feats]).tolist(), positive_label=1)
            perf = compare_performance(base, cur_m)
            if perf["status"] == "degraded":
                results[case]["performance_degraded"] += 1
            elif perf["status"] == "inconclusive":
                results[case]["performance_inconclusive"] += 1
    return {"rows_per_window": n, "cases": results}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--seeds", type=int, default=30)
    ap.add_argument("--rows", type=int, default=2000)
    ap.add_argument("--sensitivity-seeds", type=int, default=20)
    ap.add_argument("--model-seeds", type=int, default=20)
    ap.add_argument("--scaling", default="2000,20000,100000")
    ap.add_argument("--out", type=Path, default=None, help="directory for benchmark_results.json")
    args = ap.parse_args()

    started = time.perf_counter()
    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "environment": {"python": platform.python_version(), "machine": platform.machine(),
                        "processor_count": __import__("os").cpu_count()},
        "data": run_data(args.seeds, args.rows),
        "sensitivity": run_sensitivity(args.sensitivity_seeds, args.rows),
        "model": run_model(args.model_seeds, args.rows),
        "scaling": run_scaling([int(x) for x in args.scaling.split(",") if x]),
        "note": "Synthetic, seeded scenarios only; see docs/benchmark.md for how to read these numbers.",
    }
    report["wall_seconds"] = round(time.perf_counter() - started, 1)
    text = json.dumps(report, indent=2)
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "benchmark_results.json").write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
