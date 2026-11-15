"""
FastAPI inference service for the financial distress model.

Wraps predict.py's logic behind an HTTP API so it can run on AWS Lambda
(via a container image + API Gateway/Function URL) or any other container
host (ECS, App Runner, or just `uvicorn` on a VM for local testing).

Endpoints:
    GET  /health                 Liveness check
    POST /predict                Score a company given its financials + headlines
    POST /predict/demo/{ticker}  Score a company from the bundled synthetic dataset
    GET  /model/info             Current promoted model version + registry metadata
    GET  /companies              Nifty LargeMidcap 250 list for the dashboard (weekly snapshot)
    GET  /companies/{symbol}     Latest annual financials for one constituent
    GET  /lookup/{ticker}        Search a custom ticker (snapshot first, then live Yahoo)

Run locally:
    uvicorn app:app --host 0.0.0.0 --port 8000 --app-dir src

Then:
    curl -X POST http://localhost:8000/predict/demo/SYN027
"""

import json
import os
from typing import Optional

import numpy as np
import xgboost as xgb
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

import auth
from features import build_feature_row, financials_from_dict, FEATURE_NAMES
from altman_zscore import classify_zone
import model_loader
import market_data

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SAMPLE_DATA_PATH = os.environ.get(
    "SAMPLE_DATA_PATH", os.path.join(_SCRIPT_DIR, "..", "data", "sample_companies.json")
)

app = FastAPI(
    title="Financial Distress Screening API",
    description="Combines Altman Z-Score-style ratios with news sentiment to "
                "estimate a company's probability of financial distress. "
                "Research/screening tool only -- not investment advice.",
    version="0.1.0",
)


def get_model():
    """Delegates to model_loader, which prefers the S3/DynamoDB registry when
    MODEL_REGISTRY_TABLE + MODEL_BUCKET are set, falling back to a local file
    otherwise (e.g. for local dev/testing without AWS credentials)."""
    try:
        return model_loader.get_model()
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Could not load model: {e}. Train one with train_classifier.py, "
                    "or configure MODEL_REGISTRY_TABLE/MODEL_BUCKET for the S3 registry.",
        )


class FinancialsIn(BaseModel):
    total_assets: float
    total_liabilities: float
    current_assets: float
    current_liabilities: float
    retained_earnings: float
    ebit: float
    sales: float
    market_value_equity: Optional[float] = None
    book_value_equity: Optional[float] = None


class PredictRequest(BaseModel):
    ticker: str = Field(..., description="Ticker symbol, for display purposes only")
    financials: FinancialsIn
    headlines: list[str] = Field(default_factory=list)


class PredictResponse(BaseModel):
    ticker: str
    probability_distressed: float
    z_score: float
    z_score_zone: str
    z_double_prime: float
    z_double_prime_zone: str
    news_sentiment: float
    cash_burning: bool


class ModelInfoResponse(BaseModel):
    registry_configured: bool
    version: Optional[str] = None
    promoted_at: Optional[str] = None
    s3_key: Optional[str] = None


def _run_prediction(ticker: str, fin_dict: dict, headlines: list[str]) -> PredictResponse:
    model = get_model()
    fin = financials_from_dict(fin_dict)
    feats = build_feature_row(fin, headlines)
    x = np.array([[feats[name] for name in FEATURE_NAMES]])
    prob = float(model.predict_proba(x)[0, 1])

    return PredictResponse(
        ticker=ticker,
        probability_distressed=round(prob, 4),
        z_score=round(feats["z_score"], 3),
        z_score_zone=classify_zone(feats["z_score"], "z"),
        z_double_prime=round(feats["z_double_prime"], 3),
        z_double_prime_zone=classify_zone(feats["z_double_prime"], "zpp"),
        news_sentiment=round(feats["news_sentiment"], 3),
        cash_burning=bool(feats["cash_burn_flag"]),
    )


@app.get("/health")
def health():
    return {
        "status": "ok",
        "model_version": model_loader.current_version(),
        "registry_configured": bool(os.environ.get("MODEL_REGISTRY_TABLE")),
    }


@app.post("/predict", response_model=PredictResponse)
def predict(req: PredictRequest, claims: dict = Depends(auth.require_auth)):
    fin_dict = req.financials.model_dump()
    return _run_prediction(req.ticker, fin_dict, req.headlines)


@app.post("/predict/demo/{ticker}", response_model=PredictResponse)
def predict_demo(ticker: str, claims: dict = Depends(auth.require_auth)):
    """Convenience endpoint for testing against the bundled synthetic dataset."""
    if not os.path.exists(SAMPLE_DATA_PATH):
        raise HTTPException(status_code=404, detail="Sample dataset not found")
    with open(SAMPLE_DATA_PATH) as f:
        companies = json.load(f)
    match = next((c for c in companies if c["ticker"] == ticker), None)
    if match is None:
        raise HTTPException(status_code=404, detail=f"{ticker} not found in sample dataset")
    return _run_prediction(ticker, match["financials"], match.get("headlines", []))


@app.get("/model/info", response_model=ModelInfoResponse)
def model_info(claims: dict = Depends(auth.require_auth)):
    """Read-only view of the current promoted model. Reads the DynamoDB
    registry pointer directly rather than model_loader.get_model(), so a
    dashboard page load doesn't trigger an S3 download + model deserialization
    just to answer a metadata question."""
    table_name = os.environ.get("MODEL_REGISTRY_TABLE")
    if not table_name:
        return ModelInfoResponse(registry_configured=False)
    key_value = os.environ.get("MODEL_REGISTRY_KEY", "distress-classifier")
    item = model_loader._fetch_pointer(table_name, key_value)
    if item is None:
        return ModelInfoResponse(registry_configured=True, version=None)
    return ModelInfoResponse(
        registry_configured=True,
        version=item.get("version"),
        promoted_at=item.get("promoted_at"),
        s3_key=item.get("s3_key"),
    )


