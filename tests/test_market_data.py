"""
Tests for src/market_data.py (the NSE LargeMidcap 250 snapshot behind the
dashboard's ticker list and auto-fill) and the API endpoints that serve it:
GET /companies, GET /companies/{symbol}, GET /lookup/{ticker}.

No network: Yahoo Finance and NSE's CSV hosts are replaced with fakes, and
S3 is moto-mocked.

Run from the project root: python tests/test_market_data.py
"""
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

os.environ["AWS_DEFAULT_REGION"] = "ap-south-1"
os.environ["AWS_REGION"] = "ap-south-1"
os.environ["COGNITO_USER_POOL_ID"] = "ap-south-1_testpool"
os.environ["COGNITO_CLIENT_ID"] = "test-client-id"
os.environ.pop("MODEL_BUCKET", None)
os.environ.pop("MARKET_SNAPSHOT_PATH", None)

import boto3
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from moto import mock_aws

import auth
import market_data

_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class _FakeSigningKey:
    def __init__(self, key):
        self.key = key


class _FakeJwkClient:
    def get_signing_key_from_jwt(self, token):
        return _FakeSigningKey(_PRIVATE_KEY.public_key())


def _auth_header():
    auth._cached_jwk_client = _FakeJwkClient()
    now = int(time.time())
    token = jwt.encode(
        {
            "sub": "test-user",
            "aud": os.environ["COGNITO_CLIENT_ID"],
            "iss": f"https://cognito-idp.{os.environ['AWS_REGION']}.amazonaws.com/{os.environ['COGNITO_USER_POOL_ID']}",
            "iat": now,
            "exp": now + 3600,
        },
        _PRIVATE_KEY,
        algorithm="RS256",
    )
    return {"Authorization": f"Bearer {token}"}


def _csv(n: int) -> str:
    rows = ["Company Name,Industry,Symbol,Series,ISIN Code"]
    for i in range(n):
        rows.append(f"Company {i} Ltd.,Industry {i % 5},SYM{i},EQ,INE{i:09d}")
    return "\n".join(rows) + "\n"


FULL = {
    "total_assets": 1000.0, "total_liabilities": 600.0, "current_assets": 400.0,
    "current_liabilities": 300.0, "retained_earnings": 150.0, "ebit": 80.0,
    "sales": 900.0, "market_value_equity": 2000.0, "book_value_equity": 400.0,
    "as_of": "2025-03-31", "currency": "INR",
}


def _reset_caches():
    market_data._snapshot_cache.update(value=None, loaded_at=0.0)
    market_data._lookup_cache.clear()


# ---------------------------------------------------------------- parsing --

def test_parse_constituents_handles_bom_whitespace_and_duplicates():
    text = "﻿Company Name, Industry ,Symbol,Series,ISIN Code\n" \
           "Reliance Industries Ltd., Oil Gas , reliance ,EQ,INE002A01018\n" \
           "Dup,X,RELIANCE,EQ,X\n" \
           "Blank symbol,X,,EQ,X\n"
    rows = market_data.parse_constituents_csv(text)
    assert rows == [{
        "symbol": "RELIANCE", "name": "Reliance Industries Ltd.",
        "industry": "Oil Gas", "isin": "INE002A01018",
    }], rows
    print("PASS: constituent CSV parsing (BOM, whitespace, duplicates, blanks)")


def test_fetch_constituents_falls_through_sources_in_order():
    calls = []

    def http_get(url):
        calls.append(url)
        if url == market_data.CONSTITUENT_URLS[0]:
            return "<html>Access denied</html>"  # error page, not a CSV
        return _csv(250)

    rows, source = market_data.fetch_constituents(http_get=http_get, seed_reader=lambda: None)
    assert len(rows) == 250 and source == market_data.CONSTITUENT_URLS[1], (len(rows), source)
    assert calls == market_data.CONSTITUENT_URLS

    def http_fail(url):
        raise ConnectionError("blocked")

    rows, source = market_data.fetch_constituents(http_get=http_fail, seed_reader=lambda: _csv(3))
    assert source == "s3-seed" and len(rows) == 3

    try:
        market_data.fetch_constituents(http_get=http_fail, seed_reader=lambda: None)
    except RuntimeError as e:
        assert "blocked" in str(e) and "s3-seed: not present" in str(e), e
    else:
        raise AssertionError("expected RuntimeError when every source fails")
    print("PASS: constituent sources tried in order: niftyindices -> NSE archive -> S3 seed -> error")


# ------------------------------------------------------------- snapshot ----

