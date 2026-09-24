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
