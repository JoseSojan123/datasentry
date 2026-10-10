# Sample data (synthetic)

Every file in this folder is **synthetic**. The files were generated from fixed seeds by
`backend/datasentry_core/synthetic.py`. They contain no real customers, transactions or people. The email
addresses use the reserved `example.com` domain.

To regenerate the files with timestamps anchored to the current time, so that freshness rules pass when you upload
them:

```bash
python scripts/generate_sample_data.py
```

The committed copies are anchored to `2026-01-15T12:00:00` (`--as-of 2026-01-15T12:00:00`), so a freshness rule will
flag them as stale.

| File | What it is |
|---|---|
| `transactions_baseline.csv` | A healthy batch. Upload it first to become the reference. |
| `transactions_healthy.csv` | A new batch from the same process, with nothing injected (the control). |
| `transactions_missing_spike.csv` | 30% of `segment` is blank. |
| `transactions_schema_change.csv` | `amount` is renamed to `transaction_amount` and `channel` is removed. |
| `transactions_duplicates.csv` | 8% of rows are exact duplicates. |
| `transactions_unexpected_categories.csv` | 10% of `currency` is JPY or the invalid code XXX. |
| `transactions_numeric_drift.csv` | `amount` is scaled by 1.6 and shifted by +15. |
| `transactions_stale_ingestion.csv` | The newest record is 5 days old. |
| `transactions_category_shift.csv` | The `channel` mix moves from web-heavy to mobile-heavy. |
| `credit_reference.csv` | Loan applications with a `defaulted` label, for the model reference window. |
| `credit_shifted.csv` | The same process with shifted inputs, which produces input drift. |

`manifest.json` lists each file with its row count and the defect that was injected.

To try it, create a dataset in the UI with `transactions_baseline.csv`, then upload one of the other transaction
files as a new version.