def test_build_snapshot_records_complete_incomplete_and_failed_companies():
    constituents = [
        {"symbol": "GOOD", "name": "Good Ltd", "industry": "IT"},
        {"symbol": "PART", "name": "Partial Ltd", "industry": "Auto"},
        {"symbol": "BOOM", "name": "Boom Ltd", "industry": None},
    ]

    def fetcher(yahoo):
        if yahoo == "GOOD.NS":
            return dict(FULL)
        if yahoo == "PART.NS":
            return {**FULL, "retained_earnings": float("nan"), "ebit": None}
        raise ValueError("No data found, symbol may be delisted")

    snap = market_data.build_snapshot(constituents, "test-source", fetcher=fetcher, workers=3)
    by = {c["symbol"]: c for c in snap["companies"]}

    assert snap["count"] == 3 and snap["complete_count"] == 1
    assert snap["constituents_source"] == "test-source"
    assert by["GOOD"]["complete"] and by["GOOD"]["missing"] == []
    assert by["GOOD"]["yahoo_ticker"] == "GOOD.NS" and by["GOOD"]["as_of"] == "2025-03-31"
    assert by["PART"]["missing"] == ["retained_earnings", "ebit"], by["PART"]["missing"]
    assert by["PART"]["financials"]["retained_earnings"] is None  # NaN cleaned to None
    assert by["BOOM"]["error"].startswith("ValueError") and not by["BOOM"]["complete"]
    assert [c["symbol"] for c in snap["companies"]] == ["BOOM", "GOOD", "PART"]  # sorted
    json.dumps(snap)  # must be JSON-serialisable (no NaN, no numpy types)
    print("PASS: snapshot keeps complete, partial (NaN -> None) and failed companies")


@mock_aws
def test_snapshot_round_trips_through_s3_and_missing_snapshot_is_none():
    _reset_caches()
    os.environ["MODEL_BUCKET"] = "distress-model-test"
    try:
        s3 = boto3.client("s3", region_name="ap-south-1")
        s3.create_bucket(Bucket="distress-model-test",
                         CreateBucketConfiguration={"LocationConstraint": "ap-south-1"})

        assert market_data.load_snapshot(force=True) is None

        snap = market_data.build_snapshot(
            [{"symbol": "GOOD", "name": "Good Ltd", "industry": "IT"}], "x",
            fetcher=lambda y: dict(FULL), workers=1)
        keys = market_data.save_snapshot(snap)
        assert keys[1] == market_data.DEFAULT_SNAPSHOT_KEY
        assert keys[0].startswith("market-data/nse-largemidcap250/history/")

        loaded = market_data.load_snapshot(force=True)
        assert loaded["companies"][0]["symbol"] == "GOOD"
        assert market_data.find_company(loaded, "good.ns")["name"] == "Good Ltd"

        # Seed CSV path, as used when NSE's hosts block AWS.
        s3.put_object(Bucket="distress-model-test", Key=market_data.DEFAULT_SEED_KEY, Body=_csv(2).encode())
        assert market_data._read_seed_from_s3().startswith("Company Name")
    finally:
        os.environ.pop("MODEL_BUCKET", None)
        _reset_caches()
    print("PASS: snapshot S3 round trip (latest + dated history), seed CSV, missing -> None")


