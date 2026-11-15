"""
Tests for the second market universe, the S&P 500, next to the Nifty
LargeMidcap 250:

  * constituent parsing (GitHub CSV, Yahoo-style class-share tickers),
  * the sharded weekly job: each shard writes a part, latest.json is merged
    only once every part exists, a newer part's record wins, and companies
    past the time budget are recorded as skipped rather than lost,
  * the API's ?universe= parameter on /companies, /companies/{symbol} and
    /market/overview, US banks/insurers marked "model doesn't apply",
  * search and /lookup across both indexes, where NSE's HAL (Hindustan
    Aeronautics) and NYSE's HAL (Halliburton) are different companies.

No network: S3 is moto-mocked and Yahoo is replaced by fakes.

Run from the project root: python tests/test_us_universe.py
"""
import json
import os
import sys
import tempfile
import time

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(_ROOT, "src"))

os.environ["AWS_DEFAULT_REGION"] = "ap-south-1"
os.environ["AWS_REGION"] = "ap-south-1"
os.environ["COGNITO_USER_POOL_ID"] = "ap-south-1_testpool"
os.environ["COGNITO_CLIENT_ID"] = "test-client-id"
for var in ("MODEL_BUCKET", "MARKET_SNAPSHOT_PATH", "MARKET_SNAPSHOT_PATH_US", "MARKET_UNIVERSE"):
    os.environ.pop(var, None)

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
        {"sub": "u", "aud": os.environ["COGNITO_CLIENT_ID"],
         "iss": f"https://cognito-idp.{os.environ['AWS_REGION']}.amazonaws.com/{os.environ['COGNITO_USER_POOL_ID']}",
         "iat": now, "exp": now + 3600},
        _PRIVATE_KEY, algorithm="RS256")
    return {"Authorization": f"Bearer {token}"}


FULL = {
    "total_assets": 1000.0, "total_liabilities": 600.0, "current_assets": 400.0,
    "current_liabilities": 300.0, "retained_earnings": 150.0, "ebit": 80.0,
    "sales": 900.0, "market_value_equity": 2000.0, "book_value_equity": 400.0,
    "as_of": "2025-12-31", "currency": "USD",
}

SP500_HEADER = "Symbol,Security,GICS Sector,GICS Sub-Industry,Headquarters Location,Date added,CIK,Founded"


def _sp500_csv(n: int, extra: str = "") -> str:
    rows = [SP500_HEADER]
    for i in range(n):
        rows.append(f'US{i},Company {i} Inc.,Sector {i % 4},Sub {i},"City, State",2000-01-01,{1000 + i},1950')
    return "\n".join(rows) + "\n" + extra


def _reset_caches():
    for cache in market_data._snapshot_caches.values():
        cache.update(value=None, loaded_at=0.0)
    market_data._lookup_cache.clear()
    market_data._search_cache.clear()


class _Ctx:
    """Just enough of a Lambda context for the handler's time budget."""
    def __init__(self, remaining_ms):
        self.remaining_ms = remaining_ms

    def get_remaining_time_in_millis(self):
        return self.remaining_ms


# ------------------------------------------------------------ constituents --

def test_parse_sp500_csv_uses_yahoo_tickers_and_gics_sector():
    text = ("﻿" + SP500_HEADER + "\n"
            'BRK.B,Berkshire Hathaway,Financials,Multi-Sector Holdings,"Omaha, Nebraska",1976-01-01,1067983,1839\n'
            ' aapl ,Apple Inc.,Information Technology,Technology Hardware,"Cupertino, California",1982-11-30,320193,1977\n'
            'AAPL,Duplicate,X,X,X,X,X,X\n'
            ',No symbol,X,X,X,X,X,X\n')
    rows = market_data.parse_sp500_csv(text)
    assert rows == [
        {"symbol": "BRK-B", "name": "Berkshire Hathaway", "industry": "Financials", "cik": "1067983"},
        {"symbol": "AAPL", "name": "Apple Inc.", "industry": "Information Technology", "cik": "320193"},
    ], rows
    print("PASS: S&P 500 CSV: BRK.B -> BRK-B, GICS sector as industry, BOM/whitespace/duplicates handled")