# --- Market data (dashboard ticker list + auto-fill) -------------------------
# Display data only; see market_data.py's docstring for why none of this may
# feed training.

class CompanySummary(BaseModel):
    symbol: str
    name: str
    industry: Optional[str] = None
    has_financials: bool
    as_of: Optional[str] = None


class CompaniesResponse(BaseModel):
    index: str
    available: bool
    generated_at: Optional[str] = None
    data_source: Optional[str] = None
    companies: list[CompanySummary] = Field(default_factory=list)


class CompanyFinancialsOut(BaseModel):
    symbol: str
    yahoo_ticker: str
    name: str
    industry: Optional[str] = None
    as_of: Optional[str] = None
    currency: Optional[str] = None
    source: str  # "snapshot" (weekly job) or "live" (fetched on request)
    fetched_at: Optional[str] = None
    financials: dict[str, Optional[float]]
    missing: list[str]
    complete: bool


class LookupResponse(BaseModel):
    query: str
    found: bool
    in_index: bool = False
    company: Optional[CompanyFinancialsOut] = None


def _company_out(rec: dict, source: str, fetched_at: Optional[str]) -> CompanyFinancialsOut:
    return CompanyFinancialsOut(
        symbol=rec["symbol"],
        yahoo_ticker=rec["yahoo_ticker"],
        name=rec["name"],
        industry=rec.get("industry"),
        as_of=rec.get("as_of"),
        currency=rec.get("currency"),
        source=source,
        fetched_at=fetched_at,
        financials=rec["financials"],
        missing=rec["missing"],
        complete=rec["complete"],
    )


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@app.get("/companies", response_model=CompaniesResponse)
def list_companies(claims: dict = Depends(auth.require_auth)):
    """Nifty LargeMidcap 250 constituents for the dashboard's ticker list.
    available=False until the weekly snapshot job has run at least once."""
    snap = market_data.load_snapshot()
    if not snap:
        return CompaniesResponse(index=market_data.INDEX_NAME, available=False)
    return CompaniesResponse(
        index=snap.get("index", market_data.INDEX_NAME),
        available=True,
        generated_at=snap.get("generated_at"),
        data_source=snap.get("data_source"),
        companies=[
            CompanySummary(
                symbol=c["symbol"],
                name=c["name"],
                industry=c.get("industry"),
                has_financials=c["complete"],
                as_of=c.get("as_of"),
            )
            for c in snap.get("companies", [])
        ],
    )


@app.get("/companies/{symbol}", response_model=CompanyFinancialsOut)
def company_financials(symbol: str, claims: dict = Depends(auth.require_auth)):
    """Latest annual financials for one index constituent, from the weekly
    snapshot. A constituent whose snapshot record is incomplete is retried
    live once, since Yahoo coverage is patchy week to week."""
    ticker = market_data.normalise_ticker(symbol)
    if ticker is None:
        raise HTTPException(status_code=400, detail="Invalid ticker")
    snap = market_data.load_snapshot()
    rec = market_data.find_company(snap, ticker)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"{ticker} is not in the {market_data.INDEX_NAME} snapshot")
    if rec["complete"]:
        return _company_out(rec, "snapshot", snap.get("generated_at"))
    live = market_data.live_lookup(rec["yahoo_ticker"])
    if live and len(live["missing"]) < len(rec["missing"]):
        live = {**live, "name": rec["name"], "industry": rec.get("industry"), "symbol": rec["symbol"]}
        return _company_out(live, "live", _now_iso())
    return _company_out(rec, "snapshot", snap.get("generated_at"))


@app.get("/lookup/{ticker}", response_model=LookupResponse)
def lookup_ticker(ticker: str, claims: dict = Depends(auth.require_auth)):
    """Search for a custom ticker. Index members come from the snapshot;
    anything else is fetched live from Yahoo Finance (bare tickers are tried
    as NSE, then BSE, then as-is)."""
    t = market_data.normalise_ticker(ticker)
    if t is None:
        raise HTTPException(status_code=400, detail="Invalid ticker")
    snap = market_data.load_snapshot()
    rec = market_data.find_company(snap, t) if "." not in t or t.endswith(".NS") else None
    if rec is not None and rec["complete"]:
        return LookupResponse(query=t, found=True, in_index=True,
                              company=_company_out(rec, "snapshot", snap.get("generated_at")))
    live = market_data.live_lookup(t)
    if live is None:
        return LookupResponse(query=t, found=False, in_index=rec is not None)
    if rec is not None:
        live = {**live, "name": rec["name"], "industry": rec.get("industry"), "symbol": rec["symbol"]}
    return LookupResponse(query=t, found=True, in_index=rec is not None,
                          company=_company_out(live, "live", _now_iso()))


# --- AWS Lambda entry point -------------------------------------------------
# Only imported/used when running inside Lambda; harmless to leave in for
# other deployment targets since it's not invoked unless Lambda calls `handler`.
try:
    from mangum import Mangum
    handler = Mangum(app)
except ImportError:
    handler = None  # not running in/for Lambda; fine for local uvicorn or ECS
