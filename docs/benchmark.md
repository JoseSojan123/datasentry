# Detection benchmark

Every number on this page comes from [`scripts/benchmark.py`](../scripts/benchmark.py). The raw output is in
[`benchmark_results.json`](benchmark_results.json). To reproduce it:

```bash
cd backend
python ../scripts/benchmark.py --seeds 30 --out ../docs
```

**Read these results with care.**

- The data is synthetic, generated from fixed seeds by `datasentry_core.synthetic`.
- The scenarios are deliberately clear-cut defects.
- The numbers show that the pipeline detects and attributes these specific defects. They do **not** estimate
  accuracy on real pipelines, where defects are subtler and the right thresholds depend on the data.
- The [sensitivity sweep](#sensitivity-where-detection-stops) below shows where the default thresholds stop
  alerting.

Run recorded on 2026-10-10: Python 3.12.3, 4 vCPUs (x86_64), 188 s wall time for the whole script.

## Method

The script runs each scenario 30 times, with a different seed each time.

1. A healthy **baseline** batch is drawn.
2. An independent **current** batch is drawn from the same process, so ordinary sampling noise is present.
3. One defect is injected into the current batch. The control scenario, `healthy`, injects nothing.
4. Both batches go through the same `run_monitoring` function that the API uses, with the scenario's default rules
   and default thresholds.

Each batch has 2,000 rows and 10 columns.

### Scoring

- An **alert** is a finding with severity warning or critical. Info findings are excluded.
- An alert **matches** the defect in either of these cases:
  - It is on the injected column, or on that column's renamed successor.
  - Its kind can only be explained by that defect. For example, a duplicate-rows rule failing in the duplicates
    scenario.
- **Recall** = injected batches with at least one matching alert ÷ injected batches.
- **Precision** = matching alerts ÷ all alerts on injected batches.
- **False-positive rate** = healthy batches with any alert ÷ healthy batches.

## Results: injected defects

| Scenario | Injected defect | Batches | Detected | Alerts | Unrelated alerts | Median ms / batch |
|---|---|---|---|---|---|---|
| healthy (control) | nothing | 30 | 0 alerted | 0 | 0 | 65 |
| missing_spike | 30% of `segment` blanked | 30 | 30 | 60 | 0 | 65 |
| schema_change | `amount` renamed, `channel` dropped | 30 | 30 | 150 | 0 | 56 |
| duplicates | 8% of rows replayed | 30 | 30 | 90 | 0 | 71 |
| unexpected_categories | 10% of `currency` set to JPY or XXX | 30 | 30 | 120 | 0 | 66 |
| numeric_drift | `amount` × 1.6 + 15 | 30 | 30 | 30 | 0 | 66 |
| stale_ingestion | newest record is 5 days old | 30 | 30 | 30 | 0 | 73 |
| category_shift | `channel` mix moves from web-heavy to mobile-heavy | 30 | 30 | 30 | 0 | 67 |

**Overall:**

- **Recall:** 1.00 (210 of 210 injected batches).
- **Precision:** 1.00 (0 unrelated alerts).
- **False-positive rate:** 0.00 (0 of 30 healthy batches alerted).

These are perfect scores on easy, large defects. They show that each detector fires on what it should and stays
quiet on a healthy batch from the same process. They do not show that every defect will be caught. A single defect
often raises several alerts: for example, a schema change trips the schema contract rule, the removal finding and
the rename candidate. That is why there are more alerts than batches.

## Sensitivity: where detection stops

The script repeats the pipeline at decreasing defect sizes, with 20 batches per level. Detection here means at
least one alert on the affected column.

| `amount` multiplied by | 1.00 | 1.05 | 1.10 | 1.20 | 1.30 | 1.50 |
|---|---|---|---|---|---|---|
| detection rate | 0.00 | 0.00 | 0.00 | 0.00 | **1.00** | 1.00 |

| `segment` fraction blanked | 0 | 0.5% | 1% | 2% | 5% |
|---|---|---|---|---|---|
| detection rate | 0.00 | 0.00 | 0.00 | **1.00** | 1.00 |

| `channel` share moved from web to mobile | 0 | 0.05 | 0.10 | 0.15 | 0.20 | 0.30 |
|---|---|---|---|---|---|---|
| detection rate | 0.00 | 0.00 | 0.20 | **1.00** | 1.00 | 1.00 |

How to read the sweep:

- **Scaling `amount` by up to 20% is not flagged.** `amount` is lognormal. In a spot check of 5 seeds, a 1.2× scale gave PSI values
  between 0.05 and just under 0.10, below the 0.1 warning threshold, even though the corrected KS test was
  significant every time. The effect-size gate holds the alert back by design. Lower `psi_warning` for the dataset if changes that small
  matter.
- **Missing values in `segment` alert at 2%** because the default rule has a 1% tolerance. At exactly 1% the rule
  still passes. The drift detector alone would only alert at a 5 percentage point increase.
- **A 10 percentage point mix shift is borderline,** detected in 4 of 20 batches, because the JS distance sits close
  to the 0.1 threshold.

## Model monitoring

A logistic regression is trained on 4,000 synthetic loan applications. Its baseline F1 is measured on a 2,000-row
holdout. The script then scores three kinds of 2,000-row window, 20 times each:

| Window | Input drift alert | Performance `degraded` | Performance `inconclusive` |
|---|---|---|---|
| control (same process) | 0 / 20 | 0 / 20 | 5 / 20 |
| input shift (`shift = 1.0`) | 20 / 20 | 0 / 20 | 0 / 20 |
| concept change (new label relationship) | 0 / 20 | 20 / 20 | 0 / 20 |

How to read this:

- **Input drift and performance are separate questions.** A large input shift was detected every time, but F1 did
  not degrade, because this model still ranks the shifted applicants correctly. A concept change degraded F1 every
  time, and no input drift was seen. This is why DataSentry never reports a performance drop from drift alone.
- **The control windows did not raise a false alarm.** Five of them returned `inconclusive`: the point estimate of
  F1 was more than 5% below baseline, but the 95% bootstrap interval still included acceptable values. In those
  cases nothing alerts, and the UI says the evidence is not yet conclusive.

## Timing

Each figure is the best of 3 runs of the full pipeline on one batch: profile, 10 rules, schema diff, and drift
against a reference of the same size.

| Rows | Seconds | Rows per second |
|---|---|---|
| 2,000 | 0.077 | ≈ 26,000 |
| 20,000 | 0.158 | ≈ 127,000 |
| 100,000 | 0.561 | ≈ 178,000 |

Measured on a 4-vCPU cloud container. Timings exclude file parsing and database writes. Expect different numbers on
other hardware.

## What this benchmark does not cover

- Real-world data, gradual drift over many batches, and seasonal patterns.
- Several defects interacting in one batch.
- Lineage impact accuracy, which depends on how complete the declared lineage is.
- Remediation outcomes. These are covered by tests: the backend integration tests and `scripts/e2e_scenario.py`
  check that incidents resolve only after verification.