def test_fetch_sp500_constituents_validates_row_count_and_falls_back_to_seed():
    rows, source = market_data.fetch_constituents(
        http_get=lambda url: _sp500_csv(503), seed_reader=lambda: None, universe="us")
    assert len(rows) == 503 and source == market_data.SP500_CONSTITUENT_URLS[0]

    # An error page or a truncated list is not accepted; the S3 seed is.
    rows, source = market_data.fetch_constituents(
        http_get=lambda url: _sp500_csv(20), seed_reader=lambda: _sp500_csv(7), universe="us")
    assert source == "s3-seed" and len(rows) == 7

    try:
        market_data.fetch_constituents(http_get=lambda url: _sp500_csv(20), seed_reader=lambda: None,
                                       universe="us")
    except RuntimeError as e:
        assert "only 20 rows" in str(e), e
    else:
        raise AssertionError("expected RuntimeError")

    try:
        market_data.get_universe("mars")
    except KeyError:
        pass
    else:
        raise AssertionError("unknown universe should raise KeyError")
    print("PASS: S&P 500 list needs 450+ rows, else S3 seed, else a clear error; unknown universe rejected")


# ------------------------------------------------------------ sharded job --

def test_shards_partition_the_list_evenly_and_stably():
    cons = [{"symbol": f"S{i:03d}", "name": str(i)} for i in range(503)]
    parts = [market_data.shard_constituents(list(reversed(cons)), i, 4) for i in range(4)]
    symbols = [c["symbol"] for p in parts for c in p]
    assert sorted(symbols) == sorted(c["symbol"] for c in cons) and len(symbols) == 503  # each exactly once
    assert sorted(len(p) for p in parts) == [125, 126, 126, 126]
    assert parts == [market_data.shard_constituents(cons, i, 4) for i in range(4)]  # input order irrelevant
    print("PASS: 4 shards cover all 503 companies once, sizes within one, independent of input order")


def test_build_snapshot_uses_bare_us_tickers_and_respects_deadline():
    seen = []

    def fetcher(yahoo):
        seen.append(yahoo)
        return dict(FULL)

    cons = [{"symbol": "AAPL", "name": "Apple", "industry": "IT"},
            {"symbol": "BRK-B", "name": "Berkshire", "industry": "Financials"}]
    snap = market_data.build_snapshot(cons, "src", fetcher=fetcher, workers=1, universe="us")
    assert sorted(seen) == ["AAPL", "BRK-B"], seen
    assert snap["index"] == "S&P 500" and snap["universe"] == "us" and snap["complete_count"] == 2

    seen.clear()
    late = market_data.build_snapshot(cons, "src", fetcher=fetcher, workers=1, universe="us",
                                      deadline=time.time() - 1)
    assert seen == [] and late["complete_count"] == 0 and late["count"] == 2
    assert all(c["error"].startswith("Skipped") for c in late["companies"])
    print("PASS: US tickers fetched without a suffix; past the deadline companies are skipped, not lost")


