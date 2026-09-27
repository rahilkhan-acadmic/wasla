"""
Compares fresh predictions, run under whatever environment this test
executes in, against the golden snapshot in fixture_prediction_snapshot.json.

This is what actually catches dependency-version-driven prediction drift --
something "run training twice in one sitting" structurally cannot catch,
since both runs would share the same library versions. This test compares
across time/environments instead, which is where the real risk lives (see
this project's real incident: a routine rebuild silently pulled a newer
XGBoost, and the exact same stored model started returning different
predictions with zero warning, until this was caught by manual testing).

If this test fails, it means: the model-relevant environment (xgboost,
scikit-learn, numpy, pandas) has changed since the snapshot was generated,
and that change altered actual prediction behavior. That's not necessarily
wrong -- but it MUST be a conscious decision, not something that merges
silently:
  1. Understand WHY it changed (check what changed in requirements.txt)
  2. Decide if the new behavior is acceptable (review the actual numbers
     below, not just "test passed/failed")
  3. If accepted, regenerate the snapshot deliberately:
       python tests/generate_prediction_snapshot.py
     and commit the updated fixture_prediction_snapshot.json as part of
     the SAME PR that changed the dependency -- so the snapshot update is
     reviewable evidence of an intentional decision, not a silent drift.
"""

import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from train_classifier import load_dataset, train_model
from features import build_feature_row, financials_from_dict, FEATURE_NAMES

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "sample_companies.json")
SNAPSHOT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixture_prediction_snapshot.json")

# How much a prediction is allowed to drift before this is treated as a real
# behavior change rather than harmless floating-point noise. Same-version
# reruns are bit-identical (verified empirically), so this only needs to be
# larger than true floating-point noise, not larger than genuine drift --
# 0.005 is deliberately tight.
TOLERANCE = 0.005


def run_test():
    with open(SNAPSHOT_PATH) as f:
        snapshot = json.load(f)

    with open(DATA_PATH) as f:
        raw = {row["ticker"]: row for row in json.load(f)}

    X, y, tickers = load_dataset(DATA_PATH)
    model, auc, _ = train_model(X, y)

    print(f"Snapshot training_auc: {snapshot['training_auc']}, current: {round(auc, 6)}")

    failures = []
    for ticker, expected in snapshot["predictions"].items():
        row = raw[ticker]
        fin = financials_from_dict(row["financials"])
        feats = build_feature_row(fin, row.get("headlines", []))
        x = [[feats[name] for name in FEATURE_NAMES]]
        actual = float(model.predict_proba(x)[0][1])

        diff = abs(actual - expected)
        status = "OK" if diff <= TOLERANCE else "DRIFT"
        print(f"  {ticker}: expected={expected:.6f} actual={actual:.6f} diff={diff:.6f} [{status}]")

        if diff > TOLERANCE:
            failures.append((ticker, expected, actual, diff))

    if failures:
        print("\n" + "=" * 70)
        print(f"PREDICTION DRIFT DETECTED in {len(failures)} of "
              f"{len(snapshot['predictions'])} snapshot companies.")
        print("This means the model-relevant environment has changed behavior")
        print("since the snapshot was generated. See this file's module")
        print("docstring for what to do next -- do NOT just regenerate the")
        print("snapshot without understanding why it changed.")
        print("=" * 70)
        raise AssertionError(f"{len(failures)} prediction(s) drifted beyond tolerance {TOLERANCE}")

    print(f"\nAll {len(snapshot['predictions'])} predictions match the golden snapshot "
          f"within tolerance {TOLERANCE}. PASSED")


if __name__ == "__main__":
    run_test()
