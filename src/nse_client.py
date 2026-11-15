"""
Indian market data client -- drop-in replacement for edgar_client.py's role,
built on yfinance since India doesn't have a free structured filings API
equivalent to SEC EDGAR.

Usage: append .NS for NSE or .BO for BSE to the ticker, e.g.:
    RELIANCE.NS, TCS.NS, INFY.NS, RELIANCE.BO

IMPORTANT:
  - Needs outbound internet access to Yahoo Finance's endpoints -- won't work
    in network-sandboxed environments. Run on your own machine/server.
  - yfinance's financial statement coverage for small/micro-caps (i.e. many
    penny stocks) is inconsistent -- some line items may come back missing.
    For anything beyond a quick prototype, budget for Screener.in's paid API
    or NSE/BSE data directly (see README) for more reliable small-cap coverage.
  - Unlike SEC EDGAR, yfinance DOES give you live market cap directly, so
    market_value_equity is populated automatically here (an advantage over
    the US EDGAR path, which needs a separate price source).
"""

import time
from typing import Optional

import yfinance as yf

# Maps our internal field names -> possible row labels yfinance uses in its
# balance_sheet / income_stmt DataFrames. Labels can vary slightly by company/
# reporting standard, so a few aliases are listed per concept.
BALANCE_SHEET_ALIASES = {
    "total_assets": ["Total Assets"],
    "total_liabilities": ["Total Liabilities Net Minority Interest", "Total Liab"],
    "current_assets": ["Current Assets"],
    "current_liabilities": ["Current Liabilities"],
    "retained_earnings": ["Retained Earnings"],
}
INCOME_STMT_ALIASES = {
    "ebit": ["EBIT", "Operating Income"],
    "sales": ["Total Revenue"],
}


def _first_available(df, aliases: list[str]) -> Optional[float]:
    """Return the most recent (first column) value for the first matching
    row label found in a yfinance financial statement DataFrame."""
    if df is None or df.empty:
        return None
    for label in aliases:
        if label in df.index:
            series = df.loc[label].dropna()
            if not series.empty:
                return float(series.iloc[0])  # most recent period
    return None


def fetch_financials_for_ticker(ticker: str, polite_delay: float = 0.5) -> dict:
    """Ticker (with .NS or .BO suffix) -> extracted financial fields dict,
    same shape as edgar_client.fetch_financials_for_ticker's output."""
    t = yf.Ticker(ticker)
    time.sleep(polite_delay)  # be polite to Yahoo's endpoints

    balance_sheet = t.balance_sheet
    income_stmt = t.income_stmt

    out = {}
    for field, aliases in BALANCE_SHEET_ALIASES.items():
        out[field] = _first_available(balance_sheet, aliases)
    for field, aliases in INCOME_STMT_ALIASES.items():
        out[field] = _first_available(income_stmt, aliases)

    # yfinance gives us live market cap directly -- a real advantage over
    # EDGAR, which has no price data at all.
    try:
        out["market_value_equity"] = t.fast_info.get("marketCap")
    except Exception:
        out["market_value_equity"] = t.info.get("marketCap")

    if out.get("total_assets") is not None and out.get("total_liabilities") is not None:
        out["book_value_equity"] = out["total_assets"] - out["total_liabilities"]
    else:
        out["book_value_equity"] = None

    return out


def _value_at(df, aliases: list[str], column) -> Optional[float]:
    """Value of the first alias row that is non-null in exactly `column`.
    Unlike _first_available(), never falls back to an older period."""
    if df is None or df.empty or column is None or column not in df.columns:
        return None
    for label in aliases:
        if label in df.index:
            v = df.at[label, column]
            if v is not None and v == v:  # not None / NaN
                return float(v)
    return None


def _latest_column(df, aliases: list[str]):
    """Newest period column in which the first available alias row has a value."""
    if df is None or df.empty:
        return None
    for label in aliases:
        if label in df.index:
            series = df.loc[label].dropna()
            if not series.empty:
                return series.index[0]
    return None


