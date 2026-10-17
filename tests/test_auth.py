"""
Tests for src/auth.py's Cognito ID token verification and its wiring into
src/app.py's protected routes.

Moto has no cognito-idp mock, so this generates its own throwaway RSA
keypair, signs a fake Cognito-shaped ID token with it, and monkeypatches
auth._jwk_client() to return a fake client exposing that keypair's public
key -- testing real signature verification without a real User Pool.

Run from the project root: python tests/test_auth.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

os.environ["AWS_DEFAULT_REGION"] = "ap-south-1"
os.environ["AWS_REGION"] = "ap-south-1"
os.environ["COGNITO_USER_POOL_ID"] = "ap-south-1_testpool"
os.environ["COGNITO_CLIENT_ID"] = "test-client-id"

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

import auth

_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_ISSUER = f"https://cognito-idp.{os.environ['AWS_REGION']}.amazonaws.com/{os.environ['COGNITO_USER_POOL_ID']}"


class _FakeSigningKey:
    def __init__(self, key):
        self.key = key


class _FakeJwkClient:
    """Stands in for jwt.PyJWKClient: returns our test keypair's public key
    regardless of the token's `kid`, so no real JWKS endpoint is needed."""

    def get_signing_key_from_jwt(self, token):
        return _FakeSigningKey(_PRIVATE_KEY.public_key())


def _patch_jwk_client():
    auth._cached_jwk_client = _FakeJwkClient()


def _make_token(**overrides):
    now = int(time.time())
    claims = {
        "sub": "test-user",
        "aud": os.environ["COGNITO_CLIENT_ID"],
        "iss": _ISSUER,
        "token_use": "id",
        "iat": now,
        "exp": now + 3600,
    }
    claims.update(overrides)
    return jwt.encode(claims, _PRIVATE_KEY, algorithm="RS256")


def _client():
    import importlib
    import app as app_module
    importlib.reload(app_module)
    from fastapi.testclient import TestClient
    return TestClient(app_module.app)


def test_valid_token_succeeds():
    _patch_jwk_client()
    claims = auth.require_auth(authorization=f"Bearer {_make_token()}")
    assert claims["sub"] == "test-user"
    print("PASSED: valid token verified")


def test_missing_token_rejected():
    _patch_jwk_client()
    try:
        auth.require_auth(authorization=None)
        assert False, "expected HTTPException"
    except Exception as e:
        assert getattr(e, "status_code", None) == 401, e
    print("PASSED: missing token -> 401")


def test_wrong_signing_key_rejected():
    _patch_jwk_client()
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = int(time.time())
    bad_token = jwt.encode(
        {
            "sub": "test-user",
            "aud": os.environ["COGNITO_CLIENT_ID"],
            "iss": _ISSUER,
            "iat": now,
            "exp": now + 3600,
        },
        other_key,
        algorithm="RS256",
    )
    try:
        auth.require_auth(authorization=f"Bearer {bad_token}")
        assert False, "expected HTTPException"
    except Exception as e:
        assert getattr(e, "status_code", None) == 401, e
    print("PASSED: wrong signing key -> 401")


def test_expired_token_rejected():
    _patch_jwk_client()
    now = int(time.time())
    token = _make_token(iat=now - 7200, exp=now - 3600)
    try:
        auth.require_auth(authorization=f"Bearer {token}")
        assert False, "expected HTTPException"
    except Exception as e:
        assert getattr(e, "status_code", None) == 401, e
    print("PASSED: expired token -> 401")


def test_wrong_audience_rejected():
    _patch_jwk_client()
    token = _make_token(aud="some-other-client-id")
    try:
        auth.require_auth(authorization=f"Bearer {token}")
        assert False, "expected HTTPException"
    except Exception as e:
        assert getattr(e, "status_code", None) == 401, e
    print("PASSED: wrong audience -> 401")


def test_health_stays_open():
    client = _client()
    r = client.get("/health")
    assert r.status_code == 200, r.text
    print("PASSED: /health reachable with no token")


def test_predict_demo_requires_auth():
    _patch_jwk_client()
    client = _client()

    r = client.post("/predict/demo/SYN027")
    assert r.status_code == 401, r.text

    r = client.post(
        "/predict/demo/SYN027",
        headers={"Authorization": f"Bearer {_make_token()}"},
    )
    assert r.status_code == 200, r.text
    print("PASSED: /predict/demo requires a valid bearer token")


if __name__ == "__main__":
    test_valid_token_succeeds()
    test_missing_token_rejected()
    test_wrong_signing_key_rejected()
    test_expired_token_rejected()
    test_wrong_audience_rejected()
    test_health_stays_open()
    test_predict_demo_requires_auth()
    print("\nAll auth tests passed.")
