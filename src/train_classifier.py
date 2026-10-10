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


def split_dataset(X, y, test_size: float = 0.25, random_state: int = 42):
    """The single, shared train/test split -- deterministic (fixed seed).

    Exists so that ANYTHING comparing models can score them all on the same
    held-out records. train_model() trains on the train half and reports AUC
    on the test half; the retrain handler calls this same function to get the
    identical test half and score the currently-deployed model on it too --
    otherwise the two AUCs being compared come from different data and mean
    nothing relative to each other.
    """
    return train_test_split(
        X, y, test_size=test_size, random_state=random_state, stratify=y
    )


def make_model(random_state: int = 42):
    """The classifier configuration used everywhere -- training, the retrain
    Lambda, and cross_validate.py -- so an evaluation always measures exactly
    the model that gets deployed."""
    return xgb.XGBClassifier(
        n_estimators=200,
        max_depth=3,
        learning_rate=0.08,
        subsample=0.9,
        colsample_bytree=0.9,
        eval_metric="logloss",
        random_state=random_state,
    )


def train_model(X, y, test_size: float = 0.25, random_state: int = 42):
    """Train the XGBoost classifier and return (model, auc, report_dict).

    Shared by both the CLI script below and the Lambda retrain handler
    (src/retrain_handler.py), so both paths train identically.
    """
    X_train, X_test, y_train, y_test = split_dataset(X, y, test_size, random_state)

    model = make_model(random_state)
    model.fit(X_train, y_train)

    probs = model.predict_proba(X_test)[:, 1]
    preds = (probs >= 0.5).astype(int)
    auc = roc_auc_score(y_test, probs)
    report = classification_report(y_test, preds, target_names=["healthy", "distressed"],
                                    output_dict=True)

    return model, auc, report


def rows_to_arrays(raw_rows: list[dict]):
    """Turns a list of raw JSON records into (X, y, tickers) arrays, skipping
    any record with incomplete financials. Shared by load_dataset() (random-
    split path) and time_split_dataset()'s callers, so both build features
    identically."""
    X, y, tickers = [], [], []
    skipped = []
    for row in raw_rows:
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


def load_dataset(path: str):
    with open(path) as f:
        raw = json.load(f)
    return rows_to_arrays(raw)


# Only us_edgar_labels.py fetches financials AS OF the exact event_date (see
# edgar_client.py's as_of_date cutoff) -- every other market's event_date is
# either null (india_gsm's GSM-flagged companies, which use yfinance's
# "latest", not as-of any date) or a fixed placeholder shared by several
# companies (india_gsm's/india's healthy rows, all stamped "2023-03-31" in
# india_distress_labels.csv, disconnected from when their financials were
# actually fetched). Treat only US records as having a real timeline anchor
# until another market gets the same as-of-date treatment.
RELIABLE_DATE_MARKET = "US"


def _reliable_date_records(raw_rows: list[dict]) -> list[dict]:
    return [r for r in raw_rows if r.get("market") == RELIABLE_DATE_MARKET and r.get("event_date")]


def time_split_dataset(raw_rows: list[dict], cutoff_date: str):
    """Splits raw JSON records into (train_rows, test_rows) by event_date,
    instead of randomly -- so the held-out set measures whether the model
    generalizes to LATER companies, not just different ones.

    Only reliably-dated records (see RELIABLE_DATE_MARKET /
    _reliable_date_records) are eligible for the test side; every other
    record (another market, or a US record missing event_date) always goes
    to train, since it can't be verified to belong on either side of the
    boundary.

    Each eligible COMPANY (ticker) contributes at most one record to this
    split -- its earliest dated snapshot -- rather than every snapshot that
    exists. Without this, the same company resampled at different dates
    (which happens: build_dataset.py's healthy sample keeps resurfacing the
    same relevance-ranked filers across runs) could straddle the boundary,
    which is both an identity leak (testing on a company already seen in
    training, just at a later date) and a date-ordering violation. A later
    snapshot of a company already placed in train by an earlier snapshot is
    kept in train only if it's ALSO before the cutoff (harmless extra
    signal); if it falls at/after the cutoff it is dropped entirely -- never
    added to train (would date-order after test) or to test (the company
    isn't new there).
    """
    reliable = _reliable_date_records(raw_rows)
    by_ticker: dict[str, list[dict]] = {}
    for r in reliable:
        by_ticker.setdefault(r["ticker"], []).append(r)

    train, test = [], []
    for snaps in by_ticker.values():
        earliest = min(snaps, key=lambda r: r["event_date"])
        (train if earliest["event_date"] < cutoff_date else test).append(earliest)
        for snap in snaps:
            if snap is not earliest and snap["event_date"] < cutoff_date:
                train.append(snap)

    reliable_ids = {id(r) for r in reliable}
    train.extend(r for r in raw_rows if id(r) not in reliable_ids)

    return train, test