def fetch_financials_with_period(ticker: str, polite_delay: float = 0.5, with_name: bool = False) -> dict:
    """fetch_financials_for_ticker's fields plus, for display:
        as_of     period-end date of the latest annual balance sheet
        currency  currency of the financial statements (Yahoo's
                  financialCurrency; usually INR for .NS/.BO, but e.g. USD
                  for Infosys)
        currency_mismatch  True when that differs from the trading
                  currency; market_value_equity is then None (see below)
        name      company short name (only when with_name=True)
    Used by market_data.py for the dashboard's ticker auto-fill. Not used by
    training, which has its own as-of handling."""
    t = yf.Ticker(ticker)
    time.sleep(polite_delay)

    balance_sheet = t.balance_sheet
    income_stmt = t.income_stmt

    # Every figure comes from ONE fiscal year: the latest balance sheet's
    # period, and the income statement column for the same period-end (or
    # its newest column if the dates don't line up). A gap is left missing
    # rather than filled from an older year -- mixing years would put a
    # misleading "as of" label on the auto-filled form.
    bs_col = _latest_column(balance_sheet, BALANCE_SHEET_ALIASES["total_assets"])
    if income_stmt is not None and not income_stmt.empty:
        inc_col = bs_col if bs_col in income_stmt.columns else income_stmt.columns[0]
    else:
        inc_col = None

    out = {}
    for field, aliases in BALANCE_SHEET_ALIASES.items():
        out[field] = _value_at(balance_sheet, aliases, bs_col)
    for field, aliases in INCOME_STMT_ALIASES.items():
        out[field] = _value_at(income_stmt, aliases, inc_col)

    try:
        fi = t.fast_info
        market_cap = fi.get("marketCap")
        trading_currency = fi.get("currency")
    except Exception:
        market_cap, trading_currency = None, None

    # The statements' currency can differ from the trading currency: e.g.
    # Infosys trades in INR on NSE but Yahoo carries its USD statements.
    # Mixing an INR market cap with USD liabilities inflates the Altman
    # market-value ratio ~85x, so it's read every time (one extra request).
    info = {}
    try:
        info = t.info or {}
    except Exception:
        pass
    financial_currency = info.get("financialCurrency") or trading_currency
    out["currency"] = financial_currency
    out["currency_mismatch"] = bool(
        financial_currency and trading_currency and financial_currency != trading_currency
    )
    # On a mismatch, drop the market cap rather than convert it: features.py
    # then falls back to book value of equity, as it does for any missing
    # market cap. An FX conversion would need a rate source and a date policy.
    out["market_value_equity"] = None if out["currency_mismatch"] else market_cap

    if out.get("total_assets") is not None and out.get("total_liabilities") is not None:
        out["book_value_equity"] = out["total_assets"] - out["total_liabilities"]
    else:
        out["book_value_equity"] = None

    out["as_of"] = bs_col.strftime("%Y-%m-%d") if hasattr(bs_col, "strftime") else (str(bs_col)[:10] if bs_col is not None else None)

    if with_name:
        out["name"] = info.get("shortName") or info.get("longName")

    return out


def fetch_recent_news_headlines(ticker: str, max_items: int = 10) -> list[str]:
    """Pull recent headlines for a ticker via yfinance's news feed, for
    feeding into sentiment.py. Coverage for small/micro-caps is often thin --
    supplement with a dedicated news API for anything beyond a quick check."""
    t = yf.Ticker(ticker)
    try:
        news = t.news or []
    except Exception:
        news = []
    return [item.get("title", "") for item in news[:max_items] if item.get("title")]


if __name__ == "__main__":
    import sys
    import json

    if len(sys.argv) != 2:
        print("Usage: python nse_client.py TICKER.NS   (or TICKER.BO for BSE)")
        sys.exit(1)

    ticker = sys.argv[1]
    fields = fetch_financials_for_ticker(ticker)
    print(json.dumps(fields, indent=2))
    print("\nRecent headlines:")
    for h in fetch_recent_news_headlines(ticker):
        print(f"  - {h}")
