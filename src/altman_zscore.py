"""
Altman Z-Score calculators.

Two variants are implemented:
  * Original Z-Score  - designed for publicly traded MANUFACTURING firms.
  * Z''-Score (Z double-prime) - designed for private / non-manufacturing /
    emerging-market firms. Since most penny stocks are small, non-manufacturing,
    thinly-traded companies, Z'' is usually the more appropriate variant --
    but both are provided so you can compare.

Reference (classic, publicly documented formulas):
    Z  = 1.2*A + 1.4*B + 3.3*C + 0.6*D + 1.0*E
    Z'' = 6.56*A + 3.26*B + 6.72*C + 1.05*D

Where:
    A = Working Capital / Total Assets
    B = Retained Earnings / Total Assets
    C = EBIT / Total Assets
    D = Market Value of Equity / Total Liabilities   (Book Value of Equity for Z'')
    E = Sales / Total Assets   (used only in original Z)
"""

from dataclasses import dataclass


@dataclass
class Financials:
    """Minimal set of line items needed to compute Z-Scores.

    All values should be in the same currency unit (e.g. USD), for a single
    reporting period. These map directly onto SEC XBRL / EDGAR "companyfacts"
    tags -- see edgar_client.py for exact tag names used to populate this.
    """
    total_assets: float
    total_liabilities: float
    current_assets: float
    current_liabilities: float
    retained_earnings: float
    ebit: float                # Earnings Before Interest & Taxes
    sales: float                # Total revenue
    market_value_equity: float  # shares_outstanding * share_price
    book_value_equity: float    # total_assets - total_liabilities (fallback)

    def working_capital(self) -> float:
        return self.current_assets - self.current_liabilities


def z_score(f: Financials) -> float:
    """Original Altman Z-Score (public manufacturing firms)."""
    if f.total_assets == 0 or f.total_liabilities == 0:
        raise ValueError("total_assets and total_liabilities must be non-zero")

    a = f.working_capital() / f.total_assets
    b = f.retained_earnings / f.total_assets
    c = f.ebit / f.total_assets
    d = f.market_value_equity / f.total_liabilities
    e = f.sales / f.total_assets

    return 1.2 * a + 1.4 * b + 3.3 * c + 0.6 * d + 1.0 * e


def z_double_prime_score(f: Financials, use_market_value: bool = False) -> float:
    """Z''-Score (private firms / non-manufacturers / EM firms) -- generally
    the better fit for small-cap and penny stocks."""
    if f.total_assets == 0 or f.total_liabilities == 0:
        raise ValueError("total_assets and total_liabilities must be non-zero")

    equity = f.market_value_equity if use_market_value else f.book_value_equity

    a = f.working_capital() / f.total_assets
    b = f.retained_earnings / f.total_assets
    c = f.ebit / f.total_assets
    d = equity / f.total_liabilities

    return 6.56 * a + 3.26 * b + 6.72 * c + 1.05 * d


def classify_zone(score: float, variant: str = "z") -> str:
    """Bucket a Z-Score into Altman's traditional risk zones.

    Thresholds differ slightly by variant; using the commonly cited cutoffs.
    """
    if variant == "z":
        if score > 2.99:
            return "safe"
        elif score > 1.81:
            return "grey"
        else:
            return "distress"
    else:  # z''
        if score > 2.6:
            return "safe"
        elif score > 1.1:
            return "grey"
        else:
            return "distress"
