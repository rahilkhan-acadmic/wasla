"""
Trains a gradient-boosted classifier to predict company distress, using
Altman-style structured ratios + news sentiment as features.

Usage:
    python src/train_classifier.py --data data/sample_companies.json --out models/distress_model.json

On the bundled SYNTHETIC demo data this will look artificially easy to
separate (the two classes were generated from clearly different
distributions on purpose, to prove the pipeline works end-to-end).
Real-world performance on actual filings + actual bankruptcy/delisting
labels will be much harder and noisier -- see README for how to swap in
real data.
"""

import argparse
import json

import numpy as np
import xgboost as xgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, roc_auc_score

from features import (build_feature_row, financials_from_dict, FEATURE_NAMES,
                       has_complete_financials, REQUIRED_FINANCIAL_FIELDS)


def train_model(X, y, test_size: float = 0.25, random_state: int = 42):
    """Train the XGBoost classifier and return (model, auc, report_dict).

    Shared by both the CLI script below and the Lambda retrain handler
    (src/retrain_handler.py), so both paths train identically.
    """
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_size, random_state=random_state, stratify=y
    )

    model = xgb.XGBClassifier(
        n_estimators=200,
        max_depth=3,
        learning_rate=0.08,
        subsample=0.9,
        colsample_bytree=0.9,
        eval_metric="logloss",
        random_state=random_state,
    )
    model.fit(X_train, y_train)

    probs = model.predict_proba(X_test)[:, 1]
    preds = (probs >= 0.5).astype(int)
    auc = roc_auc_score(y_test, probs)
    report = classification_report(y_test, preds, target_names=["healthy", "distressed"],
                                    output_dict=True)

    return model, auc, report


def load_dataset(path: str):
    with open(path) as f:
        raw = json.load(f)

    X, y, tickers = [], [], []
    skipped = []
    for row in raw:
        if not has_complete_financials(row["financials"]):
            skipped.append(row.get("ticker", "?"))
            continue
        fin = financials_from_dict(row["financials"])
        feats = build_feature_row(fin, row.get("headlines", []))
        X.append([feats[name] for name in FEATURE_NAMES])
        y.append(row["label_distressed"])
        tickers.append(row["ticker"])

    if skipped:
        print(f"Skipped {len(skipped)} record(s) with incomplete financials "
              f"(missing at least one of {REQUIRED_FINANCIAL_FIELDS}): {skipped}")

    return np.array(X), np.array(y), tickers


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="data/sample_companies.json")
    parser.add_argument("--out", default="models/distress_model.json")
    parser.add_argument("--test-size", type=float, default=0.25)
    args = parser.parse_args()

    print(f"Loading dataset from {args.data} ...")
    X, y, tickers = load_dataset(args.data)
    print(f"  {len(y)} companies | {y.sum()} distressed | {len(y) - y.sum()} healthy")
    print(f"  Features: {FEATURE_NAMES}")

    model, auc, report = train_model(X, y, test_size=args.test_size)

    print("\n=== Evaluation on held-out test set ===")
    print(json.dumps(report, indent=2))
    print(f"ROC-AUC: {auc:.3f}")

    print("\n=== Feature importances ===")
    for name, imp in sorted(zip(FEATURE_NAMES, model.feature_importances_),
                             key=lambda t: -t[1]):
        print(f"  {name:28s} {imp:.3f}")

    model.save_model(args.out)
    print(f"\nSaved trained model to {args.out}")


if __name__ == "__main__":
    main()