def test_nse_client_extracts_latest_period_from_yfinance_frames():
    """fetch_financials_with_period against a fake yfinance.Ticker built from
    real pandas frames shaped like yfinance's (rows = line items, columns =
    period-end timestamps, newest first)."""
    import pandas as pd
    import nse_client

    cols = [pd.Timestamp("2025-03-31"), pd.Timestamp("2024-03-31")]
    bs = pd.DataFrame(
        {cols[0]: [1000, 600, 400, 300, 150], cols[1]: [900, 550, 350, 280, 120]},
        index=["Total Assets", "Total Liabilities Net Minority Interest",
               "Current Assets", "Current Liabilities", "Retained Earnings"],
    )
    inc = pd.DataFrame(
        {cols[0]: [None, 85, 900], cols[1]: [70, 75, 800]},
        index=["EBIT", "Operating Income", "Total Revenue"],
    )

    class FakeTicker:
        def __init__(self, t):
            self.balance_sheet, self.income_stmt = bs, inc
            self.fast_info = {"marketCap": 2500, "currency": "INR"}
            self.info = {"shortName": "Fake Co", "financialCurrency": "INR"}

    real = nse_client.yf.Ticker
    nse_client.yf.Ticker = FakeTicker
    try:
        out = nse_client.fetch_financials_with_period("FAKE.NS", polite_delay=0, with_name=True)
    finally:
        nse_client.yf.Ticker = real

    assert out["as_of"] == "2025-03-31", out["as_of"]
    assert out["total_assets"] == 1000 and out["sales"] == 900
    # EBIT's FY2025 cell is blank -> the next alias (Operating Income) for
    # the SAME year, never FY2024's EBIT of 70: no mixing of fiscal years.
    assert out["ebit"] == 85, out["ebit"]
    assert out["book_value_equity"] == 400 and out["market_value_equity"] == 2500
    assert out["name"] == "Fake Co" and out["currency"] == "INR"

    # A field blank in the latest year under every alias stays missing.
    inc.loc["Operating Income", cols[0]] = None
    nse_client.yf.Ticker = FakeTicker
    try:
        out = nse_client.fetch_financials_with_period("FAKE.NS", polite_delay=0)
    finally:
        nse_client.yf.Ticker = real
    assert out["ebit"] is None and out["as_of"] == "2025-03-31", out

    # Statements in USD while the shares trade in INR (Infosys on Yahoo):
    # the INR market cap must not be mixed with USD liabilities.
    class UsdStatements(FakeTicker):
        def __init__(self, t):
            super().__init__(t)
            self.info = {"shortName": "Infosys", "financialCurrency": "USD"}

    nse_client.yf.Ticker = UsdStatements
    try:
        out = nse_client.fetch_financials_with_period("INFY.NS", polite_delay=0)
    finally:
        nse_client.yf.Ticker = real
    assert out["currency"] == "USD" and out["currency_mismatch"] is True, out
    assert out["market_value_equity"] is None and out["book_value_equity"] == 400, out
    rec = market_data.normalise_record(out, {"symbol": "INFY"})
    assert "USD" in rec["note"], rec
    print("PASS: nse_client takes one fiscal year only, and drops a market cap in a different currency")


# ------------------------------------------------------------- lookups -----

def test_ticker_validation_rejects_anything_unusual():
    ok = {"reliance": "RELIANCE", " M&M ": "M&M", "BAJAJ-AUTO.NS": "BAJAJ-AUTO.NS", "500325.BO": "500325.BO"}
    for raw, want in ok.items():
        assert market_data.normalise_ticker(raw) == want, raw
    for bad in ["", "../etc", "A B", "X" * 30, "AAPL.TOOLONG", "a/b", "TCS.NS?x=1"]:
        assert market_data.normalise_ticker(bad) is None, bad
    assert market_data.candidate_yahoo_tickers("TCS") == ["TCS.NS", "TCS.BO", "TCS"]
    assert market_data.candidate_yahoo_tickers("TCS.BO") == ["TCS.BO"]
    print("PASS: ticker validation and NSE -> BSE -> bare candidate order")


def test_live_lookup_tries_candidates_caches_and_times_out():
    _reset_caches()
    tried = []

    def fetcher(yahoo):
        tried.append(yahoo)
        if yahoo.endswith(".NS"):
            return {f: None for f in market_data.REQUIRED_FIELDS}  # nothing usable
        return {**FULL, "name": "Found On BSE"}

    rec = market_data.live_lookup("ABC", fetcher=fetcher)
    assert rec["yahoo_ticker"] == "ABC.BO" and rec["name"] == "Found On BSE" and rec["complete"]
    assert tried == ["ABC.NS", "ABC.BO"]

    market_data.live_lookup("ABC", fetcher=fetcher)
    assert tried == ["ABC.NS", "ABC.BO"], "second lookup should be served from cache"

    assert market_data.live_lookup("NOPE", fetcher=lambda y: {}) is None

    def slow(yahoo):
        time.sleep(2)
        return dict(FULL)

    started = time.time()
    assert market_data.live_lookup("SLOW", fetcher=slow, timeout_seconds=0.3) is None
    assert time.time() - started < 1.5, "lookup must give up at its deadline"
    _reset_caches()
    print("PASS: live lookup candidate order, cache, not-found and timeout")


# ------------------------------------------------------------------ API -----

def _client_with_snapshot(snapshot):
    _reset_caches()
    tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    if snapshot is None:
        os.unlink(tmp.name)
    else:
        json.dump(snapshot, tmp)
        tmp.close()
    os.environ["MARKET_SNAPSHOT_PATH"] = tmp.name
    import importlib
    import app as app_module
    importlib.reload(app_module)
    from fastapi.testclient import TestClient
    return TestClient(app_module.app), app_module


