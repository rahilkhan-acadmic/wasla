"""
Tests for the market overview: src/scoring.py (shared by /predict and the
overview) and GET /market/overview in src/app.py.

Uses the bundled local model (models/distress_model.json, no registry) and
the bundled synthetic companies in data/sample_companies.json as realistic
financials, dressed up as a Nifty LargeMidcap 250 snapshot.

Run from the project root: python tests/test_market_overview.py
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
for var in ("MODEL_REGISTRY_TABLE", "MODEL_BUCKET", "MARKET_SNAPSHOT_PATH"):
    os.environ.pop(var, None)

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

import auth
import market_data
import model_loader
import scoring

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


with open(os.path.join(_ROOT, "data", "sample_companies.json")) as f:
    SAMPLES = json.load(f)


def _snapshot(generated_at="2026-11-15T01:42:00Z"):
    """40 sample companies as complete snapshot records, plus one incomplete
    (EBIT known and negative), one failed fetch, one bank (no current
    assets/liabilities, no EBIT), and one complete record with zero total
    assets that can't be turned into features."""
    companies = []
    for s in SAMPLES[:40]:
        companies.append(market_data.normalise_record(dict(s["financials"]), {
            "symbol": s["ticker"], "yahoo_ticker": s["ticker"] + ".NS", "name": f"{s['ticker']} Ltd",
            "industry": "Test", "as_of": "2025-03-31", "currency": "INR"}))
    partial = dict(SAMPLES[0]["financials"], retained_earnings=None, ebit=-5.0)
    companies.append(market_data.normalise_record(partial, {
        "symbol": "PARTIAL", "yahoo_ticker": "PARTIAL.NS", "name": "Partial Ltd",
        "industry": "Test", "as_of": "2025-03-31", "currency": "INR"}))
    failed = market_data.normalise_record({}, {
        "symbol": "FAILED", "yahoo_ticker": "FAILED.NS", "name": "Failed Ltd",
        "industry": None, "as_of": None, "currency": None})
    failed["error"] = "ValueError: No data found"
    companies.append(failed)
    bank = dict(SAMPLES[2]["financials"], current_assets=None, current_liabilities=None, ebit=None)
    companies.append(market_data.normalise_record(bank, {
        "symbol": "SOMEBANK", "yahoo_ticker": "SOMEBANK.NS", "name": "Some Bank Ltd",
        "industry": "Financial Services", "as_of": "2026-03-31", "currency": "INR"}))
    zero = dict(SAMPLES[1]["financials"], total_assets=0.0)
    companies.append(market_data.normalise_record(zero, {
        "symbol": "ZERO", "yahoo_ticker": "ZERO.NS", "name": "Zero Ltd",
        "industry": "Test", "as_of": "2025-03-31", "currency": "INR"}))
    return {"index": "Nifty LargeMidcap 250", "generated_at": generated_at,
            "companies": companies, "count": len(companies)}


def test_risk_band_boundaries():
    assert scoring.risk_band(0.0) == "low"
    assert scoring.risk_band(0.3299) == "low"
    assert scoring.risk_band(0.33) == "moderate"
    assert scoring.risk_band(0.6599) == "moderate"
    assert scoring.risk_band(0.66) == "high"
    assert scoring.risk_band(1.0) == "high"
    print("PASS: risk bands: <0.33 low, <0.66 moderate, else high")


def test_batch_scores_equal_single_scores_and_survive_bad_rows():
    model = model_loader.get_model(force_reload=True)
    fins = [dict(s["financials"]) for s in SAMPLES[:25]]
    fins.insert(7, dict(fins[0], total_assets=0.0))  # unusable row mid-batch

    batch = scoring.score_many(model, fins)
    assert len(batch) == len(fins)
    assert "error" in batch[7] and "division" in batch[7]["error"], batch[7]
    for fin, b in zip(fins, batch):
        if "error" in b:
            continue
        assert b == scoring.score_one(model, fin), (b, scoring.score_one(model, fin))
    assert scoring.score_many(model, []) == []
    print("PASS: batched scores identical to single scores; a bad row is isolated")


def _client(snapshot):
    tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    if snapshot is None:
        tmp.close()
        os.unlink(tmp.name)
    else:
        json.dump(snapshot, tmp)
        tmp.close()
    os.environ["MARKET_SNAPSHOT_PATH"] = tmp.name
    market_data._snapshot_cache.update(value=None, loaded_at=0.0)
    import importlib
    import app as app_module
    importlib.reload(app_module)
    from fastapi.testclient import TestClient
    return TestClient(app_module.app), app_module


