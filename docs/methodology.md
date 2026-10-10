# Methodology

This page explains how DataSentry turns a dataset version or a model window into findings, incidents and
remediation decisions. All defaults below come from the code (`backend/datasentry_core/`). Most of them can be
changed per dataset or per evaluation, and every result stores the configuration it was computed with.

The thresholds are conventional rules of thumb. They are not universal truths, and the [benchmark](benchmark.md)
shows where they stop detecting small changes.

## Contents

- [Pipeline](#pipeline)
- [Ingestion](#ingestion)
- [Profiling](#profiling)
- [Quality rules](#quality-rules)
- [Schema and version comparison](#schema-and-version-comparison)
- [Drift detection](#drift-detection)
- [Model monitoring](#model-monitoring)
- [Lineage and impact](#lineage-and-impact)
- [Incident priority](#incident-priority)
- [Incidents: deduplication and reopening](#incidents-deduplication-and-reopening)
- [Remediation and verification](#remediation-and-verification)
- [Known limitations](#known-limitations)

## Pipeline

Every new version of a dataset goes through the same pipeline. It runs from the API, the scheduler, the SDK and
the offline benchmark, all through the same function (`datasentry_core.monitor.run_monitoring`):

1. **Ingest:** parse the file, infer the schema and normalise the types.
2. **Profile:** compute per-column statistics.
3. **Validate:** run the dataset's enabled quality rules.
4. **Compare:** produce a schema and profile diff against the dataset's reference version.
5. **Drift:** run statistical tests, feature by feature, against the reference version.
6. **Findings:** merge every failing rule, schema change and drifted feature into one list.
   - Rules always produce findings.
   - Drift and missingness findings appear only when they reach the configured severity.
7. **Incident:** open, update or reopen an incident, score its priority, and propose remediations.

The **reference version** is the first version that ingests without critical findings, unless a user picks a
different one.

The **validation gate** applies when a dataset is in `block` mode. A version with critical findings is then held
back as `pending`, and consumers stay on the current version until someone promotes or rejects it. In the default
`warn` mode, the new version becomes active and the incident records the problem.

## Ingestion

- CSV is read with DuckDB.
  - Every field is read as text first, so the type decision belongs to DataSentry and not to the parser.
  - Malformed rows, such as a wrong field count or bad quoting, are skipped and counted, and the version
    reports how many there were.
  - Accepted encodings are UTF-8 and Latin-1.
- Parquet is read through DuckDB.
- DuckDB runs in memory, reads only server-side storage paths, and has extension autoloading turned off.
- Column names are validated: they must be non-empty and unique, with a length limit.
- Type inference assigns each column a semantic type:
  - `numeric`
  - `categorical`
  - `datetime`
  - `boolean`
  - `text`

  You can override these per dataset.
- Uploads are limited by `MAX_UPLOAD_MB` and `MAX_ROWS`.

## Profiling

| Statistic | Definition |
|---|---|
| Missing | Null or NaN after ingestion. Blank CSV fields become null. |
| Outliers | Tukey's fences: below Q1 − k·IQR or above Q3 + k·IQR, with **k = 1.5**. Quartiles use linear interpolation. |
| Duplicate rows | `n_rows − n_distinct_rows` across all columns. Duplicate keys use the same rule over the primary-key columns. |
| Rare categories | Relative frequency among non-null values below **1%**. |
| Datetime gaps | The expected interval is the median gap between consecutive distinct timestamps. A gap is any difference larger than **1.5×** that interval. |
| Freshness | `as_of − max(timestamp)` of the freshness column, or of the first datetime column when no freshness column is set. |

Profiles are deterministic for a given input and `as_of`.

## Quality rules

DataSentry has 11 rule types:

- `not_null`
- `unique`
- `allowed_values`
- `range`
- `regex`
- `referential_integrity`
- `freshness`
- `row_count`
- `duplicate_rows`
- `schema`
- `expectation`

Each rule has a severity (`info`, `warning` or `critical`). Row-level rules also take an optional
`max_failure_pct` tolerance: the rule fails only when the share of failing rows is above it. A rule result records:

- the rows evaluated
- the failing rows and their percentage
- what was observed and what was expected
- up to 5 sample failing rows (values truncated to 80 characters)
- a plain-language explanation

User input never executes as code.

- **`expectation` rules** use a small declarative condition language, validated with Pydantic:
  - comparisons against a value or another column (`eq`, `ne`, `lt`, `le`, `gt`, `ge`)
  - `in` and `not_in`
  - `is_null` and `not_null`
  - `matches`
  - nesting with `all`, `any` and `not`, up to 20 conditions per group

  There is no `eval`, no pandas `query`, and no SQL built from user input.
- **Regular expressions** are limited to 300 characters. Patterns are rejected when they contain:
  - nested quantifiers, such as `(a+)+`
  - quantified alternations, such as `(a|aa)+`
  - backreferences

  Values are truncated to 1,000 characters before matching.

## Schema and version comparison

The comparison between two versions reports typed changes, each with a severity. A dataset can override the
severity of any change kind.

| Change | Default severity | Trigger |
|---|---|---|
| `column_removed`, `type_changed` | critical | |
| `column_renamed` (confirmed), `rename_candidate` | warning | |
| `column_added`, `category_removed` | info | |
| `null_pct_increase` | warning | Missing share rises by ≥ 5 percentage points |
| `null_pct_increase_large` | critical | Missing share rises by ≥ 20 percentage points |
| `category_added` | warning | |
| `row_count_change` | warning | Row count changes by ≥ 30% |
| `duplicate_increase` | warning | Duplicate share rises by ≥ 1 percentage point |

**Renames are never applied automatically.** When a column is removed and another of the same semantic type is
added, the pair is scored:

```
confidence = 0.35 × name similarity      (difflib ratio on normalised names)
           + 0.50 × profile similarity   (mean/std or category overlap, plus missingness)
           + 0.15 × position proximity
```

- Pairs at or above 0.5 are shown as candidates.
- A candidate is marked *ambiguous* when another pairing scores within 0.1 of it.
- A user must confirm or reject each candidate. A confirmed rename is then treated as a rename in later comparisons
  instead of a removal plus an addition. Stored data is never rewritten.

## Drift detection

Drift compares the current version with the reference, feature by feature, keeping two questions separate:

- **Is the change large?** This is measured by an effect size.
- **Is it real?** This is answered by a hypothesis test, corrected across all features in the evaluation.

| Feature type | Effect size (warning / critical) | Test |
|---|---|---|
| Numeric | PSI on 10 quantile bins of the reference (0.1 / 0.25) | Two-sample Kolmogorov–Smirnov |
| Categorical / boolean | Jensen–Shannon distance, base 2 (0.1 / 0.2) | Chi-square test of homogeneity |

**PSI** is `Σ (cur − ref) · ln(cur / ref)` over bins.

- Bin edges are the reference quantiles, with duplicate edges removed for tied or constant data.
- Each bin count gets **+0.5 additive smoothing**, so an empty bin never produces an infinite value.

**Chi-square** follows Cochran's rule.

- Categories with an expected count below 5 are pooled into one bucket.
- If that bucket is still too small, its rows are left out.
- The test runs only when, after pooling, there are at least 2 categories, every expected count is at least 1, and
  at least 80% of expected counts are 5 or more. Otherwise the result is marked *not applicable* and the reason is
  recorded.

**Multiple testing.** P-values are adjusted across all the features in one evaluation with Benjamini–Hochberg (the
default), Bonferroni, or no correction. α is 0.05.

**Status rules:**

| Effect ≥ warning | Corrected test significant | Status |
|---|---|---|
| yes | yes | `drift`, with the effect-size severity |
| yes | no | `inconclusive`, with severity `info`. This usually means the sample is small. |
| no | yes | `no_drift`, with an `info` note. With large samples, trivial differences become significant. |
| no | no | `no_drift` |
| yes | test not applicable | `drift` only if the effect is critical, otherwise `inconclusive` |

There are some additional checks:

- **Sample size:** a feature with fewer than **30** non-null values on either side is reported as
  `insufficient_data`.
- **Missingness:** an increase of ≥ 5 percentage points is a warning, and ≥ 20 is critical. A two-proportion
  z-test p-value is reported alongside.
- **Cardinality:** a change of ±50% or more in the number of distinct values is a warning.
- **Type changes:** a feature whose type changed is flagged critical and not compared, because a distribution
  comparison would not be meaningful.

Each feature result stores:

- the statistics
- both p-values (raw and adjusted)
- the bins
- histograms or category shares for the UI
- a one-sentence explanation

## Model monitoring

DataSentry reports input drift, prediction drift and performance separately. **Drift alone never implies that
accuracy has dropped.** Only labelled predictions can show that, so label coverage is always reported.

### Feature logging

Feature logging is set per model version:

- `none` keeps only predictions and labels, so input drift can't be monitored.
- `aggregate` is the default. Raw features are discarded after the per-batch histograms on the reference bins are
  updated. That is enough for PSI, JS and chi-square.
- `full` stores the raw features, subject to the retention period (90 days by default).

### Delayed labels

Labels can arrive at any time after the prediction they belong to. Metrics are computed only on the predictions
that have labels.

### Metrics

- **Classification:**
  - accuracy
  - precision
  - recall
  - F1
  - confusion matrix
  - ROC-AUC, which is computed only for binary problems where scores were logged and both classes are present
- **Regression:**
  - MAE
  - RMSE
  - R², which needs at least two labelled points and targets that are not constant

### Degradation

DataSentry compares the primary metric (F1, or RMSE for regression) with the registered baseline, using a
**95% bootstrap interval** (300 resamples, fixed seed).

- The degradation is relative.
  - **Warning:** 5% worse.
  - **Critical:** 10% worse.
- It is reported as `degraded` only when the whole interval is past the threshold.
- A worse point estimate whose interval still includes acceptable values is reported as `inconclusive`.

### Windows

By default, the current window is the last 24 hours of predictions and the reference window is everything before
it.

## Lineage and impact

Nodes can be datasets, transformations, feature tables, models, reports or consumers. Every edge carries a
provenance:

- `confirmed`: observed by the platform. For example, a model version registered against its reference dataset,
  or an SDK call that reported a read or write.
- `declared`: entered by a user.
- `inferred`: suggested by a heuristic and not yet confirmed.

**Impact** is a breadth-first traversal downstream from the failing node.

- A downstream node is a *confirmed* impact only if some path to it uses confirmed edges only.
- Every other reachable node is a *potential* impact.
- The investigation view shows one shortest path to each node and how deep it is.

DataSentry rejects edges that would create a cycle. It also reports dangling edges, nodes with no inputs, and
isolated nodes.

**No money figures are invented.** An incident shows a cost only when a user has entered an hourly cost on a
consumer node, and then it is labelled as a user-configured assumption. Otherwise the UI says that no monetary
estimate is available.

## Incident priority

The score runs from 0 to 100. It is a transparent weighted sum, and every component is stored with the incident and
shown in the UI.

| Component | Points |
|---|---|
| Severity | info 10, warning 25, critical 40 |
| Source criticality | low 0, medium 5, high 10, critical 15 |
| Downstream reach | Σ over affected nodes of `criticality weight × provenance factor × 3 / depth`, capped at 30. The criticality weight is low 0.5, medium 1, high 2, critical 3. The provenance factor is 1.0 for confirmed and 0.5 for potential. |
| Models and reports affected | +5 for each affected model, report or consumer, capped at 15 |

The score maps to an urgency: **P1** at 70 or above, **P2** at 45 or above, **P3** at 25 or above, and **P4**
below that. These weights are a starting point (`weighted-sum v1`) and have not been fitted to outcome data.

## Incidents: deduplication and reopening

Each incident has a fingerprint, built from its scope (the dataset or model) and the set of `source:kind:column`
keys of its findings.

- **Same findings while the incident is still active:** they are added to it. The occurrence count goes up, and a
  `recurred` event is logged instead of a new alert.
- **Same findings within 7 days of a resolution:** the incident is **reopened** instead of a new one being created.
- **Allowed status changes:**
  - `open` can move to `acknowledged`, `investigating` or `resolved`.
  - `resolved` can move to `reopened`.
- **Manual resolution:** this needs a note of at least 5 characters, and the incident is labelled as resolved
  manually.

## Remediation and verification

**Execution modes:**

- `recommend` never executes anything.
- `approval` executes only after a human approves. This is the default.
- `auto` executes immediately, but only for actions that are on the workspace allowlist and rated low risk.

**Catalog:**

| Action | Risk | Changes data? |
|---|---|---|
| Quarantine failing version | low | No. It moves the active-version pointer. |
| Reject schema-breaking update | low | No |
| Re-run validation | low | No |
| Re-run profiling | low | No |
| Retry ingestion | low | No |
| Restore last known good version | medium | No. It moves the active-version pointer. |
| Apply configured type conversion | medium | Yes. It writes a new derived version. |
| Apply configured missing-value policy | medium | Yes. It writes a new derived version. |
| Notify an operator | low | No |

**Safety rules:**

- **No action deletes or overwrites stored data.** Original files are always kept.
- **Preconditions are checked again just before execution.**
  - If any blocking precondition fails, the action is refused.
  - For example, a missing-value fill that would change more than 20% of rows is refused.
- **Each proposal can be attempted at most 3 times.**
- **After an action runs, the originally failing checks run again.**
  - For data changes, they run on the new derived version.
  - For pointer moves, they run on the new active version.
- **An incident is marked resolved by remediation only when every finding that opened it has cleared on the active
  version.**
  - The resolution type is then `verified`, and the incident records the execution and version it was checked on.
  - If verification fails, the derived version is rejected and the incident stays open.
- **Quarantine contains the problem but does not fix the data.** The incident message says that the quarantined
  batch still contains the defects.

## Known limitations

- The thresholds are conventional defaults, not calibrated for your data. The [benchmark](benchmark.md) shows, on
  synthetic data, the effect sizes below which the defaults do not alert.
- PSI depends on how the bins are chosen. Very heavy-tailed or highly discrete numeric features can need more or
  fewer bins.
- KS and chi-square assume independent samples. Time-correlated batches can make the p-values too small.
  Effect-size gating limits the impact of this, but does not remove it.
- Benjamini–Hochberg controls the false discovery rate within one evaluation, not across evaluations over time.
- Inferred lineage is only as good as what users and SDK calls report, and DataSentry does not parse SQL.
- The bootstrap intervals for model metrics assume that labelled predictions are representative of all predictions.
  If labels arrive selectively, for example only for defaults, the metrics are biased.
