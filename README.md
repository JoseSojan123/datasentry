# DataSentry

**Find bad data, see what it breaks downstream, and prove the fix worked.**

DataSentry is an open-source platform for data quality and ML monitoring. It checks every dataset version and model
window for:

- quality failures
- schema changes
- statistical drift
- model degradation

It ranks each incident by its lineage impact, proposes safe and reversible remediations, and closes an incident only
after verification shows the original checks pass again.

![Incident investigation: impact propagating from a failing dataset through the lineage graph](docs/images/incident-investigation.png)

> This is a portfolio project. Every number in the app is computed from stored records. The demo data is
> **synthetic** and labelled as such. There are no customer testimonials or production metrics here because there
> aren't any.

## Contents

- [What it does](#what-it-does)
- [Architecture](#architecture)
- [Quick start](#quick-start)
- [Development](#development)
- [Testing and benchmark](#testing-and-benchmark)
- [Python SDK](#python-sdk)
- [Deployment](#deployment)
- [Documentation](#documentation)
- [Limitations](#limitations)
- [License](#license)

## What it does

| Area | What you get |
|---|---|
| **Ingestion and profiling** | CSV and Parquet upload (or JSON records through the SDK), type inference, malformed-row reporting. Per-column profiles: missing values, Tukey outliers, duplicates, rare categories, datetime gaps, freshness. |
| **Quality rules** | 11 rule types: not null, unique, allowed values, range, regex, referential integrity, freshness, row count, duplicate rows, schema contract, declarative expectations. Each has a severity and tolerance, and each result comes with observed values, expected values and sample failures. |
| **Schema diff** | Typed changes between versions, each with a configurable severity. Possible renames are scored, but a user must confirm them; they are never applied automatically. |
| **Drift** | PSI or Jensen–Shannon effect sizes, gated by KS or chi-square tests with Benjamini–Hochberg correction. A feature is reported as drifted only when the change is both large and significant. Small samples are reported as `inconclusive`. |
| **Model monitoring** | Model registry, prediction logging with privacy-aware feature retention, delayed labels, and windowed metrics with bootstrap intervals. Input drift, prediction drift and performance are reported separately. |
| **Lineage and impact** | Datasets, transformations, feature tables, models, reports and consumers. Every edge is marked confirmed, declared or inferred. Impact separates confirmed from potential paths. No money figures are invented. |
| **Incidents** | Deduplication, reopening within 7 days, a transparent priority score, assignment, comments and a timeline. |
| **Remediation** | Three modes: recommend, approval and auto (auto only for allowlisted low-risk actions). No action is destructive. Every action is verified before an incident resolves, and failed preconditions are refused. |
| **Operations** | Scheduled jobs with retries, timeouts and overlap protection. In-app notifications, an audit log, API keys and role-based access. |
| **Interface** | 20 pages, a ⌘K command palette, dark and light themes, reduced-motion support, and layouts down to 320 px wide. |

| | |
|---|---|
| ![Overview](docs/images/overview.png) | ![Lineage](docs/images/lineage.png) |
| ![Dataset profile](docs/images/dataset-profile.png) | ![Drift](docs/images/drift.png) |

## Architecture

```mermaid
flowchart LR
    subgraph Clients
        UI["Web app<br/>React · TypeScript · Vite"]
        SDK["Python SDK"]
        CRON["External cron<br/>(optional)"]
    end

    subgraph API["FastAPI service (/api/v1)"]
        AUTH["Auth · RBAC · rate limits"]
        ROUTES["Datasets · Rules · Drift · Models<br/>Lineage · Incidents · Remediation · Jobs"]
        PIPE["Monitoring pipeline"]
    end

    subgraph Core["datasentry_core (pure Python)"]
        IO["Ingestion<br/>DuckDB"]
        PROF["Profiling"]
        RULES["Rule engine"]
        DIFF["Schema diff"]
        DRIFT["Drift tests<br/>SciPy"]
        MM["Model metrics<br/>scikit-learn"]
        LIN["Lineage and impact"]
        REM["Remediation catalog"]
    end

    WORKER["Scheduler worker<br/>python -m app.worker"]
    PG[("PostgreSQL<br/>metadata · results · audit")]
    STORE[("File storage<br/>local volume or Postgres")]

    UI --> AUTH
    SDK --> AUTH
    CRON -->|X-Cron-Secret| ROUTES
    AUTH --> ROUTES --> PIPE
    PIPE --> IO & PROF & RULES & DIFF & DRIFT
    ROUTES --> MM & LIN & REM
    WORKER --> PIPE
    ROUTES --> PG
    WORKER --> PG
    IO --> STORE
```

When a new dataset version arrives, the pipeline runs these steps in order:

1. Ingest
2. Profile
3. Validate
4. Compare with the reference version
5. Detect drift
6. Collect findings
7. Open or update an incident
8. Assess impact and priority
9. Propose remediations
10. Approve and execute a remediation
11. Verify
12. Resolve

The same `run_monitoring` function serves the API, the scheduler, the SDK and the offline benchmark. The
[methodology](docs/methodology.md) explains each step.

### Repository layout

```
backend/
  app/               FastAPI app: API routes, services, DB models, worker, seed CLI
  datasentry_core/   Detection engine (no web or DB dependencies)
  alembic/           Database migrations
  tests/             Unit and integration tests (pytest, real PostgreSQL)
frontend/            React app, unit tests (Vitest), browser tests (Playwright)
sdk/                 Python client with typed results and examples
scripts/             Benchmark, end-to-end scenario, sample data and doc generators
sample_data/         Synthetic CSVs with known injected defects
docs/                Methodology, benchmark, security, deployment, API index, data dictionary
```

## Quick start

You need Docker with Compose v2.

```bash
git clone <this repository> datasentry && cd datasentry
cp .env.example .env     # set SECRET_KEY and POSTGRES_PASSWORD to random values
docker compose up -d --build --wait
```

Open http://localhost:8000 and click **Explore the live demo**. This creates a private workspace with synthetic data
that expires after 24 hours. The workspace includes a P1 incident: open it, approve **Quarantine failing version**,
and click **Run and verify**. The incident resolves only after the original checks pass on the active version, and
the graph changes from *propagating* to *contained*.

To create an admin account with sample data instead:

```bash
SEED_ADMIN_PASSWORD='choose-a-long-password' \
  docker compose --profile seed run --rm seed --email you@example.com --scenarios all
```

## Development

You need Python 3.12, Node 22 and PostgreSQL 16 (or `docker compose up -d db`).

```bash
# Backend
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]" -e "../sdk[dev]"
export DATABASE_URL=postgresql://datasentry:PASSWORD@localhost:5432/datasentry
alembic upgrade head
uvicorn app.main:app --reload             # http://localhost:8000/api/docs

# Frontend (separate shell)
cd frontend
npm ci
npm run dev                               # http://localhost:5173 (proxies /api to :8000)
```

Every setting is an environment variable, documented in [`.env.example`](.env.example).

## Testing and benchmark

| Suite | Command | Result at release |
|---|---|---|
| Backend unit and integration tests (real PostgreSQL) | `cd backend && pytest` | 111 passed |
| SDK tests (in-process API) | `cd sdk && pytest` | 4 passed |
| Lint and types | `ruff check . ../scripts ../sdk && mypy` (in `backend/`) | clean |
| Frontend unit tests, lint, types, build | `cd frontend && npm test && npm run lint && npm run typecheck && npm run build` | 12 passed, clean |
| Browser tests (desktop and Pixel 7) | `cd frontend && E2E_BASE_URL=http://localhost:8000 npx playwright test` | 4 passed |
| API end-to-end scenario | `python scripts/e2e_scenario.py --api http://localhost:8000` | all 7 steps passed |

[GitHub Actions](.github/workflows/ci.yml) runs all of these on every push. The last job builds the Docker image and
runs the scenario and the browser tests against the container.

### Detection benchmark

[`scripts/benchmark.py`](scripts/benchmark.py) runs the monitoring pipeline over seeded synthetic scenarios with known
injected defects. The full results and caveats are in [docs/benchmark.md](docs/benchmark.md). In summary:

- **Seven clear-cut defect types, 30 batches each:**
  - Every defect was detected, and every alert pointed at the injected problem.
  - None of the 30 healthy control batches raised an alert.
  - These are large, deliberately obvious defects. They are not evidence of perfect detection.
- **Smaller defects:** the sensitivity sweep shows where the default thresholds stop alerting.
  - Scaling a lognormal amount by 1.2× is **not** detected. Scaling it by 1.3× is.
  - A 10-point shift in a category's share is caught in only 4 of 20 batches.
- **Model monitoring:** input drift and performance are separate signals. A large input shift did not degrade F1 for
  this model, and a concept change degraded F1 with no input drift at all.
- **Speed:** about 0.56 s for the full pipeline on 100,000 rows, on a 4-vCPU container.

## Python SDK

```python
from datasentry import DataSentry

client = DataSentry(api_url="http://localhost:8000", api_key="dsk_…")
dataset = client.register_dataset(name="orders", data=df)            # pandas DataFrame, CSV path or records
client.add_rule(dataset.id, "not_null", ["order_id"], severity="critical")
version, result = client.create_version(dataset.id, new_df)          # runs the full monitoring pipeline
print(result.status, [f["kind"] for f in result.findings])
```

The SDK also covers models (`register_model`, `log_predictions`, `log_labels`, `evaluate_model`), lineage and
incidents. See [sdk/README.md](sdk/README.md) and [sdk/examples](sdk/examples).

## Deployment

The repository includes:

- a single [Dockerfile](Dockerfile) that serves both the API and the web app
- [docker-compose.yml](docker-compose.yml)
- a [Render Blueprint](render.yaml)

[docs/deployment.md](docs/deployment.md) has the exact manual steps for a free setup, with Render running the app
and Neon providing PostgreSQL. **No public deployment has been made or verified for this release.** After deploying,
run `scripts/e2e_scenario.py` against your URL to check it.

## Documentation

- [Methodology](docs/methodology.md): every statistic, threshold and decision rule
- [Benchmark](docs/benchmark.md): detection results, sensitivity, model monitoring, timing
- [Security](docs/security.md): authentication, isolation, untrusted input, known gaps
- [Deployment](docs/deployment.md): Docker Compose, Render with Neon, other hosts
- [API index](docs/api.md): all 98 operations. The interactive docs are at `/api/docs` on a running server.
- [Data dictionary](docs/data-dictionary.md): all 31 tables, generated from the models
- [Sample data](sample_data/README.md): synthetic CSVs and the defect injected into each

## Limitations

- **Thresholds.** The detection thresholds are conventional defaults, not calibrated to your data. Use the benchmark
  sensitivity tables to judge what they will miss.
- **Scale.** This is a single-node design. Files are processed in memory with pandas and DuckDB, so the upload limit
  defaults to 25 MB and 500,000 rows. Rate limits are kept in memory per process.
- **Lineage.** Lineage comes from user declarations and SDK reports. SQL and pipelines are not parsed automatically.
- **Remediation.** Only a fixed catalog of safe, typed actions is available. There is no user-defined code. It does
  not repair data in upstream source systems.
- **Authentication.** The access token is stored in `localStorage`, and there is no SSO, MFA or password reset by
  email. See [security](docs/security.md#known-limitations).
- **Testing.** The detection results come from synthetic data only. They have not been validated on production
  pipelines.

## License

[MIT](LICENSE)