def time_split_class_counts(train_rows: list[dict], test_rows: list[dict]) -> dict:
    """{'train': {0: n_unique_healthy_companies, 1: n_unique_distressed}, 'test': {...}}.
    Counts unique tickers, not raw records, since train can contain more
    than one snapshot of the same company."""
    def counts(rows):
        seen = {}
        for r in rows:
            seen.setdefault(r["ticker"], r["label_distressed"])
        c = {0: 0, 1: 0}
        for label in seen.values():
            c[label] += 1
        return c

    return {"train": counts(train_rows), "test": counts(test_rows)}


def check_time_split_gate(train_rows: list[dict], test_rows: list[dict], min_per_class: int = 5) -> dict:
    """Raises ValueError if either side has fewer than `min_per_class` unique
    companies of either label -- the split is too thin to mean anything at
    this dataset size (see CLAUDE.md's known-limitations notes). Callers
    that need to keep running on a small dataset (e.g. the retrain Lambda)
    should catch this and fall back to a random split rather than report a
    number resting on a single company."""
    counts = time_split_class_counts(train_rows, test_rows)
    problems = [
        f"{side} has only {n} unique label={label} companies (need >= {min_per_class})"
        for side, side_counts in counts.items()
        for label, n in side_counts.items()
        if n < min_per_class
    ]
    if problems:
        raise ValueError("Time split failed its minimum-size gate: " + "; ".join(problems))
    return counts


def report_cutoff_candidates(raw_rows: list[dict], candidate_cutoffs: list[str]) -> str:
    """Prints unique-company-by-class counts on each side for a list of
    candidate cutoff dates -- meant to be looked at BEFORE picking a cutoff,
    since class and era can be confounded (bankruptcies cluster in time)."""
    lines = []
    for cutoff in candidate_cutoffs:
        train_rows, test_rows = time_split_dataset(raw_rows, cutoff)
        counts = time_split_class_counts(train_rows, test_rows)
        lines.append(
            f"  cutoff {cutoff}: train healthy={counts['train'][0]:3d} distressed={counts['train'][1]:3d}"
            f" | test healthy={counts['test'][0]:3d} distressed={counts['test'][1]:3d}"
        )
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="data/sample_companies.json")
    parser.add_argument("--out", default="models/distress_model.json")
    parser.add_argument("--test-size", type=float, default=0.25)
    parser.add_argument("--split-mode", choices=["random", "time"], default="random",
                         help="'time' trains on companies dated before --cutoff-date and "
                              "tests on companies dated at/after it (see time_split_dataset), "
                              "instead of a random stratified split. Requires --cutoff-date.")
    parser.add_argument("--cutoff-date", default=None,
                         help="YYYY-MM-DD boundary for --split-mode time.")
    parser.add_argument("--min-per-class", type=int, default=5,
                         help="Minimum unique companies per class required on EACH side of "
                              "a time split before it's trusted (see check_time_split_gate).")
    args = parser.parse_args()

    if args.split_mode == "time":
        if not args.cutoff_date:
            raise SystemExit("--split-mode time requires --cutoff-date")
        with open(args.data) as f:
            raw_rows = json.load(f)
        train_rows, test_rows = time_split_dataset(raw_rows, args.cutoff_date)
        check_time_split_gate(train_rows, test_rows, min_per_class=args.min_per_class)
        X_train, y_train, _ = rows_to_arrays(train_rows)
        X_test, y_test, _ = rows_to_arrays(test_rows)
        print(f"Time split at {args.cutoff_date}: {len(y_train)} train / {len(y_test)} test records")
        print(f"  Features: {FEATURE_NAMES}")
        model = make_model()
        model.fit(X_train, y_train)
        probs = model.predict_proba(X_test)[:, 1]
        preds = (probs >= 0.5).astype(int)
        auc = roc_auc_score(y_test, probs)
        report = classification_report(y_test, preds, target_names=["healthy", "distressed"],
                                        output_dict=True)
    else:
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
