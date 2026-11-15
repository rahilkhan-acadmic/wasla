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
    GET  /companies              Index constituents for the dashboard (weekly snapshot);
                                 ?universe=nse (Nifty LargeMidcap 250, default) | us (S&P 500)
    GET  /companies/{symbol}     Latest annual financials for one constituent (?universe= as above)
    GET  /lookup/{ticker}        Search a custom ticker (snapshot first, then live Yahoo)
    GET  /search?q=              Find companies by ticker (3+ chars) or name (5+ chars), both indexes
    GET  /market/overview        A whole index scored with the current model: risk bands +
                                 loss-making count (?universe= as above)
    GET  /market/refresh         State of the index's data refresh (?universe= as above)
    POST /market/refresh         Start a refresh now instead of waiting for Sunday (409 if one is running)

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
from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

import auth
from features import build_feature_row, financials_from_dict, FEATURE_NAMES
from altman_zscore import classify_zone
import model_loader
import market_data
import scoring

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
    return PredictResponse(ticker=ticker, **scoring.score_one(model, fin_dict, headlines))


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
    note: Optional[str] = None  # e.g. statements in a different currency


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
        note=rec.get("note"),
    )


UniverseParam = Query("nse", description="nse = Nifty LargeMidcap 250, us = S&P 500")


def _universe(universe_id: str) -> "market_data.Universe":
    try:
        return market_data.get_universe(universe_id)
    except KeyError:
        raise HTTPException(status_code=400,
                            detail=f"Unknown universe {universe_id!r}; use one of: {', '.join(market_data.UNIVERSES)}")


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@app.get("/companies", response_model=CompaniesResponse)
def list_companies(universe: str = UniverseParam, claims: dict = Depends(auth.require_auth)):
    """An index's constituents for the dashboard's ticker list.
    available=False until the weekly snapshot job has run at least once."""
    u = _universe(universe)
    snap = market_data.load_snapshot(universe=u.id)
    if not snap:
        return CompaniesResponse(index=u.index, available=False)
    return CompaniesResponse(
        index=snap.get("index", u.index),
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
def company_financials(symbol: str, universe: str = UniverseParam,
                       claims: dict = Depends(auth.require_auth)):
    """Latest annual financials for one index constituent, from the weekly
    snapshot. A constituent whose snapshot record is incomplete is retried
    live once, since Yahoo coverage is patchy week to week."""
    u = _universe(universe)
    ticker = market_data.normalise_ticker(symbol)
    if ticker is None:
        raise HTTPException(status_code=400, detail="Invalid ticker")
    snap = market_data.load_snapshot(universe=u.id)
    rec = market_data.find_company(snap, ticker)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"{ticker} is not in the {u.index} snapshot")
    if rec["complete"]:
        return _company_out(rec, "snapshot", snap.get("generated_at"))
    live = market_data.live_lookup(rec["yahoo_ticker"])
    if live and len(live["missing"]) < len(rec["missing"]):
        live = {**live, "name": rec["name"], "industry": rec.get("industry"), "symbol": rec["symbol"]}
        return _company_out(live, "live", _now_iso())
    return _company_out(rec, "snapshot", snap.get("generated_at"))


@app.get("/lookup/{ticker}", response_model=LookupResponse)
def lookup_ticker(ticker: str, claims: dict = Depends(auth.require_auth)):
    """Search for a custom ticker. Index members come from the snapshots
    (Nifty LargeMidcap 250 first, then the S&P 500); anything else is
    fetched live from Yahoo Finance (bare tickers are tried as NSE, then
    BSE, then as-is)."""
    t = market_data.normalise_ticker(ticker)
    if t is None:
        raise HTTPException(status_code=400, detail="Invalid ticker")
    snap = market_data.load_snapshot()
    rec = market_data.find_company(snap, t) if "." not in t or t.endswith(".NS") else None
    if rec is None and not t.endswith((".NS", ".BO")):
        us = market_data.load_snapshot(universe="us")
        us_rec = market_data.find_company(us, t)
        if us_rec is not None:
            snap, rec = us, us_rec
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


class SearchResult(BaseModel):
    symbol: str
    yahoo_ticker: str
    name: str
    exchange: Optional[str] = None
    industry: Optional[str] = None
    in_index: bool
    has_financials: Optional[bool] = None
    universe: Optional[str] = None      # index the company is in: nse | us, else None
    index_label: Optional[str] = None   # e.g. "LargeMidcap 250", "S&P 500"


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]
    online_ok: bool  # False when Yahoo search failed and only index matches are shown


