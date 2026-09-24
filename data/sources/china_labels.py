"""
China distress labels via the ST/*ST special-treatment system -- arguably
the cleanest label mechanism of any market in this project.

THE LABEL SIDE IS THE BEST OF ANY MARKET HERE:
Since 2001, the Shanghai and Shenzhen Stock Exchanges (under CSRC rules)
prefix a company's own STOCK SHORT NAME with "ST" (Special Treatment) or
"*ST" (delisting risk warning) when it meets defined financial-distress
criteria -- two consecutive years of losses, revenue below an exchange
threshold, an audit disclaimer, etc. This is used as the standard financial
distress label in published Chinese-market academic research (see e.g.
Zhou, "Predicting the Removal of Special Treatment or Delisting Warning...").
Unlike every other market in this project, you don't need a search API or
a curated list at all -- just the current roster of A-share names, and you
filter for the "ST"/"*ST" prefix directly.

TOOLING CHOICE: AKSHARE, NOT YFINANCE.
Unlike India (where yfinance works reasonably well with .NS/.BO), Yahoo
Finance's coverage of Chinese A-shares is known to be unreliable. AKShare
(https://github.com/akfamily/akshare) is the standard free, open-source
library the Chinese quant research community actually uses for this market,
and is used here instead, for both the ST/*ST roster and financial
statements.

IMPORTANT CAVEATS -- read before trusting this:
  - AKShare wraps several underlying Chinese data providers (Eastmoney,
    Sina, etc.) and its function names/return columns have historically
    shifted more often than SEC EDGAR's stable government API. The function
    names and column mappings below are written in good faith but were NOT
    verified against a live akshare install -- this sandbox has no network
    access to test them. Run `pip install akshare` and sanity-check
    `ak.stock_zh_a_spot_em()`'s actual columns before trusting this fully.
  - Financial statement field names come back in Chinese by default
    (e.g. 资产总计 = total assets); the mapping below is a best-effort guess
    at the current column names and should be verified.
  - As with India, there's no as_of_date leakage protection here yet --
    AKShare's historical financial statement depth/dating conventions would
    need investigation before this is safe for point-in-time labeling.
"""

import os
import sys
import time
import random

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))
from features import has_complete_financials  # noqa: E402

MARKET_CODE = "china"
MARKET_LABEL = "China (Shanghai/Shenzhen A-shares, via AKShare)"
MARKET_REGION = "East Asia"

# Best-effort mapping from AKShare's (Chinese) balance-sheet/income-statement
# column names to this project's schema. VERIFY against a live akshare call
# before trusting -- see module docstring.
FIELD_MAP = {
    "total_assets": "资产总计",
    "total_liabilities": "负债合计",
    "current_assets": "流动资产合计",
    "current_liabilities": "流动负债合计",
    "retained_earnings": "未分配利润",
    "ebit": "营业利润",
    "sales": "营业总收入",
}


def add_cli_args(parser) -> None:
    """Registers this market's own CLI arguments onto the shared parser --
    part of the plugin contract, see data/build_dataset.py."""
    group = parser.add_argument_group(f"{MARKET_LABEL} options")
    group.add_argument("--china-n-distressed", type=int, default=30)
    group.add_argument("--china-n-healthy", type=int, default=30)


def _get_a_share_roster():
    """Full current A-share roster with short names, via AKShare.
    Returns a DataFrame with (at least) columns for ticker code and name --
    verify actual column names against your akshare version."""
    import akshare as ak
    return ak.stock_zh_a_spot_em()


def find_st_companies(roster, max_results: int) -> list[dict]:
    """Filters the roster for ST/*ST-prefixed names -- the actual label
    mechanism, no search API needed."""
    name_col = "名称"  # "name" column -- verify against your akshare version
    code_col = "代码"  # "code" column

    st_mask = roster[name_col].str.contains(r"^\*?ST", regex=True, na=False)
    st_rows = roster[st_mask].head(max_results)

    return [
        {"code": row[code_col], "name": row[name_col]}
        for _, row in st_rows.iterrows()
    ]


def find_healthy_sample(roster, exclude_codes: set, max_results: int) -> list[dict]:
    """Random sample of non-ST companies from the same roster."""
    name_col, code_col = "名称", "代码"
    healthy_pool = roster[~roster[code_col].isin(exclude_codes)]
    healthy_pool = healthy_pool[~healthy_pool[name_col].str.contains(r"^\*?ST", regex=True, na=False)]
    sample = healthy_pool.sample(n=min(max_results, len(healthy_pool)), random_state=42)
    return [{"code": row[code_col], "name": row[name_col]} for _, row in sample.iterrows()]


def _fetch_financials(code: str, polite_delay: float = 0.3) -> dict:
    """Fetches balance sheet + income statement for one A-share code via
    AKShare and maps to this project's schema. Best-effort function/column
    names -- see module docstring."""
    import akshare as ak
    time.sleep(polite_delay)

    out = {field: None for field in FIELD_MAP}
    try:
        balance_sheet = ak.stock_balance_sheet_by_report_em(symbol=code)
        income_stmt = ak.stock_profit_sheet_by_report_em(symbol=code)
    except Exception as e:
        print(f"  Could not fetch statements for {code}: {e}")
        return out

    for field, cn_column in FIELD_MAP.items():
        for df in (balance_sheet, income_stmt):
            if df is not None and cn_column in df.columns and len(df) > 0:
                try:
                    out[field] = float(df.iloc[0][cn_column])
                    break
                except (ValueError, TypeError):
                    continue

    return out


def build_china_labeled_dataset(n_distressed: int = 30, n_healthy: int = 30) -> list[dict]:
    print("Fetching current A-share roster via AKShare...")
    roster = _get_a_share_roster()
    print(f"  Roster has {len(roster)} companies")

    print("Filtering for ST/*ST (special treatment / delisting risk) names...")
    st_companies = find_st_companies(roster, n_distressed)
    print(f"  Found {len(st_companies)} ST/*ST companies")

    exclude = {c["code"] for c in st_companies}
    healthy = find_healthy_sample(roster, exclude, n_healthy)
    print(f"  Sampled {len(healthy)} healthy comparison companies")

    records = []
    for c in st_companies:
        fin = _fetch_financials(c["code"])
        if not has_complete_financials(fin):
            continue
        records.append({
            "ticker": f"CN-{c['code']}",
            "company_name": c["name"],
            "market": "china",
            "financials": fin,
            "headlines": [f"{c['name']}: carries ST/*ST special treatment designation"],
            "label_distressed": 1,
            "event_date": None,  # AKShare roster is a current snapshot, not dated history
            "source": "CSRC/exchange ST or *ST designation (via AKShare roster)",
        })
    for c in healthy:
        fin = _fetch_financials(c["code"])
        if not has_complete_financials(fin):
            continue
        records.append({
            "ticker": f"CN-{c['code']}",
            "company_name": c["name"],
            "market": "china",
            "financials": fin,
            "headlines": [],
            "label_distressed": 0,
            "event_date": None,
            "source": "No ST/*ST designation (via AKShare roster)",
        })

    return records


def build(args) -> list[dict]:
    """Plugin entry point -- see data/build_dataset.py's MARKET_REGISTRY."""
    return build_china_labeled_dataset(
        n_distressed=args.china_n_distressed, n_healthy=args.china_n_healthy,
    )
