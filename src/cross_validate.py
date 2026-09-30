"""
Does the model add anything beyond simple baselines?

The retrain pipeline judges a model on ONE small held-out split (about 14
companies at the current dataset size). That's too little to distinguish
anything: the same single feature scored 0.965 on the full data and 0.896 on
a 14-record subset, so a perfect score on 14 records sits well inside the noise.

This uses ALL the data instead: repeated stratified k-fold cross-validation
(every company is tested many times, each time by a model that never saw it),
and compares, on IDENTICAL folds:

  - the deployed XGBoost configuration (train_classifier.make_model)
  - an untuned logistic regression on the ratio features -- a simple model
    with far fewer moving parts
  - each single feature ranked on its own, with no model at all
    (Altman Z, Z'', retained earnings / assets, leverage)

If XGBoost isn't clearly better than "rank by retained earnings", the honest
conclusion is that the model isn't demonstrably adding anything on this
data -- which says as much about the dataset (easy, tiny) as about the model.

Usage:
    python src/cross_validate.py --data data/real_companies_full.json

Caveats (read before quoting a number):
  - With ~55 records, differences smaller than the reported standard
    deviation are noise. The paired win/tie/loss counts are more informative
    than the means.
  - Random folds ignore time: this measures how well ratios SEPARATE the
    classes, not how well they PREDICT a future failure.
"""

import argparse
import os
import sys

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss, roc_auc_score
from sklearn.model_selection import RepeatedStratifiedKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import FunctionTransformer, StandardScaler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from features import FEATURE_NAMES  # noqa: E402
from train_classifier import load_dataset, make_model  # noqa: E402

# The ratio features a simple model gets. Excludes news_sentiment (a constant
# now) and the two Altman composites (built from these same ratios).
RATIO_FEATURES = [
    "working_capital_ratio", "retained_earnings_ratio", "ebit_margin_on_assets",
    "leverage_ratio", "asset_turnover",
]

# (feature, sign): sign=+1 means a HIGHER value indicates distress. Signs are
# fixed a priori from what each ratio means -- never fitted to the data, so
# these baselines can't overfit.
SINGLE_FEATURE_BASELINES = [
    ("z_score", -1),
    ("z_double_prime", -1),
    ("retained_earnings_ratio", -1),
    ("leverage_ratio", +1),
]

MODEL_NAME = "xgboost (deployed config)"
LOGISTIC_NAME = "logistic regression (5 ratios)"


def _make_logistic():
    # Clipping at +/-5 standard deviations blunts the extreme ratios tiny
    # companies produce (assets near zero make turnover/leverage explode).
    return make_pipeline(
        StandardScaler(),
        FunctionTransformer(lambda a: np.clip(a, -5, 5)),
        LogisticRegression(max_iter=1000),
    )


def run_cross_validation(X, y, n_splits: int = 5, n_repeats: int = 10, seed: int = 42):
    """Returns {name: {"auc": ndarray, "logloss": ndarray | None}}, with every
    array aligned fold-for-fold across methods so they can be compared pairwise."""
    X, y = np.asarray(X), np.asarray(y)
    min_class = int(min((y == 0).sum(), (y == 1).sum()))
    if min_class < n_splits:
        raise ValueError(
            f"Smallest class has {min_class} records but n_splits={n_splits}; "
            f"every test fold needs both classes.")

    idx = {name: FEATURE_NAMES.index(name) for name in FEATURE_NAMES}
    ratio_cols = [idx[n] for n in RATIO_FEATURES]

    scores = {MODEL_NAME: ([], []), LOGISTIC_NAME: ([], [])}
    for name, _ in SINGLE_FEATURE_BASELINES:
        scores[f"{name} alone"] = ([], None)

    splitter = RepeatedStratifiedKFold(n_splits=n_splits, n_repeats=n_repeats, random_state=seed)
    for train, test in splitter.split(X, y):
        X_tr, X_te, y_tr, y_te = X[train], X[test], y[train], y[test]

        model = make_model()
        model.fit(X_tr, y_tr)
        p = model.predict_proba(X_te)[:, 1]
        scores[MODEL_NAME][0].append(roc_auc_score(y_te, p))
        scores[MODEL_NAME][1].append(log_loss(y_te, p, labels=[0, 1]))

        logistic = _make_logistic()
        logistic.fit(X_tr[:, ratio_cols], y_tr)
        p = logistic.predict_proba(X_te[:, ratio_cols])[:, 1]
        scores[LOGISTIC_NAME][0].append(roc_auc_score(y_te, p))
        scores[LOGISTIC_NAME][1].append(log_loss(y_te, p, labels=[0, 1]))

        for name, sign in SINGLE_FEATURE_BASELINES:
            scores[f"{name} alone"][0].append(roc_auc_score(y_te, sign * X_te[:, idx[name]]))

    return {
        name: {
            "auc": np.array(auc),
            "logloss": np.array(ll) if ll is not None else None,
        }
        for name, (auc, ll) in scores.items()
    }


def format_report(scores: dict, n_records: int) -> str:
    n_folds = len(scores[MODEL_NAME]["auc"])
    lines = [
        f"Cross-validated on {n_records} records, {n_folds} test folds "
        f"(every method scored on identical folds).",
        "",
        f"{'method':36s} {'AUC mean':>9s} {'± std':>7s} {'log loss':>9s}",
        "-" * 65,
    ]
    for name, s in scores.items():
        ll = f"{s['logloss'].mean():9.3f}" if s["logloss"] is not None else f"{'n/a':>9s}"
        lines.append(f"{name:36s} {s['auc'].mean():9.3f} {s['auc'].std():7.3f} {ll}")

    lines += [
        "",
        f"Paired: {MODEL_NAME} minus each alternative, per fold "
        f"(positive = model better)",
        f"{'vs.':36s} {'mean diff':>10s} {'wins':>6s} {'ties':>6s} {'losses':>7s}",
        "-" * 69,
    ]
    model_auc = scores[MODEL_NAME]["auc"]
    for name, s in scores.items():
        if name == MODEL_NAME:
            continue
        d = model_auc - s["auc"]
        wins, ties, losses = int((d > 1e-9).sum()), int((abs(d) <= 1e-9).sum()), int((d < -1e-9).sum())
        lines.append(f"{name:36s} {d.mean():+10.3f} {wins:6d} {ties:6d} {losses:7d}")

    lines += [
        "",
        "How to read this: a difference smaller than the ± std above is noise at",
        "this dataset size. If the model does not clearly beat the best single",
        "feature (mean diff well above 0 AND mostly wins), it is not demonstrably",
        "adding anything on this data.",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", default="data/sample_companies.json")
    parser.add_argument("--splits", type=int, default=5)
    parser.add_argument("--repeats", type=int, default=10)
    args = parser.parse_args()

    X, y, _ = load_dataset(args.data)
    print(f"Loaded {len(y)} usable records ({int(y.sum())} distressed, "
          f"{int((y == 0).sum())} healthy) from {args.data}\n")
    scores = run_cross_validation(X, y, n_splits=args.splits, n_repeats=args.repeats)
    print(format_report(scores, len(y)))


if __name__ == "__main__":
    main()