@mock_aws
def test_sharded_handler_merges_only_when_every_part_exists():
    _reset_caches()
    os.environ["MODEL_BUCKET"] = "distress-model-test"
    real_fetch_constituents = market_data.fetch_constituents
    real_fetch_company = market_data.fetch_company
    try:
        s3 = boto3.client("s3", region_name="ap-south-1")
        s3.create_bucket(Bucket="distress-model-test",
                         CreateBucketConfiguration={"LocationConstraint": "ap-south-1"})
        cons = market_data.parse_sp500_csv(_sp500_csv(9))
        market_data.fetch_constituents = lambda universe="nse", **kw: (cons, "fake-src")
        fetched = []

        def fake_fetch(yahoo):
            fetched.append(yahoo)
            return dict(FULL)

        # build_snapshot's default fetcher is bound at definition time, so
        # patch the handler's call path instead.
        real_build = market_data.build_snapshot
        market_data.build_snapshot = lambda c, s, **kw: real_build(c, s, fetcher=fake_fetch, **kw)
        latest = market_data.get_universe("us").snapshot_key
        assert latest == "market-data/us-sp500/latest.json"

        out0 = market_data.snapshot_handler({"universe": "us", "shard": 0, "shards": 3}, _Ctx(600_000))
        assert out0["count"] == 3 and out0["merged_count"] is None, out0
        assert out0["s3_keys"] == ["market-data/us-sp500/parts/part-0-of-3.json"]
        assert market_data.load_snapshot(force=True, universe="us") is None  # nothing merged yet

        market_data.snapshot_handler({"universe": "us", "shard": 1, "shards": 3}, _Ctx(600_000))
        out2 = market_data.snapshot_handler({"universe": "us", "shard": 2, "shards": 3}, _Ctx(600_000))
        assert out2["merged_count"] == 9 and latest in out2["s3_keys"], out2
        assert sorted(fetched) == sorted(c["symbol"] for c in cons)  # each fetched exactly once

        merged = market_data.load_snapshot(force=True, universe="us")
        assert merged["universe"] == "us" and merged["index"] == "S&P 500"
        assert merged["count"] == 9 == merged["complete_count"] and len(merged["parts"]) == 3
        assert [c["symbol"] for c in merged["companies"]] == sorted(c["symbol"] for c in cons)
        assert market_data.load_snapshot(force=True) is None  # NSE untouched

        # A later week: shard 0 re-runs with a company now incomplete; the
        # merge (with last week's parts 1 and 2) keeps shard 0's newer record.
        time.sleep(1.1)  # generated_at has one-second resolution
        market_data.build_snapshot = lambda c, s, **kw: real_build(
            c, s, fetcher=lambda y: {**FULL, "ebit": None}, **kw)
        market_data.snapshot_handler({"universe": "us", "shard": 0, "shards": 3}, _Ctx(600_000))
        merged2 = market_data.load_snapshot(force=True, universe="us")
        shard0 = {c["symbol"] for c in market_data.shard_constituents(cons, 0, 3)}
        assert merged2["count"] == 9 and merged2["complete_count"] == 6, merged2["complete_count"]
        assert all(not c["complete"] for c in merged2["companies"] if c["symbol"] in shard0)
        assert merged2["generated_at"] > merged["generated_at"]

        for bad in ({"universe": "us", "shard": 3, "shards": 3}, {"universe": "us", "shards": 99}):
            try:
                market_data.snapshot_handler(bad, None)
            except ValueError:
                pass
            else:
                raise AssertionError(f"expected ValueError for {bad}")
        market_data.build_snapshot = real_build
    finally:
        market_data.fetch_constituents = real_fetch_constituents
        market_data.fetch_company = real_fetch_company
        if market_data.build_snapshot is not real_build:
            market_data.build_snapshot = real_build
        os.environ.pop("MODEL_BUCKET", None)
        _reset_caches()
    print("PASS: sharded job writes parts, merges once all exist, newer part wins, bad shard rejected")


def test_find_company_in_us_snapshot():
    snap = {"universe": "us", "companies": [{"symbol": "BRK-B", "name": "Berkshire"}]}
    assert market_data.find_company(snap, "brk.b")["name"] == "Berkshire"
    assert market_data.find_company(snap, "BRK-B")["name"] == "Berkshire"
    assert market_data.find_company({"companies": [{"symbol": "TCS", "name": "TCS"}]}, "TCS.NS")["name"] == "TCS"
    print("PASS: find_company: BRK.B and BRK-B both find Berkshire; NSE .NS suffix still stripped")


