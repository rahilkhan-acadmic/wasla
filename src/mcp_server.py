"""
MCP server exposing the financial distress model as tools any MCP-compatible
client (Claude Desktop, Claude Code, etc.) can call directly in conversation --
e.g. "what's the distress score for RELIANCE.NS?" -- without a dashboard, a
custom API integration, or the person needing to know this project exists as
a separate system.

Uses MCP Python SDK v2 (mcp>=2.0). If you have v1 installed instead, replace
`from mcp.server.mcpserver import MCPServer` with
`from mcp.server.fastmcp import FastMCP as MCPServer` -- the decorator API
below is unchanged either way.

Run locally (stdio transport, for Claude Desktop):
    python mcp_server.py

Then add to Claude Desktop's config (claude_desktop_config.json):
    {
      "mcpServers": {
        "distress-model": {
          "command": "python",
          "args": ["/absolute/path/to/src/mcp_server.py"]
        }
      }
    }

For a shared/remote server instead of local stdio, run with a Streamable
HTTP transport (see MCPServer.run(transport="streamable-http") in the SDK
docs) and deploy it the same way as app.py -- container on Lambda, ECS, or
App Runner.
"""

import json
import os

import numpy as np
import xgboost as xgb
from mcp.server.mcpserver import MCPServer

from features import build_feature_row, financials_from_dict, FEATURE_NAMES
from altman_zscore import classify_zone

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.environ.get(
    "MODEL_PATH", os.path.join(_SCRIPT_DIR, "..", "models", "distress_model.json")
)
SAMPLE_DATA_PATH = os.environ.get(
    "SAMPLE_DATA_PATH", os.path.join(_SCRIPT_DIR, "..", "data", "sample_companies.json")
)

mcp = MCPServer("distress-model")

_model = None


def _get_model():
    global _model
    if _model is None:
        _model = xgb.XGBClassifier()
        _model.load_model(MODEL_PATH)
    return _model


@mcp.tool()
def score_company(
    total_assets: float,
    total_liabilities: float,
    current_assets: float,
    current_liabilities: float,
    retained_earnings: float,
    ebit: float,
    sales: float,
    headlines: list[str] = [],
    ticker: str = "UNKNOWN",
) -> str:
    """Score a company's financial distress risk from its fundamentals.

    Combines Altman Z-Score-style ratios with news sentiment via a trained
    XGBoost classifier. Research/screening tool only -- not investment advice.

    Returns a JSON string with the distress probability, Z-Score and zone,
    Z''-Score and zone, news sentiment, and whether the company is cash-burning.
    """
    fin_dict = {
        "total_assets": total_assets,
        "total_liabilities": total_liabilities,
        "current_assets": current_assets,
        "current_liabilities": current_liabilities,
        "retained_earnings": retained_earnings,
        "ebit": ebit,
        "sales": sales,
    }
    fin = financials_from_dict(fin_dict)
    feats = build_feature_row(fin, headlines)
    x = np.array([[feats[name] for name in FEATURE_NAMES]])
    prob = float(_get_model().predict_proba(x)[0, 1])

    return json.dumps({
        "ticker": ticker,
        "probability_distressed": round(prob, 4),
        "z_score": round(feats["z_score"], 3),
        "z_score_zone": classify_zone(feats["z_score"], "z"),
        "z_double_prime": round(feats["z_double_prime"], 3),
        "z_double_prime_zone": classify_zone(feats["z_double_prime"], "zpp"),
        "news_sentiment": round(feats["news_sentiment"], 3),
        "cash_burning": bool(feats["cash_burn_flag"]),
    }, indent=2)


@mcp.tool()
def score_demo_ticker(ticker: str) -> str:
    """Score a company from the bundled synthetic demo dataset by ticker
    (e.g. 'SYN027'). Useful for testing without real financial data."""
    with open(SAMPLE_DATA_PATH) as f:
        companies = json.load(f)
    match = next((c for c in companies if c["ticker"] == ticker), None)
    if match is None:
        return json.dumps({"error": f"{ticker} not found in demo dataset"})

    core_fields = {
        "total_assets", "total_liabilities", "current_assets",
        "current_liabilities", "retained_earnings", "ebit", "sales",
    }
    financials = {k: v for k, v in match["financials"].items() if k in core_fields}

    return score_company(
        ticker=ticker,
        headlines=match.get("headlines", []),
        **financials,
    )


@mcp.tool()
def fetch_us_financials(ticker: str) -> str:
    """Fetch real financial statement data for a US ticker from SEC EDGAR
    (free, no API key). Requires network access to sec.gov."""
    from edgar_client import fetch_financials_for_ticker
    try:
        return json.dumps(fetch_financials_for_ticker(ticker), indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def fetch_india_financials(ticker: str) -> str:
    """Fetch real financial statement data for an Indian ticker via yfinance.
    Use a .NS suffix for NSE or .BO for BSE (e.g. 'RELIANCE.NS')."""
    from nse_client import fetch_financials_for_ticker, fetch_recent_news_headlines
    try:
        fin = fetch_financials_for_ticker(ticker)
        fin["recent_headlines"] = fetch_recent_news_headlines(ticker)
        return json.dumps(fin, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


if __name__ == "__main__":
    mcp.run()  # defaults to stdio transport, for local Claude Desktop use


# --- Remote deployment (AWS) ------------------------------------------------
# For a shared/hosted MCP server instead of local stdio, use the Streamable
# HTTP transport, which is a real ASGI (Starlette) app -- deployable exactly
# like app.py.
#
# Local test:      uvicorn mcp_server:http_app --host 0.0.0.0 --port 8765
# Lambda handler:  mcp_server.handler  (see Dockerfile.lambda-mcp)
#
# stateless_http=True is important for Lambda: each invocation is a fresh
# container, so there's no persistent session to keep alive between calls.
http_app = mcp.streamable_http_app(stateless_http=True)

try:
    from mangum import Mangum
    handler = Mangum(http_app)
except ImportError:
    handler = None
