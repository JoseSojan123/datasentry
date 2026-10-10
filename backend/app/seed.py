"""Create an admin account and load the synthetic sample data from the command line.

    python -m app.seed --email admin@example.com --workspace "Data platform"
    python -m app.seed --email admin@example.com --scenarios all

The password is read from the SEED_ADMIN_PASSWORD environment variable so it never appears in shell
history or process listings. If it is unset, a random password is generated and printed once.
Running the command again is safe: an existing user is reused and sample data is loaded only once.
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys

from sqlalchemy import func, select

from app.api.deps import Principal
from app.core.security import hash_password
from app.db import models as m
from app.db.session import session_scope
from app.services.seed import load_scenario, seed_workspace
from datasentry_core import synthetic


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.seed", description="Create an admin and load synthetic sample data.")
    ap.add_argument("--email", required=True, help="admin email (created if it does not exist)")
    ap.add_argument("--name", default="Admin", help="display name for a new admin")
    ap.add_argument("--workspace", default="DataSentry", help="workspace name for a new admin")
    ap.add_argument("--no-sample-data", action="store_true", help="only create the account")
    ap.add_argument("--scenarios", default="", help="comma-separated scenario names, or 'all' (see datasentry_core.synthetic)")
    args = ap.parse_args(argv)

    names = synthetic.SCENARIOS if args.scenarios == "all" else [s for s in args.scenarios.split(",") if s]
    unknown = [s for s in names if s not in synthetic.SCENARIOS]
    if unknown:
        ap.error(f"unknown scenario(s): {', '.join(unknown)}. Available: {', '.join(synthetic.SCENARIOS)}")

    with session_scope() as db:
        user = db.scalar(select(m.User).where(func.lower(m.User.email) == args.email.lower()))
        generated = None
        if user is None:
            password = os.environ.get("SEED_ADMIN_PASSWORD")
            if not password:
                password = generated = secrets.token_urlsafe(18)
            elif len(password) < 10:
                print("SEED_ADMIN_PASSWORD must be at least 10 characters.", file=sys.stderr)
                return 2
            ws = m.Workspace(name=args.workspace)
            db.add(ws)
            db.flush()
            user = m.User(workspace_id=ws.id, email=args.email.lower(), display_name=args.name,
                          password_hash=hash_password(password), role="admin")
            db.add(user)
            db.commit()
            print(f"Created admin {user.email} in workspace '{ws.name}' (id {ws.id}).")
        else:
            print(f"Admin {user.email} already exists; reusing workspace {user.workspace_id}.")
        principal = Principal(user.workspace_id, user.id, user.role, label=user.email)

        if not args.no_sample_data:
            result = seed_workspace(db, user.workspace_id, principal)
            print("Sample data: " + result.get("skipped", "loaded (SYNTHETIC, fixed seeds)."))
        for name in names:
            ds_name = f"scenario_{name}"
            if db.scalar(select(m.Dataset.id).where(m.Dataset.workspace_id == user.workspace_id, m.Dataset.name == ds_name)):
                print(f"Scenario {name}: already loaded.")
                continue
            res = load_scenario(db, user.workspace_id, name, principal)
            print(f"Scenario {name}: {len(res['findings'])} finding(s), incident {res['incident_id'] or 'none'}.")

    if generated:
        print(f"\nGenerated password (shown once, store it now): {generated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
