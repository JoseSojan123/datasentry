"""Generate docs/api.md (endpoint index) from the FastAPI OpenAPI schema.

    cd backend && python ../scripts/gen_api_reference.py
"""

from __future__ import annotations

import os
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("ENVIRONMENT", "test")

from app.main import create_app  # noqa: E402


def main() -> None:
    spec = create_app().openapi()
    groups: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            tag = (op.get("tags") or ["other"])[0]
            groups[tag].append((method.upper(), path, op.get("summary") or ""))
    lines = [
        "# API reference",
        "",
        "Generated from the OpenAPI schema by `scripts/gen_api_reference.py`. The interactive reference with request and "
        "response models is served by the API at `/api/docs` (Swagger UI) and `/api/redoc`; the raw schema is at "
        "`/api/openapi.json`.",
        "",
        "**Authentication:** `Authorization: Bearer <token>` (from `POST /api/v1/auth/login`, `/auth/register` or "
        "`/auth/demo`) or `X-API-Key: dsk_…` (Settings → API keys). Viewers can read; changes need the editor role; "
        "members, API keys, workspace settings and the audit log need admin.",
        "",
        "**Errors** always look like `{\"error\": {\"code\", \"message\", \"details\", \"request_id\"}}`. Rate-limited "
        "requests return 429 with `Retry-After`.",
        "",
        "**Pagination:** list endpoints take `page` and `page_size` and return `{items, total, page, page_size, pages}`.",
        "",
    ]
    for tag in sorted(groups):
        lines += [f"## {tag.replace('_', ' ').capitalize()}", "", "| Method | Path | Summary |", "|---|---|---|"]
        for method, path, summary in sorted(groups[tag], key=lambda r: (r[1], r[0])):
            lines.append(f"| {method} | `{path}` | {summary} |")
        lines.append("")
    out = ROOT / "docs" / "api.md"
    out.write_text("\n".join(lines))
    total = sum(len(v) for v in groups.values())
    print(f"Wrote {out} ({total} operations)")


if __name__ == "__main__":
    main()