def test_overview_requires_auth_and_reports_unavailable():
    client, _ = _client(None)
    assert client.get("/market/overview").status_code == 401
    body = client.get("/market/overview", headers=_auth_header()).json()
    assert body["available"] is False and body["scored"] == 0 and body["companies"] == []
    print("PASS: /market/overview requires a token; available=false before the first snapshot")


def test_overview_counts_bands_loss_making_and_unscored():
    snap = _snapshot()
    client, _ = _client(snap)
    body = client.get("/market/overview", headers=_auth_header()).json()

    assert body["available"] and body["total"] == 44
    assert body["scored"] == 40 == len(body["companies"])
    assert sum(body["bands"].values()) == body["scored"], body["bands"]
    assert set(body["bands"]) == {"low", "moderate", "high"}
    # The synthetic sample data happens to score very confidently (no
    # "moderate" companies), so only low and high are guaranteed non-empty.
    assert body["bands"]["low"] > 0 and body["bands"]["high"] > 0, body["bands"]
    assert body["thresholds"] == {"moderate": 0.33, "high": 0.66}
    assert body["model_version"] == "local"

    probs = [c["probability_distressed"] for c in body["companies"]]
    assert probs == sorted(probs, reverse=True), "companies should be sorted riskiest first"
    for c in body["companies"]:
        assert c["band"] == scoring.risk_band(c["probability_distressed"])

    # Each scored company matches what /predict-style scoring gives it.
    model = model_loader.get_model()
    by_symbol = {s["ticker"]: s for s in SAMPLES[:40]}
    for c in body["companies"][:5]:
        expected = scoring.score_one(model, by_symbol[c["symbol"]]["financials"])
        assert c["probability_distressed"] == expected["probability_distressed"]

    # Loss-making: every company with known EBIT, including PARTIAL (EBIT -5,
    # unscored) and ZERO (unscorable); FAILED has no EBIT so isn't counted.
    expected_loss = sum(1 for s in SAMPLES[:40] if s["financials"]["ebit"] < 0) + 1
    expected_loss += SAMPLES[1]["financials"]["ebit"] < 0
    assert body["loss_making"] == expected_loss, (body["loss_making"], expected_loss)
    assert body["ebit_known"] == 42  # the bank and FAILED have no EBIT

    unscored = {u["symbol"]: u["reason"] for u in body["unscored"]}
    category = {u["symbol"]: u["category"] for u in body["unscored"]}
    assert set(unscored) == {"PARTIAL", "FAILED", "ZERO", "SOMEBANK"}, unscored
    assert category == {"PARTIAL": "missing_data", "FAILED": "missing_data",
                        "ZERO": "error", "SOMEBANK": "not_applicable"}, category
    assert "doesn't apply" in unscored["SOMEBANK"]
    assert unscored["PARTIAL"] == "Missing from source: retained_earnings"
    assert unscored["FAILED"].startswith("Missing from source")  # all fields missing
    assert unscored["ZERO"].startswith("Could not score: ZeroDivisionError")
    print(f"PASS: overview bands {body['bands']}, loss-making {body['loss_making']}/{body['ebit_known']}, "
          f"unscored {sorted(unscored)}")


def test_overview_cache_follows_snapshot_and_model_version():
    client, app_module = _client(_snapshot("2026-11-15T01:42:00Z"))
    h = _auth_header()
    first = client.get("/market/overview", headers=h).json()
    key1 = app_module._overview_cache["nse"]["key"]
    assert key1 == ("2026-11-15T01:42:00Z", "local")

    # A new model version must re-score even with the same snapshot.
    model_loader._cached_version = "v99"
    real_get_model = app_module.get_model
    app_module.get_model = lambda: model_loader._cached_model
    try:
        second = client.get("/market/overview", headers=h).json()
    finally:
        app_module.get_model = real_get_model
    assert app_module._overview_cache["nse"]["key"] == ("2026-11-15T01:42:00Z", "v99")
    assert second["model_version"] == "v99" and second["bands"] == first["bands"]
    model_loader.get_model(force_reload=True)
    print("PASS: overview cache is keyed on (snapshot, model version)")


if __name__ == "__main__":
    try:
        test_risk_band_boundaries()
        test_batch_scores_equal_single_scores_and_survive_bad_rows()
        test_overview_requires_auth_and_reports_unavailable()
        test_overview_counts_bands_loss_making_and_unscored()
        test_overview_cache_follows_snapshot_and_model_version()
    finally:
        path = os.environ.pop("MARKET_SNAPSHOT_PATH", None)
        if path and os.path.exists(path):
            os.unlink(path)
    print("\nAll market overview tests passed.")
