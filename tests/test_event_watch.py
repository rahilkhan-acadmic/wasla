"""
Tests for the Event Watch section's backend (src/event_watch.py and
GET /events/watch): confidence score rules, upcoming-event selection and
NSE session mapping, and the endpoint's shape and auth -- on the real
committed calendar and study results.

Run from the project root: python tests/test_event_watch.py
"""
import datetime
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
os.environ["AWS_DEFAULT_REGION"] = "ap-south-1"
os.environ["AWS_REGION"] = "ap-south-1"
os.environ["COGNITO_USER_POOL_ID"] = "ap-south-1_testpool"
os.environ["COGNITO_CLIENT_ID"] = "test-client-id"

import jwt  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402

import auth  # noqa: E402
import event_watch as ew  # noqa: E402

IST = ew.IST
_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class _Signing:
    key = _KEY.public_key()


class _Jwk:
    def get_signing_key_from_jwt(self, token):
        return _Signing()


def _auth():
    auth._cached_jwk_client = _Jwk()
    now = int(time.time())
    tok = jwt.encode({"sub": "u", "aud": os.environ["COGNITO_CLIENT_ID"],
                      "iss": f"https://cognito-idp.ap-south-1.amazonaws.com/{os.environ['COGNITO_USER_POOL_ID']}",
                      "iat": now, "exp": now + 3600}, _KEY, algorithm="RS256")
    return {"Authorization": f"Bearer {tok}"}


def _trade(wins, losses, base_wr, p, avg, each=None):
    n = wins + losses
    return {"trades": n, "wins": wins, "losses": losses, "win_rate": wins / n if n else None,
            "avg_return": avg, "baseline": {"win_rate": base_wr}, "p_avg_beats_baseline": p,
            "each": each if each is not None else [{"return": 0.01}] * wins + [{"return": -0.01}] * losses}


def test_confidence_rules():
    no_edge = ew.confidence(_trade(17, 19, 0.53, 0.86, -0.001))
    assert no_edge["score"] == 0 and no_edge["verdict"].startswith("No edge"), no_edge
    bad = ew.confidence(_trade(8, 16, 0.50, 0.94, -0.003))
    assert bad["score"] == 0 and "avoid" in bad["verdict"], bad
    # A strong, stable, significant edge with plenty of history scores high.
    each = ([{"return": 0.01}] * 11 + [{"return": -0.01}] * 4) * 2
    strong = ew.confidence(_trade(22, 8, 0.50, 0.01, 0.004, each))
    assert strong["score"] >= 50 and strong["label"] == "high", strong
    assert strong["components"] == {"evidence": 1.0, "edge": 1.0, "significance": 1.0, "stability": 1.0}
    # Same edge on 7 events: evidence caps the score.
    small = ew.confidence(_trade(5, 2, 0.50, 0.03, 0.004, [{"return": 0.01}] * 5 + [{"return": -0.01}] * 2))
    assert small["score"] < 30 and small["components"]["evidence"] == round(7 / 30, 2), small
    print("PASS: confidence: no edge -> 0; clearly worse -> 'avoid'; strong+stable -> high; few events capped")


def test_upcoming_and_sessions():
    now = datetime.datetime(2026, 11, 25, 12, 0, tzinfo=IST)
    b = ew.build(now)
    ids = [e["id"] for e in b["upcoming"]]
    assert ids == ["rbi-2026-12-04", "fomc-2026-12-09"], ids
    fomc = b["upcoming"][1]
    # 2pm ET on Dec 9 (US winter) = 00:30 IST Dec 10 -> that morning's NSE session.
    assert fomc["release_ist"] == "2026-12-10T00:30:00+05:30" and fomc["nse_session"] == "2026-12-10"
    assert ew.reaction_session(datetime.datetime(2026, 6, 17, 23, 30, tzinfo=IST)) == "2026-06-18"
    assert ew.reaction_session(datetime.datetime(2026, 12, 4, 10, 0, tzinfo=IST)) == "2026-12-04"
    assert ew.reaction_session(datetime.datetime(2026, 11, 27, 23, 30, tzinfo=IST)) == "2026-11-30"  # Fri -> Mon
    later = ew.build(datetime.datetime(2026, 12, 20, tzinfo=IST))
    assert later["upcoming"] == [], "past events drop off"
    print("PASS: upcoming RBI Dec 4 + FOMC Dec 9 (00:30 IST Dec 10); sessions mapped; past events drop off")


def test_cards_reflect_the_study():
    b = ew.build(datetime.datetime(2026, 11, 25, tzinfo=IST))
    cards = b["cards"]
    assert set(cards) == {"rbi_mpc", "fomc", "union_budget"}
    fomc = cards["fomc"]["by_index"]["NIFTY50"]
    assert (fomc["record"]["wins"], fomc["record"]["losses"]) == (8, 16)
    assert fomc["confidence"]["score"] == 0 and "avoid" in fomc["confidence"]["verdict"]
    assert len(fomc["movement"]["each"]) == fomc["movement"]["n"] == 47
    for c in cards.values():
        assert c["vix"]["mean_vix_change_on_day"] < 0, "VIX falls on event days in the study"
        for v in c["by_index"].values():
            assert v["record"]["proxy"] == "daily" and 0 <= v["confidence"]["score"] <= 100
    assert b["latest_vix"]["close"] > 0 and 0 < b["latest_vix"]["percentile_5y"] <= 1
    print("PASS: cards carry the study's records (FOMC Nifty 8W/16L -> 0, avoid), moves, VIX")


def test_endpoint():
    import importlib
    import app as app_module
    importlib.reload(app_module)
    from fastapi.testclient import TestClient
    c = TestClient(app_module.app)
    assert c.get("/events/watch").status_code == 401
    body = c.get("/events/watch", headers=_auth()).json()
    assert {"upcoming", "cards", "latest_vix", "disclaimer", "study_span"} <= set(body), body.keys()
    print("PASS: GET /events/watch requires a token and returns the section's data")


if __name__ == "__main__":
    test_confidence_rules()
    test_upcoming_and_sessions()
    test_cards_reflect_the_study()
    test_endpoint()
    print("\nAll Event Watch tests passed.")