def _snapshot():
    return market_data.build_snapshot(
        [{"symbol": "GOOD", "name": "Good Ltd", "industry": "IT"},
         {"symbol": "PART", "name": "Partial Ltd", "industry": "Auto"}],
        "test",
        fetcher=lambda y: dict(FULL) if y == "GOOD.NS" else {**FULL, "ebit": None},
        workers=1,
    )


def test_api_requires_auth():
    client, _ = _client_with_snapshot(_snapshot())
    for path in ["/companies", "/companies/GOOD", "/lookup/GOOD"]:
        assert client.get(path).status_code == 401, path
    print("PASS: /companies, /companies/{symbol}, /lookup/{ticker} all require a token")


def test_api_companies_list_and_unavailable_state():
    client, _ = _client_with_snapshot(None)
    r = client.get("/companies", headers=_auth_header())
    assert r.status_code == 200 and r.json()["available"] is False and r.json()["companies"] == []

    client, _ = _client_with_snapshot(_snapshot())
    body = client.get("/companies", headers=_auth_header()).json()
    assert body["available"] is True and body["index"] == "Nifty LargeMidcap 250"
    assert [(c["symbol"], c["has_financials"]) for c in body["companies"]] == [("GOOD", True), ("PART", False)]
    print("PASS: /companies lists constituents, or available=false before the first snapshot")


def test_api_company_financials_snapshot_live_retry_and_errors():
    client, app_module = _client_with_snapshot(_snapshot())
    h = _auth_header()

    r = client.get("/companies/good", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "snapshot" and body["complete"] and body["financials"]["sales"] == 900.0

    # Incomplete snapshot record -> one live retry, used only if it's better.
    app_module.market_data.live_lookup = lambda t, **kw: market_data.normalise_record(
        dict(FULL), {"symbol": "PART", "yahoo_ticker": "PART.NS", "name": "Yahoo Name",
                     "industry": None, "as_of": "2025-03-31", "currency": "INR"})
    body = client.get("/companies/PART", headers=h).json()
    assert body["source"] == "live" and body["complete"] and body["name"] == "Partial Ltd", body

    app_module.market_data.live_lookup = lambda t, **kw: None
    body = client.get("/companies/PART", headers=h).json()
    assert body["source"] == "snapshot" and body["missing"] == ["ebit"]

    assert client.get("/companies/NOTINDEX", headers=h).status_code == 404
    assert client.get("/companies/a%20b", headers=h).status_code == 400
    print("PASS: /companies/{symbol}: snapshot, live retry for gaps, 404 outside index, 400 bad ticker")


def test_api_lookup_snapshot_live_and_not_found():
    client, app_module = _client_with_snapshot(_snapshot())
    h = _auth_header()

    body = client.get("/lookup/GOOD", headers=h).json()
    assert body["found"] and body["in_index"] and body["company"]["source"] == "snapshot"

    seen = []

    def fake_live(t, **kw):
        seen.append(t)
        if t == "AAPL":
            return market_data.normalise_record(dict(FULL), {
                "symbol": "AAPL", "yahoo_ticker": "AAPL", "name": "Apple Inc.",
                "industry": None, "as_of": "2025-09-27", "currency": "USD"})
        return None

    app_module.market_data.live_lookup = fake_live
    body = client.get("/lookup/aapl", headers=h).json()
    assert body["found"] and not body["in_index"] and body["company"]["currency"] == "USD"
    assert body["company"]["source"] == "live"

    body = client.get("/lookup/ZZZZ", headers=h).json()
    assert body == {"query": "ZZZZ", "found": False, "in_index": False, "company": None}, body
    assert seen == ["AAPL", "ZZZZ"]
    assert client.get("/lookup/..%2Fetc", headers=h).status_code in (400, 404)
    print("PASS: /lookup: index member from snapshot, other tickers live, clean not-found")


if __name__ == "__main__":
    try:
        test_parse_constituents_handles_bom_whitespace_and_duplicates()
        test_fetch_constituents_falls_through_sources_in_order()
        test_build_snapshot_records_complete_incomplete_and_failed_companies()
        test_snapshot_round_trips_through_s3_and_missing_snapshot_is_none()
        test_nse_client_extracts_latest_period_from_yfinance_frames()
        test_ticker_validation_rejects_anything_unusual()
        test_live_lookup_tries_candidates_caches_and_times_out()
        test_api_requires_auth()
        test_api_companies_list_and_unavailable_state()
        test_api_company_financials_snapshot_live_retry_and_errors()
        test_api_lookup_snapshot_live_and_not_found()
    finally:
        path = os.environ.pop("MARKET_SNAPSHOT_PATH", None)
        if path and os.path.exists(path):
            os.unlink(path)
    print("\nAll market data tests passed.")
