"""
Tests for company search (GET /search, market_data.search_companies): the
dashboard's ticker box searches index members by ticker (3+ characters) or
name (5+ characters), then Yahoo Finance for companies beyond the index.

No network: Yahoo's search is replaced by a fake.

Run from the project root: python tests/test_company_search.py
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
for var in ("MODEL_BUCKET", "MARKET_SNAPSHOT_PATH"):
    os.environ.pop(var, None)

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

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


def _company(symbol, name, complete=True, industry="Test"):
    return {"symbol": symbol, "yahoo_ticker": f"{symbol}.NS", "name": name, "industry": industry,
            "complete": complete}


SNAPSHOT = {"generated_at": "2026-11-15T10:57:12Z", "companies": [
    _company("TATAPOWER", "Tata Power Co. Ltd.", industry="Power"),
    _company("TATASTEEL", "Tata Steel Ltd.", industry="Metals & Mining"),
    _company("TCS", "Tata Consultancy Services Ltd.", industry="Information Technology"),
    _company("RELIANCE", "Reliance Industries Ltd.", industry="Oil Gas & Consumable Fuels"),
    _company("HDFCBANK", "HDFC Bank Ltd.", complete=False, industry="Financial Services"),
]}


def _yahoo(*quotes):
    def searcher(q):
        return [dict(x) for x in quotes]
    return searcher


def _q(symbol, name, exch="NSE", qtype="EQUITY"):
    return {"symbol": symbol, "longname": name, "exchDisp": exch, "quoteType": qtype}


def _reset():
    market_data._search_cache.clear()


def test_query_validation():
    ok = {"tcs": "tcs", "  tata   power ": "tata power", "M&M": "M&M", "Dr. Reddy's": "Dr. Reddy's"}
    for raw, want in ok.items():
        assert market_data.normalise_query(raw) == want, raw
    for bad in ["", "ab", "a" * 41, "<script>", "tata/power", "x?y=1"]:
        assert market_data.normalise_query(bad) is None, bad
    print("PASS: query validation (3-40 chars, letters/digits/space & . - ')")


def test_ticker_search_at_three_chars_name_search_from_five():
    _reset()
    # "tat": ticker-style only -> TATAPOWER, TATASTEEL by symbol; TCS's NAME
    # contains "Tat" but names don't count below 5 characters.
    r = market_data.search_companies("tat", SNAPSHOT, searcher=_yahoo())
    assert [x["symbol"] for x in r["results"]] == ["TATAPOWER", "TATASTEEL"], r

    _reset()
    # "tata " / "tata c": name search kicks in -> TCS via "Tata Consultancy".
    r = market_data.search_companies("tata c", SNAPSHOT, searcher=_yahoo())
    assert [x["symbol"] for x in r["results"]] == ["TCS"], r

    _reset()
    r = market_data.search_companies("reliance", SNAPSHOT, searcher=_yahoo())
    assert [x["symbol"] for x in r["results"]] == ["RELIANCE"], r
    assert r["results"][0]["in_index"] and r["results"][0]["has_financials"]
    print("PASS: ticker matching from 3 chars, name matching from 5 chars")


def test_ranking_exact_then_prefix_then_contains():
    _reset()
    snap = {"companies": [_company("ABTCS", "Alpha"), _company("TCSX", "Beta"), _company("TCS", "Gamma")]}
    r = market_data.search_companies("TCS", snap, searcher=_yahoo())
    assert [x["symbol"] for x in r["results"]] == ["TCS", "TCSX", "ABTCS"], r
    print("PASS: ranking: exact ticker, then prefix, then contains")


def test_online_results_merge_after_index_without_duplicates():
    _reset()
    yahoo = _yahoo(
        _q("RELIANCE.NS", "Reliance Industries Limited"),          # already in index -> skipped
        _q("RELIANCE.BO", "Reliance Industries Limited", "Bombay"),  # same company on BSE -> skipped
        _q("RPOWER.NS", "Reliance Power Limited"),
        _q("RPOWER.BO", "Reliance Power Limited", "Bombay"),          # BSE duplicate of RPOWER -> skipped
        _q("RELIANCE-F", "Some Fund", qtype="MUTUALFUND"),            # not an equity -> skipped
    )
    r = market_data.search_companies("reliance", SNAPSHOT, searcher=yahoo)
    got = [(x["symbol"], x["yahoo_ticker"], x["in_index"]) for x in r["results"]]
    assert got == [("RELIANCE", "RELIANCE.NS", True), ("RPOWER", "RPOWER.NS", False)], got
    assert r["online_ok"] is True
    print("PASS: index first; Yahoo adds others; NSE/BSE and index duplicates and non-equities dropped")


def test_short_query_ignores_yahoo_name_matches():
    _reset()
    # Yahoo matches "inf" against names too; below 5 chars only ticker matches count.
    yahoo = _yahoo(_q("INFY.NS", "Infosys Limited"), _q("NAUKRI.NS", "Info Edge (India) Limited"))
    r = market_data.search_companies("inf", SNAPSHOT, searcher=yahoo)
    assert [x["symbol"] for x in r["results"]] == ["INFY"], r
    print("PASS: 3-4 char queries keep only ticker matches from Yahoo")


def test_yahoo_failure_or_timeout_still_returns_index_matches():
    _reset()

    def broken(q):
        raise ConnectionError("Yahoo down")

    r = market_data.search_companies("tata", SNAPSHOT, searcher=broken)
    assert [x["symbol"] for x in r["results"]] == ["TATAPOWER", "TATASTEEL"] and r["online_ok"] is False

    _reset()

    def slow(q):
        time.sleep(2)
        return []

    started = time.time()
    r = market_data.search_companies("tata", SNAPSHOT, searcher=slow, timeout_seconds=0.3)
    assert time.time() - started < 1.5 and r["online_ok"] is False and len(r["results"]) == 2
    print("PASS: Yahoo failure or timeout -> index matches still returned, online_ok=false")


def test_online_results_are_cached():
    _reset()
    calls = []

    def counting(q):
        calls.append(q)
        return [_q("ZOMATO.NS", "Zomato Limited")]

    market_data.search_companies("zomato", SNAPSHOT, searcher=counting)
    market_data.search_companies("Zomato", SNAPSHOT, searcher=counting)
    assert calls == ["zomato"], calls
    print("PASS: Yahoo search cached per query (case-insensitive)")


def test_results_capped():
    _reset()
    snap = {"companies": [_company(f"TATA{i:02d}", f"Tata {i}") for i in range(30)]}
    r = market_data.search_companies("tata", snap, searcher=_yahoo())
    assert len(r["results"]) == market_data.MAX_SEARCH_RESULTS
    print(f"PASS: at most {market_data.MAX_SEARCH_RESULTS} results")


def test_search_endpoint():
    _reset()
    tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump(SNAPSHOT, tmp)
    tmp.close()
    os.environ["MARKET_SNAPSHOT_PATH"] = tmp.name
    market_data._snapshot_cache.update(value=None, loaded_at=0.0)
    try:
        import importlib
        import app as app_module
        importlib.reload(app_module)
        real_yahoo = app_module.market_data.yahoo_search
        app_module.market_data.yahoo_search = lambda q: [_q("TATAMOTORS.NS", "Tata Motors Limited")]
        from fastapi.testclient import TestClient
        client = TestClient(app_module.app)

        assert client.get("/search?q=tata").status_code == 401
        assert client.get("/search?q=ta", headers=_auth_header()).status_code == 400
        assert client.get("/search?q=" + "%3Cscript%3E", headers=_auth_header()).status_code == 400

        body = client.get("/search?q=tata", headers=_auth_header()).json()
        assert [x["symbol"] for x in body["results"]] == ["TATAPOWER", "TATASTEEL", "TATAMOTORS"], body
        assert body["results"][2] == {"symbol": "TATAMOTORS", "yahoo_ticker": "TATAMOTORS.NS",
                                      "name": "Tata Motors Limited", "exchange": "NSE", "industry": None,
                                      "in_index": False, "has_financials": None,
                                      "universe": None, "index_label": None}, body["results"][2]
        assert body["online_ok"] is True
        app_module.market_data.yahoo_search = real_yahoo
    finally:
        os.environ.pop("MARKET_SNAPSHOT_PATH", None)
        os.unlink(tmp.name)
    print("PASS: GET /search requires a token, validates q, returns index + online results")


if __name__ == "__main__":
    test_query_validation()
    test_ticker_search_at_three_chars_name_search_from_five()
    test_ranking_exact_then_prefix_then_contains()
    test_online_results_merge_after_index_without_duplicates()
    test_short_query_ignores_yahoo_name_matches()
    test_yahoo_failure_or_timeout_still_returns_index_matches()
    test_online_results_are_cached()
    test_results_capped()
    test_search_endpoint()
    print("\nAll company search tests passed.")