@app.get("/search", response_model=SearchResponse)
def search(q: str, claims: dict = Depends(auth.require_auth)):
    """Find companies by ticker (3+ characters) or name (5+ characters):
    Nifty LargeMidcap 250 and S&P 500 members from the snapshots first,
    then Yahoo Finance matches beyond them."""
    query = market_data.normalise_query(q)
    if query is None:
        raise HTTPException(
            status_code=400,
            detail=f"Search needs {market_data.MIN_TICKER_QUERY}-40 characters: letters, digits, spaces or & . - '",
        )
    snapshots = [market_data.load_snapshot(universe=uid) for uid in market_data.UNIVERSES]
    return SearchResponse(**market_data.search_companies(query, snapshots))


# --- Market overview (a whole index, scored with the live model) --------------

class OverviewCompany(BaseModel):
    symbol: str
    name: str
    industry: Optional[str] = None
    as_of: Optional[str] = None
    probability_distressed: float
    band: str  # low | moderate | high
    z_score: float
    z_score_zone: str
    z_double_prime: float
    z_double_prime_zone: str
    loss_making: bool


class UnscoredCompany(BaseModel):
    symbol: str
    name: str
    industry: Optional[str] = None
    # "not_applicable": a bank/NBFC/insurer -- no current assets/liabilities
    #   split, so the Altman-style features don't exist for it.
    # "missing_data": the source lacked a figure the model needs.
    # "error": figures present but unusable (e.g. zero total assets).
    category: str
    reason: str


class MarketOverviewResponse(BaseModel):
    index: str
    universe: str = "nse"
    available: bool
    snapshot_generated_at: Optional[str] = None
    model_version: Optional[str] = None
    thresholds: dict[str, float] = Field(
        default_factory=lambda: {"moderate": scoring.BAND_MODERATE, "high": scoring.BAND_HIGH})
    total: int = 0
    scored: int = 0
    bands: dict[str, int] = Field(default_factory=lambda: {"low": 0, "moderate": 0, "high": 0})
    # Loss-making = EBIT below zero in the latest annual figures. Counted over
    # every company whose EBIT is known (not only fully scored ones), and
    # reported separately because it overlaps the risk bands.
    loss_making: int = 0
    ebit_known: int = 0
    companies: list[OverviewCompany] = Field(default_factory=list)
    unscored: list[UnscoredCompany] = Field(default_factory=list)


_overview_cache: dict = {}  # universe -> {"key": (generated_at, model version), "value": ...}


def _is_financial_balance_sheet(c: dict, u: "market_data.Universe") -> bool:
    """Banks, NBFCs and insurers present an unclassified balance sheet (no
    current/non-current split). In the first real NSE snapshot (2026-11-15)
    that was 41 of the 47 incomplete companies, all in NSE's Financial
    Services industry; the S&P 500's equivalent is the GICS Financials sector."""
    missing = set(c.get("missing") or [])
    return c.get("industry") in u.financial_industries and bool(
        missing & {"current_assets", "current_liabilities"})


def _build_overview(snap: dict, model, model_version: Optional[str],
                    u: Optional["market_data.Universe"] = None) -> MarketOverviewResponse:
    u = u or market_data.get_universe(snap.get("universe"))
    companies = snap.get("companies", [])
    complete = [c for c in companies if c.get("complete")]
    scores = scoring.score_many(model, (c["financials"] for c in complete))

    out = MarketOverviewResponse(
        index=snap.get("index", u.index),
        universe=u.id,
        available=True,
        snapshot_generated_at=snap.get("generated_at"),
        model_version=model_version,
        total=len(companies),
    )
    for c, s in zip(complete, scores):
        if "error" in s:
            out.unscored.append(UnscoredCompany(symbol=c["symbol"], name=c["name"],
                                                industry=c.get("industry"), category="error",
                                                reason=f"Could not score: {s['error']}"))
            continue
        band = scoring.risk_band(s["probability_distressed"])
        out.bands[band] += 1
        out.companies.append(OverviewCompany(
            symbol=c["symbol"], name=c["name"], industry=c.get("industry"), as_of=c.get("as_of"),
            probability_distressed=s["probability_distressed"], band=band,
            z_score=s["z_score"], z_score_zone=s["z_score_zone"],
            z_double_prime=s["z_double_prime"], z_double_prime_zone=s["z_double_prime_zone"],
            loss_making=s["cash_burning"],
        ))
    for c in companies:
        if not c.get("complete"):
            missing = c.get("missing") or []
            if _is_financial_balance_sheet(c, u):
                category = "not_applicable"
                kind = "Bank, NBFC or insurer" if u.id == "nse" else "Bank or insurer"
                reason = (f"{kind}: its balance sheet has no current assets/liabilities "
                          "split, so this Altman-style model doesn't apply.")
            else:
                category = "missing_data"
                reason = (f"Missing from source: {', '.join(missing)}" if missing
                          else c.get("error") or "No data")
            out.unscored.append(UnscoredCompany(symbol=c["symbol"], name=c["name"],
                                                industry=c.get("industry"), category=category,
                                                reason=reason[:200]))
        ebit = (c.get("financials") or {}).get("ebit")
        if ebit is not None:
            out.ebit_known += 1
            out.loss_making += ebit < 0

    out.scored = len(out.companies)
    out.companies.sort(key=lambda r: r.probability_distressed, reverse=True)
    out.unscored.sort(key=lambda r: r.symbol)
    return out


