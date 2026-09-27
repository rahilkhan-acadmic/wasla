"""
Generates (or regenerates) tests/fixture_prediction_snapshot.json -- the
"golden" expected outputs that tests/test_prediction_stability.py checks
new environments against.

Run this DELIBERATELY, not automatically:
    python tests/generate_prediction_snapshot.py

When to run it:
  - Once, to establish the initial baseline (already done -- see the
    fixture file this produces).
  - After you've knowingly accepted a change in model behavior -- e.g.
    after bumping xgboost/scikit-learn/numpy/pandas AND retraining AND
    reviewing that the new predictions are reasonable. Regenerating the
    snapshot is how you tell the test suite "yes, this new behavior is
    correct, stop flagging it."

Do NOT run this reflexively just to make a failing test pass without
understanding why it changed -- that defeats the entire point of this
test, which is to force a conscious decision rather than let drift happen
silently (see the finance-distress-model project's actual incident: a
routine CI/CD rebuild silently pulled a newer XGBoost, and the exact same
stored model started returning different predictions with zero warning).
"""

import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from train_classifier import load_dataset, train_model
from features import build_feature_row, financials_from_dict, FEATURE_NAMES

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "sample_companies.json")
SNAPSHOT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixture_prediction_snapshot.json")

# A small, fixed set of companies to check on every run -- picked once,
# deliberately mixing distressed and healthy examples, and never changed
# casually (changing WHICH companies are checked is a different decision
# than accepting new prediction VALUES for the same companies).
SNAPSHOT_TICKERS = ["SYN001", "SYN010", "SYN027", "SYN060", "SYN075", "SYN100"]


def generate_snapshot():
    with open(DATA_PATH) as f:
        raw = {row["ticker"]: row for row in json.load(f)}

    X, y, tickers = load_dataset(DATA_PATH)
    model, auc, _ = train_model(X, y)

    snapshot = {
        "_comment": "Golden prediction snapshot. See generate_prediction_snapshot.py "
                    "docstring before regenerating this file.",
        "training_auc": round(auc, 6),
        "predictions": {},
    }

    for ticker in SNAPSHOT_TICKERS:
        row = raw[ticker]
        fin = financials_from_dict(row["financials"])
        feats = build_feature_row(fin, row.get("headlines", []))
        x = [[feats[name] for name in FEATURE_NAMES]]
        prob = float(model.predict_proba(x)[0][1])
        snapshot["predictions"][ticker] = round(prob, 6)

    with open(SNAPSHOT_PATH, "w") as f:
        json.dump(snapshot, f, indent=2)

    print(f"Wrote snapshot for {len(SNAPSHOT_TICKERS)} companies to {SNAPSHOT_PATH}")
    print(json.dumps(snapshot, indent=2))


if __name__ == "__main__":
    generate_snapshot()
