"""
Generates a SYNTHETIC dataset of fictional companies for demo/testing purposes
only. This lets the whole pipeline (features -> training -> evaluation) run
end-to-end without needing live SEC/EDGAR network access or real bankruptcy
labels.

*** DO NOT use this synthetic data to draw any real financial conclusions. ***
Replace this with real data via src/edgar_client.py + a real distress-event
label source (see README) before doing anything beyond pipeline testing.
"""

import json
import random

random.seed(42)

HEALTHY_HEADLINE_POOL = [
    "Company beats earnings estimates for third consecutive quarter.",
    "Board approves share buyback program citing strong balance sheet.",
    "New product line drives double-digit revenue growth.",
    "Analysts upgrade stock following strong guidance.",
    "Company expands into new international markets.",
]

DISTRESS_HEADLINE_POOL = [
    "Auditor flags going concern doubt in latest annual report.",
    "Company delays quarterly filing amid accounting review.",
    "CFO resigns abruptly as cash reserves dwindle.",
    "Lender tightens covenant terms after missed debt payment.",
    "Company announces layoffs and facility closures to cut costs.",
    "Stock delisted from major exchange for failing to meet listing standards.",
]


def make_company(is_distressed: bool, idx: int) -> dict:
    if is_distressed:
        total_assets = random.uniform(5_000_000, 80_000_000)
        total_liabilities = total_assets * random.uniform(0.85, 1.4)  # often insolvent
        current_assets = total_assets * random.uniform(0.15, 0.35)
        current_liabilities = total_assets * random.uniform(0.30, 0.55)
        retained_earnings = -total_assets * random.uniform(0.2, 0.9)  # accumulated deficit
        ebit = -total_assets * random.uniform(0.05, 0.30)             # losing money
        sales = total_assets * random.uniform(0.1, 0.6)
        headlines = random.sample(DISTRESS_HEADLINE_POOL, k=random.randint(1, 3))
        label = 1
    else:
        total_assets = random.uniform(20_000_000, 500_000_000)
        total_liabilities = total_assets * random.uniform(0.2, 0.55)
        current_assets = total_assets * random.uniform(0.25, 0.5)
        current_liabilities = total_assets * random.uniform(0.1, 0.25)
        retained_earnings = total_assets * random.uniform(0.05, 0.4)
        ebit = total_assets * random.uniform(0.03, 0.18)
        sales = total_assets * random.uniform(0.4, 1.3)
        headlines = random.sample(HEALTHY_HEADLINE_POOL, k=random.randint(1, 3))
        label = 0

    book_value_equity = total_assets - total_liabilities
    market_value_equity = book_value_equity * random.uniform(0.5, 1.8)  # market can disagree w/ book

    return {
        "ticker": f"SYN{idx:03d}",
        "financials": {
            "total_assets": round(total_assets, 2),
            "total_liabilities": round(total_liabilities, 2),
            "current_assets": round(current_assets, 2),
            "current_liabilities": round(current_liabilities, 2),
            "retained_earnings": round(retained_earnings, 2),
            "ebit": round(ebit, 2),
            "sales": round(sales, 2),
            "market_value_equity": round(market_value_equity, 2),
            "book_value_equity": round(book_value_equity, 2),
        },
        "headlines": headlines,
        "label_distressed": label,
    }


def generate(n_per_class: int = 60) -> list[dict]:
    companies = []
    for i in range(n_per_class):
        companies.append(make_company(is_distressed=True, idx=i))
    for i in range(n_per_class, 2 * n_per_class):
        companies.append(make_company(is_distressed=False, idx=i))
    random.shuffle(companies)
    return companies


if __name__ == "__main__":
    data = generate(n_per_class=60)
    with open("data/sample_companies.json", "w") as f:
        json.dump(data, f, indent=2)
    print(f"Wrote {len(data)} synthetic companies to data/sample_companies.json")