@app.get("/market/overview", response_model=MarketOverviewResponse)
def market_overview(universe: str = UniverseParam, claims: dict = Depends(auth.require_auth)):
    """Every company in the index with complete figures, scored with the
    CURRENT model (not a stored score), so a mid-week model promotion is
    reflected immediately. One batched prediction; cached per
    (universe, snapshot, model version) in a warm container."""
    u = _universe(universe)
    snap = market_data.load_snapshot(universe=u.id)
    if not snap:
        return MarketOverviewResponse(index=u.index, universe=u.id, available=False)
    model = get_model()
    version = model_loader.current_version()
    key = (snap.get("generated_at"), version)
    cached = _overview_cache.get(u.id)
    if not cached or cached["key"] != key:
        cached = {"key": key, "value": _build_overview(snap, model, version, u)}
        _overview_cache[u.id] = cached
    return cached["value"]


# --- Manual market-data refresh ----------------------------------------------

class RefreshStatusResponse(BaseModel):
    universe: str
    index: str
    # idle (never ran) | running | done | failed | stale (said running, but
    # is past its time budget: it died without reporting back)
    state: str
    trigger: Optional[str] = None       # manual | scheduled | ...
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    progress: Optional[str] = None      # e.g. "2 of 4 parts done"
    error: Optional[str] = None
    snapshot_generated_at: Optional[str] = None
    expected_minutes: int


def _refresh_out(u: "market_data.Universe", status: Optional[dict]) -> RefreshStatusResponse:
    status = status or {}
    snap = market_data.load_snapshot(universe=u.id)
    return RefreshStatusResponse(
        universe=u.id, index=u.index, state=market_data.effective_state(status, u.id),
        trigger=status.get("trigger"), started_at=status.get("started_at"),
        finished_at=status.get("finished_at"), progress=status.get("progress"), error=status.get("error"),
        snapshot_generated_at=(snap or {}).get("generated_at"), expected_minutes=u.expected_minutes,
    )


@app.get("/market/refresh", response_model=RefreshStatusResponse)
def refresh_status(universe: str = UniverseParam, claims: dict = Depends(auth.require_auth)):
    """Where the index's data refresh stands. Once a run is done, the next
    snapshot read picks up its data (the snapshot cache is dropped here)."""
    u = _universe(universe)
    status = market_data.read_refresh_status(u.id)
    if market_data.effective_state(status, u.id) == "done":
        # The warm container caches the snapshot for an hour; if that copy
        # predates the run that just finished, reload it.
        snap = market_data.load_snapshot(universe=u.id)
        started = market_data._parse_iso((status or {}).get("started_at"))
        generated = market_data._parse_iso((snap or {}).get("generated_at"))
        if started and (generated is None or generated < started):
            market_data.load_snapshot(force=True, universe=u.id)
    return _refresh_out(u, status)


@app.post("/market/refresh", response_model=RefreshStatusResponse, status_code=202)
def start_market_refresh(universe: str = UniverseParam, claims: dict = Depends(auth.require_auth)):
    """Start the index's snapshot job now. The job runs in the background
    (NSE ~12 min; S&P 500 ~30 min, as 4 parts one after another); poll
    GET /market/refresh. Refused with 409 while a run is in progress."""
    u = _universe(universe)
    who = claims.get("cognito:username") or claims.get("sub")
    try:
        status = market_data.start_refresh(u.id, requested_by=who)
    except market_data.RefreshInProgress as e:
        raise HTTPException(status_code=409, detail={
            "message": f"A {u.index} refresh is already running (started {e.status.get('started_at')}).",
            "status": _refresh_out(u, e.status).model_dump()})
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not start the refresh: {type(e).__name__}")
    return _refresh_out(u, status)


# --- AWS Lambda entry point -------------------------------------------------
# Only imported/used when running inside Lambda; harmless to leave in for
# other deployment targets since it's not invoked unless Lambda calls `handler`.
try:
    from mangum import Mangum
    handler = Mangum(app)
except ImportError:
    handler = None  # not running in/for Lambda; fine for local uvicorn or ECS
