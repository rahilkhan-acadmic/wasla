"""
FastAPI inference service for the financial distress model.

Wraps predict.py's logic behind an HTTP API so it can run on AWS Lambda
(via a container image + API Gateway/Function URL) or any other container
host (ECS, App Runner, or just `uvicorn` on a VM for local testing).

Endpoints:
    GET  /health                 Liveness check
    POST /predict                Score a company given its financials + headlines
    POST /predict/demo/{ticker}  Score a company from the bundled synthetic dataset

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
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from features import build_feature_row, financials_from_dict, FEATURE_NAMES
from altman_zscore import classify_zone
import model_loader

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
def predict(req: PredictRequest):
    fin_dict = req.financials.model_dump()
    return _run_prediction(req.ticker, fin_dict, req.headlines)


@app.post("/predict/demo/{ticker}", response_model=PredictResponse)
def predict_demo(ticker: str):
    """Convenience endpoint for testing against the bundled synthetic dataset."""
    if not os.path.exists(SAMPLE_DATA_PATH):
        raise HTTPException(status_code=404, detail="Sample dataset not found")
    with open(SAMPLE_DATA_PATH) as f:
        companies = json.load(f)
    match = next((c for c in companies if c["ticker"] == ticker), None)
    if match is None:
        raise HTTPException(status_code=404, detail=f"{ticker} not found in sample dataset")
    return _run_prediction(ticker, match["financials"], match.get("headlines", []))


# --- AWS Lambda entry point -------------------------------------------------
# Only imported/used when running inside Lambda; harmless to leave in for
# other deployment targets since it's not invoked unless Lambda calls `handler`.
try:
    from mangum import Mangum
    handler = Mangum(app)
except ImportError:
    handler = None  # not running in/for Lambda; fine for local uvicorn or ECS
