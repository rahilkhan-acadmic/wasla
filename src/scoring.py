"""
One place that turns financials into a distress score, shared by the API's
single-company endpoints (/predict, /predict/demo) and the market overview
(/market/overview), so a company scores exactly the same either way.

Risk bands use the same cut-offs the dashboard has always shown:
    probability < 0.33  -> low
    probability < 0.66  -> moderate
    otherwise           -> high
"""

from typing import Iterable, Optional

import numpy as np

from altman_zscore import classify_zone
from features import FEATURE_NAMES, build_feature_row, financials_from_dict

BAND_MODERATE = 0.33
BAND_HIGH = 0.66


def risk_band(probability: float) -> str:
    if probability < BAND_MODERATE:
        return "low"
    if probability < BAND_HIGH:
        return "moderate"
    return "high"


def _result(prob: float, feats: dict) -> dict:
    return {
        "probability_distressed": round(prob, 4),
        "z_score": round(feats["z_score"], 3),
        "z_score_zone": classify_zone(feats["z_score"], "z"),
        "z_double_prime": round(feats["z_double_prime"], 3),
        "z_double_prime_zone": classify_zone(feats["z_double_prime"], "zpp"),
        "news_sentiment": round(feats["news_sentiment"], 3),
        "cash_burning": bool(feats["cash_burn_flag"]),
    }


def score_one(model, fin_dict: dict, headlines: Optional[list[str]] = None) -> dict:
    """Score a single company. Raises on unusable financials (e.g. zero
    total assets), which the API turns into an error response."""
    feats = build_feature_row(financials_from_dict(fin_dict), headlines or [])
    x = np.array([[feats[name] for name in FEATURE_NAMES]])
    prob = float(model.predict_proba(x)[0, 1])
    return _result(prob, feats)


def score_many(model, fin_dicts: Iterable[dict]) -> list[dict]:
    """Score many companies in one model call. A company whose financials
    can't be turned into features gets {"error": ...} instead of a score, so
    one bad record never sinks the batch. No headlines are used (the
    news_sentiment feature is a constant 0.0 for now, see CLAUDE.md)."""
    rows, feats_list, results = [], [], []
    for d in fin_dicts:
        try:
            feats = build_feature_row(financials_from_dict(d), [])
            rows.append([feats[name] for name in FEATURE_NAMES])
            feats_list.append(feats)
            results.append(None)  # filled below
        except Exception as e:
            results.append({"error": f"{type(e).__name__}: {e}"[:200]})

    if rows:
        probs = model.predict_proba(np.array(rows))[:, 1]
        it = iter(zip(probs, feats_list))
        for i, r in enumerate(results):
            if r is None:
                prob, feats = next(it)
                results[i] = _result(float(prob), feats)
    return results