# --------------------------------------------------------------------- API --

def _record(symbol, yahoo, name, industry, fin=None):
    return market_data.normalise_record(dict(fin or FULL), {
        "symbol": symbol, "yahoo_ticker": yahoo, "name": name, "industry": industry,
        "as_of": "2025-12-31", "currency": "USD"})


def _us_snapshot():
    bank = {**FULL, "current_assets": None, "current_liabilities": None}
    reit = {**FULL, "current_assets": None}
    return {"index": "S&P 500", "universe": "us", "generated_at": "2026-11-15T03:30:00Z",
            "companies": [
                _record("AAPL", "AAPL", "Apple Inc.", "Information Technology"),
                _record("HAL", "HAL", "Halliburton", "Energy"),
                _record("BRK-B", "BRK-B", "Berkshire Hathaway", "Financials"),
                _record("JPM", "JPM", "JPMorgan Chase", "Financials", bank),
                _record("PLD", "PLD", "Prologis", "Real Estate", reit),
            ]}


def _nse_snapshot():
    return {"index": "Nifty LargeMidcap 250", "generated_at": "2026-11-15T01:42:00Z", "companies": [
        _record("HAL", "HAL.NS", "Hindustan Aeronautics Ltd.", "Capital Goods"),
        _record("TCS", "TCS.NS", "Tata Consultancy Services Ltd.", "Information Technology"),
    ]}


def _client(nse, us):
    paths = []
    for var, snap in (("MARKET_SNAPSHOT_PATH", nse), ("MARKET_SNAPSHOT_PATH_US", us)):
        tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump(snap, tmp)
        tmp.close()
        os.environ[var] = tmp.name
        paths.append(tmp.name)
    _reset_caches()
    import importlib
    import app as app_module
    importlib.reload(app_module)
    from fastapi.testclient import TestClient
    return TestClient(app_module.app), app_module, paths


def _cleanup(paths):
    for var in ("MARKET_SNAPSHOT_PATH", "MARKET_SNAPSHOT_PATH_US"):
        os.environ.pop(var, None)
    for p in paths:
        os.unlink(p)
    _reset_caches()


def test_api_universe_parameter():
    client, app_module, paths = _client(_nse_snapshot(), _us_snapshot())
    h = _auth_header()
    try:
        assert client.get("/companies?universe=us").status_code == 401
        assert client.get("/market/overview?universe=mars", headers=h).status_code == 400
        assert client.get("/companies?universe=mars", headers=h).status_code == 400

        nse = client.get("/companies", headers=h).json()
        us = client.get("/companies?universe=us", headers=h).json()
        assert nse["index"] == "Nifty LargeMidcap 250" and [c["symbol"] for c in nse["companies"]] == ["HAL", "TCS"]
        assert us["index"] == "S&P 500" and len(us["companies"]) == 5

        # HAL is a different company in each universe.
        assert client.get("/companies/HAL", headers=h).json()["name"] == "Hindustan Aeronautics Ltd."
        hal_us = client.get("/companies/HAL?universe=us", headers=h).json()
        assert hal_us["name"] == "Halliburton" and hal_us["yahoo_ticker"] == "HAL" and hal_us["currency"] == "USD"
        assert client.get("/companies/BRK.B?universe=us", headers=h).json()["symbol"] == "BRK-B"
        assert client.get("/companies/AAPL", headers=h).status_code == 404  # not in NSE

        ov = client.get("/market/overview?universe=us", headers=h).json()
        assert ov["available"] and ov["universe"] == "us" and ov["index"] == "S&P 500"
        assert ov["total"] == 5 and ov["scored"] == 3
        cat = {u["symbol"]: u["category"] for u in ov["unscored"]}
        # A bank without the current/non-current split doesn't fit the model;
        # a REIT with a figure missing is ordinary missing data.
        assert cat == {"JPM": "not_applicable", "PLD": "missing_data"}, cat
        assert next(u for u in ov["unscored"] if u["symbol"] == "JPM")["reason"].startswith("Bank or insurer")

        ov_nse = client.get("/market/overview", headers=h).json()
        assert ov_nse["universe"] == "nse" and ov_nse["total"] == 2
        assert set(app_module._overview_cache) == {"nse", "us"}  # cached separately

        # No US snapshot yet -> available=false, not an error.
        _reset_caches()
        os.environ["MARKET_SNAPSHOT_PATH_US"] = paths[1] + ".missing"
        app_module._overview_cache.clear()
        empty = client.get("/market/overview?universe=us", headers=h).json()
        assert empty == {**empty, "available": False, "universe": "us", "index": "S&P 500"}
    finally:
        _cleanup(paths)
    print("PASS: ?universe= on /companies, /companies/{symbol}, /market/overview; HAL differs per index; "
          "US banks not applicable")


