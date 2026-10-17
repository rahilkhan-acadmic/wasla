"""
Cognito ID token verification for src/app.py's protected routes.

Verifies the ID token (not the access token -- ID tokens carry `aud` set to
the app client id directly; access tokens use a different client_id/scope
shape). jwt.decode validates `exp`/`iat` automatically.
"""
import os

import jwt
from jwt import PyJWKClient
from fastapi import Header, HTTPException

COGNITO_REGION = os.environ.get("AWS_REGION", "ap-south-1")
USER_POOL_ID = os.environ.get("COGNITO_USER_POOL_ID")
CLIENT_ID = os.environ.get("COGNITO_CLIENT_ID")

_cached_jwk_client = None  # per-warm-process cache, same pattern as model_loader.py's _cached_model


def _jwk_client():
    global _cached_jwk_client
    if _cached_jwk_client is None:
        url = f"https://cognito-idp.{COGNITO_REGION}.amazonaws.com/{USER_POOL_ID}/.well-known/jwks.json"
        _cached_jwk_client = PyJWKClient(url)
    return _cached_jwk_client


def require_auth(authorization: str = Header(default=None)) -> dict:
    if not USER_POOL_ID or not CLIENT_ID:
        raise HTTPException(status_code=503, detail="Auth not configured")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.removeprefix("Bearer ")
    try:
        signing_key = _jwk_client().get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=CLIENT_ID,
            issuer=f"https://cognito-idp.{COGNITO_REGION}.amazonaws.com/{USER_POOL_ID}",
        )
    except jwt.PyJWTError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")
