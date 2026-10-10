"""Reproducible end-to-end scenario against a running DataSentry API (standard library only).

    python scripts/e2e_scenario.py --api http://localhost:8000

Use it as a smoke test after deploying. It creates its own expiring demo workspace, so it does not
touch other users' data, and it fails loudly (non-zero exit) at the first step that does not behave
as documented:

 1. health and readiness respond, and an unknown route returns the structured error shape
 2. a healthy synthetic batch produces no incident (control)
 3. a batch with unexpected currency codes opens an incident with findings on 'currency'
 4. executing a remediation that nobody approved is refused, and nothing is marked fixed
 5. quarantining the bad version is approved, executed, verified, and only then resolves the incident
 6. the incident's lineage investigation reports the incident as contained
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from typing import Any


class Client:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.token: str | None = None

    def call(self, method: str, path: str, body: Any = None, expect: int | tuple[int, ...] = (200, 201)) -> Any:
        url = f"{self.base}/api/v1{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(req, timeout=120) as res:
                status, raw = res.status, res.read()
        except urllib.error.HTTPError as e:
            status, raw = e.code, e.read()
        payload = json.loads(raw) if raw else None
        expected = (expect,) if isinstance(expect, int) else expect
        if status not in expected:
            raise AssertionError(f"{method} {path} returned {status}, expected {expected}: {raw[:400]!r}")
        return payload


STEP = 0


def step(title: str) -> None:
    global STEP
    STEP += 1
    print(f"[{STEP}] {title}", flush=True)


def check(cond: bool, message: str) -> None:
    if not cond:
        raise AssertionError(message)
    print(f"    ok  {message}")


def main() -> int:
    ap = argparse.ArgumentParser(description="End-to-end smoke scenario for a DataSentry deployment.")
    ap.add_argument("--api", default="http://localhost:8000", help="API base URL (no /api/v1 suffix)")
    args = ap.parse_args()
    api = Client(args.api)
    started = time.perf_counter()

    step("Health, readiness and error shape")
    health = api.call("GET", "/health")
    check(health.get("status") == "ok", "liveness reports ok")
    ready = api.call("GET", "/ready", expect=(200, 503))
    check(ready.get("status") == "ready", f"readiness reports ready ({ready.get('status')})")
    err = api.call("GET", "/datasets/999999999", expect=401)
    check(set(err.get("error", {})) >= {"code", "message", "request_id"}, "errors use the structured shape")
    check("Traceback" not in json.dumps(err), "error body carries no stack trace")

    step("Create an isolated demo workspace (no sample data)")
    session = api.call("POST", "/auth/demo", {"load_sample_data": False})
    api.token = session["access_token"]
    check(session["workspace"]["is_demo"], "workspace is a demo workspace with an expiry")

    step("Control: a healthy batch")
    healthy = api.call("POST", "/demo/scenarios/healthy")
    alerts = [f for f in healthy["findings"] if f["severity"] in ("warning", "critical")]
    check(not alerts, f"no warning or critical findings ({len(healthy['findings'])} total findings)")
    check(healthy["incident_id"] is None, "no incident opened")

    step("Defect: unexpected currency codes")
    bad = api.call("POST", "/demo/scenarios/unexpected_categories")
    cols = {f.get("column") for f in bad["findings"]}
    check("currency" in cols, f"findings include 'currency' (columns: {sorted(c for c in cols if c)})")
    check(bad["incident_id"] is not None, "an incident was opened")
    inc = api.call("GET", f"/incidents/{bad['incident_id']}")
    check(inc["status"] == "open", f"incident {inc['id']} is open with severity {inc['severity']}")
    proposals = {p["action"]: p for p in inc["proposals"]}
    check("quarantine_version" in proposals, f"remediation proposals: {sorted(proposals)}")

    step("Remediation without approval is refused")
    restore = proposals.get("restore_last_known_good") or next(p for p in inc["proposals"] if p["action"] != "quarantine_version")
    refused = api.call("POST", f"/remediations/{restore['id']}/execute", expect=(403, 409, 422))
    check(bool(refused["error"]["message"]), f"'{restore['action']}' refused: {refused['error']['message'][:100]}")
    after = api.call("GET", f"/incidents/{inc['id']}")
    check(after["status"] != "resolved", f"incident stays {after['status']}; nothing is marked fixed")

    step("Quarantine, execute and verify")
    q = proposals["quarantine_version"]
    approved = api.call("POST", f"/remediations/{q['id']}/approve", {"note": "e2e scenario"})
    check(approved["status"] == "approved", "proposal approved")
    res = api.call("POST", f"/remediations/{q['id']}/execute")
    check(res["execution"]["status"] == "succeeded", "execution succeeded")
    check(res["proposal"]["status"] == "verified", f"verification passed: {res['execution']['verification'].get('note', '')[:120]}")
    check(res["incident"]["status"] == "resolved", "incident resolved")
    check((res["incident"].get("resolution") or {}).get("type") == "verified", "resolution type is 'verified', not manual")

    step("Investigation shows the incident contained")
    inv = api.call("GET", f"/incidents/{inc['id']}/investigation")
    check(inv.get("contained") is True, "investigation reports contained")

    print(f"\nAll steps passed in {time.perf_counter() - started:.1f}s.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as e:
        print(f"\nFAILED at step {STEP}: {e}", file=sys.stderr)
        raise SystemExit(1) from None