def test_search_and_lookup_across_both_indexes():
    client, app_module, paths = _client(_nse_snapshot(), _us_snapshot())
    h = _auth_header()
    real_yahoo = app_module.market_data.yahoo_search
    real_live = app_module.market_data.live_lookup
    try:
        app_module.market_data.yahoo_search = lambda q: [
            {"symbol": "HAL", "longname": "Halliburton Company", "exchDisp": "NYSE", "quoteType": "EQUITY"},
            {"symbol": "HAL.BO", "longname": "Hindustan Aeronautics", "exchDisp": "Bombay", "quoteType": "EQUITY"},
            {"symbol": "HALO", "longname": "Halozyme", "exchDisp": "NASDAQ", "quoteType": "EQUITY"},
        ]
        body = client.get("/search?q=hal", headers=h).json()
        got = [(r["yahoo_ticker"], r["universe"], r["index_label"]) for r in body["results"]]
        # Both HALs from the indexes (NSE first at equal rank); Yahoo's NYSE
        # HAL and BSE HAL.BO are those same companies, so dropped; HALO added.
        assert got == [("HAL.NS", "nse", "LargeMidcap 250"), ("HAL", "us", "S&P 500"), ("HALO", None, None)], got
        assert body["results"][1]["exchange"] == "NYSE/Nasdaq"

        app_module.market_data.yahoo_search = lambda q: []
        body = client.get("/search?q=apple", headers=h).json()
        assert [(r["symbol"], r["universe"], r["in_index"]) for r in body["results"]] == [("AAPL", "us", True)]

        # /lookup: an S&P 500 member comes from the snapshot, no live fetch.
        def no_live(*a, **kw):
            raise AssertionError("should not fetch live")
        app_module.market_data.live_lookup = no_live
        r = client.get("/lookup/AAPL", headers=h).json()
        assert r["found"] and r["in_index"] and r["company"]["source"] == "snapshot", r
        assert client.get("/lookup/HAL", headers=h).json()["company"]["name"] == "Hindustan Aeronautics Ltd."
    finally:
        app_module.market_data.yahoo_search = real_yahoo
        app_module.market_data.live_lookup = real_live
        _cleanup(paths)
    print("PASS: search lists NSE and S&P 500 members (both HALs), drops Yahoo duplicates; /lookup uses the "
          "US snapshot")


if __name__ == "__main__":
    test_parse_sp500_csv_uses_yahoo_tickers_and_gics_sector()
    test_fetch_sp500_constituents_validates_row_count_and_falls_back_to_seed()
    test_shards_partition_the_list_evenly_and_stably()
    test_build_snapshot_uses_bare_us_tickers_and_respects_deadline()
    test_sharded_handler_merges_only_when_every_part_exists()
    test_find_company_in_us_snapshot()
    test_api_universe_parameter()
    test_search_and_lookup_across_both_indexes()
    print("\nAll US universe tests passed.")
