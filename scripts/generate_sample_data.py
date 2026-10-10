"""Write the SYNTHETIC sample datasets to sample_data/ as CSV files you can upload in the UI.

    python scripts/generate_sample_data.py                 # timestamps anchored to now
    python scripts/generate_sample_data.py --as-of 2026-01-15T12:00:00 --rows 1000

All files are generated from fixed seeds by datasentry_core.synthetic. They contain no real people,
customers or transactions. Timestamps are anchored to --as-of, so with the default (now) freshness
rules pass when you upload right away; the copies committed to the repository will look stale later.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from datasentry_core import synthetic  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate synthetic sample CSVs.")
    ap.add_argument("--out", type=Path, default=ROOT / "sample_data")
    ap.add_argument("--rows", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--as-of", type=datetime.fromisoformat, default=None, help="ISO timestamp; default is now (UTC)")
    args = ap.parse_args()
    as_of = (args.as_of or datetime.now(UTC)).replace(tzinfo=None, microsecond=0)
    args.out.mkdir(parents=True, exist_ok=True)

    manifest = {"label": synthetic.SYNTHETIC_LABEL, "as_of": as_of.isoformat(), "seed": args.seed, "files": []}
    base = None
    for name in synthetic.SCENARIOS:
        sc = synthetic.scenario(name, seed=args.seed, n=args.rows, as_of=as_of)
        if base is None:
            base = sc.baseline
            path = args.out / "transactions_baseline.csv"
            base.to_csv(path, index=False)
            manifest["files"].append({"file": path.name, "role": "baseline", "rows": len(base), "description": "Healthy reference batch."})
        path = args.out / f"transactions_{name}.csv"
        sc.modified.to_csv(path, index=False)
        manifest["files"].append({"file": path.name, "role": "batch", "scenario": name, "rows": len(sc.modified),
                                  "description": sc.description, "injected": sc.injected})

    ref = synthetic.credit_applications(args.rows, seed=args.seed)
    drifted = synthetic.credit_applications(args.rows, seed=args.seed + 1, shift=1.0)
    for df, fname, desc in ((ref, "credit_reference.csv", "Model reference window (labels included)."),
                            (drifted, "credit_shifted.csv", "Applications with shifted inputs (input drift).")):
        df.to_csv(args.out / fname, index=False)
        manifest["files"].append({"file": fname, "role": "model", "rows": len(df), "description": desc})

    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Wrote {len(manifest['files'])} files to {args.out} (as of {as_of.isoformat()}).")


if __name__ == "__main__":
    main()
