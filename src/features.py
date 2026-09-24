"""
Combine structured financial ratios (Altman-style) with text-derived sentiment
into a single feature vector for the distress classifier.
"""

from dataclasses import asdict
from altman_zscore import Financials, z_score, z_double_prime_score
from sentiment import score_documents


FEATURE_NAMES = [
    "working_capital_ratio",
    "retained_earnings_ratio",
    "ebit_margin_on_assets",
    "leverage_ratio",          # total_liabilities / total_assets
    "asset_turnover",
    "z_score",
    "z_double_prime",
    "news_sentiment",
    "cash_burn_flag",          # 1 if EBIT < 0, else 0 -- cheap distress signal
]

# The 7 core financial fields every ratio calculation in this file depends
# on. A record missing ANY of these -- not just total_assets -- will crash
# build_feature_row with a TypeError (dividing by/on None). This was a real
# bug: data source builders originally only checked total_assets before
# accepting a record, so a company reporting assets but filing revenue under
# an unrecognized XBRL tag (giving sales=None) got included and crashed
# training. Every market plugin AND load_dataset() below now check this.
REQUIRED_FINANCIAL_FIELDS = [
    "total_assets", "total_liabilities", "current_assets",
    "current_liabilities", "retained_earnings", "ebit", "sales",
]


def has_complete_financials(fin_dict: dict) -> bool:
    """True only if every field build_feature_row's ratios need is present
    and non-None. Use this to filter records BEFORE they reach training,
    rather than letting a partial record crash a ratio calculation."""
    return all(fin_dict.get(f) is not None for f in REQUIRED_FINANCIAL_FIELDS)


def build_feature_row(fin: Financials, news_headlines: list[str] | None = None) -> dict:
    """Turn one company's financials + recent headlines into a flat feature dict."""
    news_headlines = news_headlines or []

    working_capital_ratio = fin.working_capital() / fin.total_assets
    retained_earnings_ratio = fin.retained_earnings / fin.total_assets
    ebit_margin_on_assets = fin.ebit / fin.total_assets
    leverage_ratio = fin.total_liabilities / fin.total_assets
    asset_turnover = fin.sales / fin.total_assets

    zs = z_score(fin)
    zpp = z_double_prime_score(fin)
    sentiment = score_documents(news_headlines)
    cash_burn_flag = 1.0 if fin.ebit < 0 else 0.0

    return {
        "working_capital_ratio": working_capital_ratio,
        "retained_earnings_ratio": retained_earnings_ratio,
        "ebit_margin_on_assets": ebit_margin_on_assets,
        "leverage_ratio": leverage_ratio,
        "asset_turnover": asset_turnover,
        "z_score": zs,
        "z_double_prime": zpp,
        "news_sentiment": sentiment,
        "cash_burn_flag": cash_burn_flag,
    }


def financials_from_dict(d: dict) -> Financials:
    """Build a Financials object from a plain dict (e.g. loaded JSON/request body),
    filling sensible defaults for equity fields when they're missing or None."""
    d = dict(d)  # copy

    book_value_equity = d.get("book_value_equity")
    if book_value_equity is None:
        book_value_equity = d["total_assets"] - d["total_liabilities"]
    d["book_value_equity"] = book_value_equity

    if d.get("market_value_equity") is None:
        d["market_value_equity"] = book_value_equity

    return Financials(**d)
