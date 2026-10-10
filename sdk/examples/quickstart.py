"""Minimal SDK walkthrough against a running DataSentry API.

    export DATASENTRY_API_URL=http://localhost:8000
    export DATASENTRY_API_KEY=dsk_...      # Settings → API keys in the UI
    python examples/quickstart.py
"""
import numpy as np
import pandas as pd

from datasentry import DataSentry

rng = np.random.default_rng(0)  # SYNTHETIC example data
df = pd.DataFrame({
    "customer_id": [f"C{i:05d}" for i in range(1000)],
    "segment": rng.choice(["retail", "smb", "enterprise"], 1000, p=[0.6, 0.3, 0.1]),
    "spend": rng.lognormal(3.5, 0.6, 1000).round(2),
})

with DataSentry() as client:
    dataset = client.register_dataset(name="customer_events_quickstart", data=df,
                                      description="Customer activity dataset (synthetic)")
    profile = client.profile(dataset.id)
    print("rows:", profile.row_count, "| spend mean:", round(profile.column("spend")["mean"], 2))

    result = client.validate(dataset.id, rules=[
        {"type": "not_null", "column": "customer_id"},
        {"type": "unique", "column": "customer_id"},
        {"type": "range", "column": "spend", "config": {"min": 0}},
    ])
    print(result.summary)

    # A second batch with a shifted spend distribution and missing segments
    df2 = df.assign(spend=(df["spend"] * 1.5).round(2), segment=df["segment"].where(rng.random(1000) > 0.25))
    version, monitoring = client.create_version(dataset.id, df2)
    print("v2 status:", monitoring.status, "| findings:", [(f["kind"], f["column"]) for f in monitoring.findings])
    if monitoring.incident_id:
        incident = client.get_incident(monitoring.incident_id)
        print("incident:", incident.title, incident.priority.get("urgency"))
