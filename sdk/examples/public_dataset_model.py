"""Reproducible public-dataset example: Breast Cancer Wisconsin (Diagnostic).

The dataset ships with scikit-learn (sklearn.datasets.load_breast_cancer; originally UCI ML Repository,
CC BY 4.0), so no download is needed. The script:

1. registers the training split as a reference dataset,
2. trains a logistic-regression classifier and registers it with baseline metrics,
3. logs predictions for a clean holdout and for a deliberately perturbed holdout
   (a simulated sensor-calibration error: 'mean radius' and 'mean texture' scaled by 1.3),
4. backfills labels for part of the perturbed batch (delayed labels), and
5. evaluates input drift, prediction drift and performance separately.

    export DATASENTRY_API_URL=http://localhost:8000 DATASENTRY_API_KEY=dsk_...
    python examples/public_dataset_model.py
"""
from datetime import UTC, datetime, timedelta

from datasentry import DataSentry
from sklearn.datasets import load_breast_cancer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

FEATURES = ["mean radius", "mean texture", "mean smoothness", "mean compactness", "mean concavity", "worst area"]

data = load_breast_cancer(as_frame=True)
frame = data.frame.rename(columns={"target": "benign"})
cols = {c: c.replace(" ", "_") for c in FEATURES}
train, test = train_test_split(frame, test_size=0.4, random_state=42, stratify=frame["benign"])
clean, shifted = train_test_split(test, test_size=0.5, random_state=7, stratify=test["benign"])
shifted = shifted.copy()
shifted[["mean radius", "mean texture"]] *= 1.3  # simulated calibration error

model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000)).fit(train[FEATURES], train["benign"])
p_clean = model.predict_proba(clean[FEATURES])[:, 1]
baseline = {"f1": float(f1_score(clean["benign"], p_clean >= 0.5)), "roc_auc": float(roc_auc_score(clean["benign"], p_clean)),
            "evaluated_on": "clean holdout"}

with DataSentry() as client:
    ref = client.register_dataset(
        name="breast_cancer_wisconsin_train", data=train[FEATURES + ["benign"]].rename(columns=cols),
        description="PUBLIC dataset: Breast Cancer Wisconsin (Diagnostic), sklearn.datasets.load_breast_cancer, CC BY 4.0.",
        tags=["public", "uci"], domain="healthcare-research", criticality="medium")
    m = client.register_model("breast_cancer_lr", "classification", positive_label=1, reference_dataset_id=ref.id,
                              target="benign (1) vs malignant (0)", description="Logistic regression on 6 features")
    client.create_model_version(m.id, "1.0", input_schema=[{"name": cols[f], "type": "numeric"} for f in FEATURES],
                                baseline_metrics=baseline, artifact={"framework": "scikit-learn"})
    t0 = datetime.now(UTC) - timedelta(days=2)

    def records(df, start, prefix, with_labels):
        proba = model.predict_proba(df[FEATURES])[:, 1]
        return [{"record_id": f"{prefix}-{idx}", "timestamp": start + timedelta(minutes=i), "prediction": int(proba[i] >= 0.5),
                 "score": float(proba[i]), "label": int(df["benign"].iloc[i]) if with_labels else None,
                 "features": {cols[f]: float(df[f].iloc[i]) for f in FEATURES}} for i, idx in enumerate(df.index)]

    client.log_predictions(m.id, "1.0", records(clean, t0, "clean", True))
    client.log_predictions(m.id, "1.0", records(shifted, t0 + timedelta(days=1), "shift", False))
    half = shifted.iloc[: len(shifted) // 2]
    client.log_labels(m.id, "1.0", [{"record_id": f"shift-{i}", "label": int(v)} for i, v in half["benign"].items()])
    ev = client.evaluate_model(m.id, "1.0", current_window=(t0 + timedelta(days=1), t0 + timedelta(days=2)),
                               reference_window=(t0, t0 + timedelta(days=1)))
    print(f"label coverage: {ev.label_coverage:.0%}")
    print("drifted inputs:", [f["feature"] for f in ev.input_drift.get("features", []) if f.get("status") == "drift"])
    print("prediction drift:", ev.prediction_drift.get("status"), "| performance:", ev.performance.get("status"),
          ev.performance.get("explanation", ""))
    print("note: drift and performance are reported separately; drift alone does not prove the model got worse.")
