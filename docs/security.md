# Security

This page describes how DataSentry protects data, credentials and the server, and what it does not protect against.
Please report a vulnerability privately to the repository owner rather than in a public issue.

## Authentication

- **Passwords** are hashed with scrypt (n = 2¹⁴, r = 8, p = 1) using a 16-byte random salt, and compared in
  constant time.
- **Sessions** use HS256 JWT access tokens.
  - Tokens are signed with `SECRET_KEY` and expire after 12 hours by default (`ACCESS_TOKEN_TTL_MINUTES`).
  - On every request, the user is reloaded from the database. A disabled user, a changed workspace or an expired
    demo workspace is rejected even if the token is still valid.
- **API keys** look like `dsk_<prefix>_<secret>`.
  - Only an HMAC-SHA256 of the key, keyed with `SECRET_KEY`, is stored.
  - The full key is shown once, when it is created.
  - Keys can be revoked and can have an expiry date.
- **Login, registration and the demo endpoint** are rate-limited (20 requests per minute per client by default).

## Authorisation

- **Roles:** there are three.
  - `viewer`: read-only.
  - `editor`: uploads, rules, comments, incident changes, and approving or executing remediation.
  - `admin`: members, API keys, workspace settings and the audit log.
- **Workspace isolation:** every row belongs to a workspace.
  - Lookups go through `owned()`. A record from another workspace returns **404 rather than 403**, so its existence
    is not revealed.
- **Demo workspaces:**
  - Each visitor gets an isolated demo workspace that expires after 24 hours.
  - There is a cap on how many can be active at once (`MAX_DEMO_WORKSPACES`).

## Untrusted input

DataSentry never executes code, SQL or shell commands supplied by users.

| Input | Control |
|---|---|
| Expectation rules | A declarative condition grammar validated by Pydantic. There is no `eval`, `exec`, pandas `query` or SQL text. |
| Regular expressions | Limited to 300 characters. Patterns with nested quantifiers, quantified alternations or backreferences are rejected. Values are truncated to 1,000 characters before matching. |
| Uploaded files | Size limit (`MAX_UPLOAD_MB`, enforced while streaming) and row limit (`MAX_ROWS`). The extension is checked, the filename is sanitised, and files are stored under generated keys. |
| CSV and Parquet parsing | In-memory DuckDB with parameterised paths. Paths are always server-generated, and extension autoinstall and autoload are off. |
| Column names | Must be non-empty and unique (case-insensitive), with no control characters and a bounded length. |
| Remediation | Only actions from a fixed catalog can run, with typed parameters. Preconditions are checked again just before execution, and no action deletes or overwrites stored data. |
| Database | SQLAlchemy ORM with bound parameters. No SQL is built from user strings. |

## Data exposure

- **Errors** use the shape `{error: {code, message, details, request_id}}`.
  - Unhandled exceptions are logged on the server with their request id.
  - The client receives only a generic message. Stack traces, SQL and configuration never reach the client.
- **`/health`** returns only the service status. **`/ready`** reports database reachability, without connection
  details.
- **Model predictions** default to `aggregate` feature logging: raw feature values are discarded after the
  histograms are updated. `full` logging is an explicit opt-in per model version, and it has a retention period.
- **Audit log** entries record actions and entity ids. Registration records only the email domain.
- **Response headers:**
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: DENY`
  - `Referrer-Policy: strict-origin-when-cross-origin`
  - `X-Request-ID`

## Configuration safety

In production (`ENVIRONMENT=production`), the API refuses to start if any of these is true:

- `SECRET_KEY` is still the development default.
- `CORS_ORIGINS` contains `*`.
- `SCHEDULER_MODE=external` and `CRON_SECRET` is shorter than 24 characters.

The external cron endpoint compares `X-Cron-Secret` in constant time.

The repository contains only `.env.example`, with placeholders. `.env` files, uploaded data and local storage are
git-ignored.

## Known limitations

- **The frontend stores the access token in `localStorage`.** A cross-site scripting bug would expose it. React's
  escaping and the absence of `dangerouslySetInnerHTML` reduce this risk, but an HttpOnly cookie session would be
  stronger.
- **Rate limiting is per process,** kept in memory. With several API replicas, each enforces its own window, so a
  global limit would need Redis or a similar shared store.
- **The regex safety checks are heuristics.** They block the classic catastrophic-backtracking shapes. Python's
  `re` module has no match timeout, so an unusual pattern could still be slow, limited only by the 1,000-character
  value cap.
- **There is no multi-factor authentication or SSO,** and no password reset by email.
- **Remediation runs inside the API process** and has a timeout. It is not sandboxed in a separate container,
  which is acceptable only because the catalog contains just fixed, typed operations.

## Review checklist

This is what was checked before release:

- Searched for `eval`, `exec`, `subprocess`, `os.system`, `pickle`, f-string SQL and `shell=True` in the backend.
  None are used on user input.
- Confirmed that error responses carry no stack traces. `scripts/e2e_scenario.py` checks this against a running
  API.
- Searched the repository for committed secrets. Only placeholder values and test fixtures were found.
- Ran `ruff` and `mypy` with no findings.
