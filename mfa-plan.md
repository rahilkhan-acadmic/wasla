# MFA-Gated Authentication for the Dashboard

## Context

The dashboard (`dashboard/`, Next.js static export on S3+CloudFront) and the
backend API (`src/app.py`, FastAPI on Lambda, public Function URL) are both
currently fully public with no login. This plan adds Cognito-backed,
mandatory-MFA authentication so only specifically authorized users can reach
the dashboard's functionality and the API's data-returning routes.

**Separate, pre-existing blocker on live verification (not part of this
feature):** this AWS account currently can't create `AWS::CloudFront::Distribution`
resources, and anonymous requests to `AuthType: NONE` Lambda Function URLs are
denied by AWS itself regardless of resource policy — both need AWS Support to
verify the account (ticket content already drafted in `aws-support.txt`,
committed this session). Neither blocker is caused by or specific to auth —
they already blocked the plain public dashboard from going live. This plan
is fully buildable and testable right now (cfn-lint, backend unit tests with
a self-signed JWT, local `uvicorn`/`next dev` walkthrough) and will deploy
automatically the moment AWS lifts the restriction, via the existing
`deploy.yml` sequence. No infra is added to try to dodge that restriction
(e.g. no API Gateway swap-in) — unconfirmed payoff, real added cost, out of
scope.

## 1. Cognito stack — new `aws/auth-stack.json`

One-stack-per-concern, same convention as `aws/dashboard-stack.json`.

- **MFA: TOTP (software token) only, mandatory.** SMS MFA costs money and
  needs phone verification — against this project's budget target, and
  unnecessary for a handful of named users. `MfaConfiguration: "ON"`,
  `EnabledMfas: ["SOFTWARE_TOKEN_MFA"]` (no `SMS_MFA`).
- `DashboardUserPool` (`AWS::Cognito::UserPool`):
  `AdminCreateUserConfig.AllowAdminCreateUserOnly: true` (no public
  self-signup — the only way a user exists is `admin-create-user`), a
  reasonable `PasswordPolicy`, plain-username `UsernameAttributes` (avoids
  needing SES/email configured at all — zero extra cost/infra).
- `DashboardUserPoolClient` (`AWS::Cognito::UserPoolClient`): **no**
  `GenerateSecret` (public client — a static JS app can't keep a secret),
  `ExplicitAuthFlows: ["ALLOW_USER_SRP_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"]`
  (SRP, not plaintext-password auth), explicit `AccessTokenValidity` /
  `IdTokenValidity` (1 hour) / `RefreshTokenValidity` (30 days). **No**
  Hosted UI / OAuth config, **no** `AWS::Cognito::UserPoolDomain` — the
  dashboard keeps its own login UI, no redirect.
- Outputs: `UserPoolId`, `UserPoolClientId`.

## 2. Dashboard changes

**Library: `amazon-cognito-identity-js`**, not full Amplify — Amplify pulls
in a large multi-category dependency graph for a need that's just
SRP-login + MFA challenge-response + token storage; `amazon-cognito-identity-js`
is the lower-level SDK Amplify's own Auth category is built on, and fits
`dashboard/package.json`'s currently minimal deps (`next`/`react`/`react-dom`
only).

New files:
- `dashboard/lib/auth.ts` — wraps `CognitoUser`/`AuthenticationDetails`:
  `signIn()`, `completeNewPasswordChallenge()`, `associateSoftwareToken()` +
  `verifySoftwareToken()` (first-login MFA setup), `submitMfaCode()`
  (returning-user challenge), `getSession()`/`refreshSession()`, `signOut()`.
  Encodes the full chain: `USER_SRP_AUTH → (NEW_PASSWORD_REQUIRED?) →
  (MFA_SETUP | SOFTWARE_TOKEN_MFA) → tokens`.
- `dashboard/components/LoginForm.tsx` (`"use client"`) — state machine
  mirroring that chain: username/password → (set-new-password, first login
  only) → (TOTP secret/QR + confirm code, first login only) → (6-digit code,
  every login after). Same local-`useState` convention as `ScoreForm.tsx`.
- `dashboard/components/AuthGate.tsx` (`"use client"`) — checks for a valid
  session on mount; renders `<LoginForm/>` until authenticated, then
  `{children}`.
- `dashboard/app/layout.tsx` — wrap `<header>`+`<main>` (which includes
  `<ModelStatusPanel/>`, since that calls the now-protected `/model/info`)
  in `<AuthGate>`. Footer stays outside (static text, no API calls).

**Token storage: `sessionStorage`.** Memory-only forces re-auth on every
refresh (too much friction for a tool reopened routinely); `localStorage`
persists indefinitely across browser restarts (larger blast radius if ever
leaked). `sessionStorage` survives refreshes within a tab but clears on
tab/browser close — the right default for a single/few-user internal tool.

- `dashboard/lib/api.ts` — `request()` adds `Authorization: Bearer <idToken>`
  (read from `lib/auth.ts`'s session helper) to every call; `/health` ignores
  the header harmlessly, so no special-casing needed.
- `dashboard/package.json` — add `amazon-cognito-identity-js`.
- `dashboard/.env.local.example` — add `NEXT_PUBLIC_COGNITO_USER_POOL_ID`,
  `NEXT_PUBLIC_COGNITO_CLIENT_ID` (same build-time-bake-in pattern as
  `NEXT_PUBLIC_API_BASE_URL`).

## 3. Backend verification — new `src/auth.py`

**Library: `PyJWT[crypto]`**, not `python-jose` — `PyJWT`+`cryptography` are
already installed in this environment; `python-jose` would be a net-new,
less-actively-maintained dependency. `PyJWT`'s `PyJWKClient` handles
JWKS-fetch-and-cache-by-`kid` directly, no hand-rolled JWKS parsing needed.

```python
import os, jwt
from jwt import PyJWKClient
from fastapi import Header, HTTPException

COGNITO_REGION = os.environ.get("AWS_REGION", "ap-south-1")
USER_POOL_ID = os.environ.get("COGNITO_USER_POOL_ID")
CLIENT_ID = os.environ.get("COGNITO_CLIENT_ID")
_cached_jwk_client = None  # per-warm-process cache, same pattern as
                            # model_loader.py's _cached_model

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
            token, signing_key.key, algorithms=["RS256"],
            audience=CLIENT_ID,
            issuer=f"https://cognito-idp.{COGNITO_REGION}.amazonaws.com/{USER_POOL_ID}",
        )
    except jwt.PyJWTError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")
```

Verifies the **ID token** (not access token — ID tokens carry `aud` matching
the client id directly; access tokens use a different `client_id`/scope
shape). `jwt.decode` validates `exp`/`iat` automatically.

**Routes**: `/predict`, `/predict/demo/{ticker}`, `/model/info` gain
`claims: dict = Depends(auth.require_auth)`. `/health` stays open (standard
liveness-check convention).

`aws/lambda-stack.json` gains two new `Parameters` (`CognitoUserPoolId`,
`CognitoClientId`) → `Environment.Variables.COGNITO_USER_POOL_ID`/
`COGNITO_CLIENT_ID`, same pattern as the existing `DashboardOrigin` parameter.

`requirements.txt` gains one pinned line: `PyJWT[crypto]==2.15.1`.

## 4. User provisioning (manual, one-time, documented in CLAUDE.md)

```bash
aws cognito-idp admin-create-user \
  --user-pool-id <UserPoolId> --username rahilkhan \
  --user-attributes Name=email,Value=rahilkhan.acadmic@gmail.com \
  --message-action SUPPRESS --region ap-south-1

aws cognito-idp admin-set-user-password \
  --user-pool-id <UserPoolId> --username rahilkhan \
  --password '<temporary-password-shared-out-of-band>' \
  --no-temporary --region ap-south-1
```

`--no-temporary` sets a real password directly (skips `NEW_PASSWORD_REQUIRED`)
for the first admin account — simplest for a single owner. Additional users
later can omit it to go through the full first-login setup flow in the UI
(`NEW_PASSWORD_REQUIRED` → `MFA_SETUP` with TOTP secret/QR → confirm code →
tokens), which `LoginForm.tsx`'s state machine already supports either way.
No SES/email setup needed — temp passwords are set directly via CLI, not
emailed.

## 5. Testing — new `tests/test_auth.py`

Same "plain script, `assert`+`print`, no pytest" convention as
`tests/test_retrain_handler.py`/`tests/test_model_info_endpoint.py`. Moto has
no `cognito-idp` mock, so the test generates its own throwaway RSA keypair,
signs a fake Cognito-shaped ID token, and monkeypatches `auth._jwk_client()`
to return a fake client exposing that keypair's public key — testing real
signature verification without a real User Pool:

- Valid token → 200.
- Missing token → 401.
- Token signed with the wrong key → 401.
- Expired token (`exp` in the past) → 401.
- Wrong audience (`aud` ≠ client id) → 401.
- `/health` still reachable with no token at all.

Wiring: add `python tests/test_auth.py` to `CLAUDE.md`'s pre-deploy list and
a new `ci.yml` step (needs no AWS credentials — pure local crypto, fits the
job's existing "no AWS creds needed" design). Add `aws/auth-stack.json` to
`ci.yml`'s `cfn-lint` file list. **Must also fix** `ci.yml`'s existing inline
FastAPI smoke test, which currently calls `/predict/demo/SYN027` and
`/model/info` with no auth header — once those routes require auth it will
start failing; narrow that inline smoke test to `/health` only and let the
new `test_auth.py` be the one place that exercises authenticated calls.

## 6. Deploy sequencing (`.github/workflows/deploy.yml`)

`auth-stack.json` must exist **before** `lambda-stack.json`'s first deploy
(opposite position from the dashboard stack) — routes should require auth
from the function's first invocation, no soft-launch window where they
don't:

1. Registry infra / ECR repo (unchanged).
2. **New:** deploy `aws/auth-stack.json` → stack `distress-model-auth`.
3. **New:** read its `UserPoolId`/`UserPoolClientId` outputs.
4. Build/push image (unchanged).
5. `Deploy inference Lambda stack` — add
   `CognitoUserPoolId=... CognitoClientId=...` to `--parameter-overrides`.
6. Retrain pipeline stack (unchanged — those Lambdas don't serve the public
   API).
7. Dashboard hosting stack (unchanged — still blocked on AWS Support, as
   before; not newly broken by this change).
8. Re-deploy Lambda stack with `DashboardOrigin` known — **also** keep
   passing the Cognito parameters (CloudFormation requires all
   non-defaulted parameters on every `deploy` call).
9. Build dashboard — add `NEXT_PUBLIC_COGNITO_USER_POOL_ID`/
   `NEXT_PUBLIC_COGNITO_CLIENT_ID` to the build env, alongside
   `NEXT_PUBLIC_API_BASE_URL`.
10. Sync/invalidate/summary (unchanged).

`ci.yml` needs no deploy-ordering change — just placeholder values for the
two new `NEXT_PUBLIC_COGNITO_*` vars in its dashboard build step, same
treatment as the existing placeholder `NEXT_PUBLIC_API_BASE_URL`.

**IAM policy additions required** — neither deploy identity has any
`cognito-idp:*` permission today:
- `aws/iam-deploy-policy-resources.json` (the `finance-distress-deploy` IAM
  user): new statement with `cognito-idp:CreateUserPool`, `DeleteUserPool`,
  `DescribeUserPool`, `UpdateUserPool`, `CreateUserPoolClient`,
  `DeleteUserPoolClient`, `DescribeUserPoolClient`, `UpdateUserPoolClient`,
  `TagResource`, `UntagResource`, `AdminCreateUser`, `AdminSetUserPassword`,
  `AdminGetUser`, `ListUsers` — `Resource: "*"` (pool creation can't be
  ARN-scoped before the pool exists, same shape as this file's existing
  `ECRPushPull`/`StepFunctionsAndEventBridge` statements).
- `aws/github-oidc-stack.json`'s `distress-model-cicd-permissions` policy:
  identical new statement (this repo already duplicates every other
  service's permissions across both files — same pattern).
- Check both files against the 6,144-non-whitespace-character cap
  (`CLAUDE.md` already notes this limit was hit once before); split into a
  third policy file if the Cognito addition pushes either over it — a
  build-time check, not something to pre-guess.

## What's deferred / out of scope

AWS CloudFront/Function-URL account-verification blocker (external, tracked
via `aws-support.txt`, unrelated to auth); API Gateway (rejected — unconfirmed
workaround, real added cost); SMS MFA; Hosted UI/OAuth redirect; self-service
signup; Cognito "remember this device" tracking; QR-rendering library choice
(plain-text TOTP secret is a valid zero-dependency fallback); SES/email
delivery; automated credential rotation; custom rate-limiting beyond
Cognito's defaults.

## Files touched

**New:** `aws/auth-stack.json`, `src/auth.py`, `dashboard/lib/auth.ts`,
`dashboard/components/AuthGate.tsx`, `dashboard/components/LoginForm.tsx`,
`tests/test_auth.py`.

**Changed:** `src/app.py` (auth dependency on 3 routes), `dashboard/lib/api.ts`
(bearer header), `dashboard/app/layout.tsx` (auth gate), `dashboard/package.json`
(+amazon-cognito-identity-js), `dashboard/.env.local.example`,
`requirements.txt` (+PyJWT[crypto]), `aws/lambda-stack.json` (+2 params/env
vars), `.github/workflows/deploy.yml` (new stack + reordering),
`.github/workflows/ci.yml` (new test, cfn-lint entry, narrowed smoke test),
`aws/iam-deploy-policy-resources.json` + `aws/github-oidc-stack.json`
(+Cognito IAM statement), `CLAUDE.md` (pre-deploy list, provisioning steps,
resource names).

## Verification

- `cfn-lint aws/auth-stack.json` and the full `cfn-lint aws/*-stack.json`
  list.
- `python tests/test_auth.py` (all 6 cases above) plus the full existing
  `CLAUDE.md` pre-deploy suite.
- Local manual walkthrough: `uvicorn app:app` locally with
  `COGNITO_USER_POOL_ID`/`COGNITO_CLIENT_ID` set to a real (dev) pool, run
  `next dev` against it, exercise first-login (new password → MFA setup →
  QR/secret → confirm code) and returning-login (password → 6-digit code)
  flows end-to-end in a browser before relying on the deployed stack.
- Full live E2E (real CloudFront URL, real public Function URL) stays
  blocked until AWS Support resolves the account verification — call this
  out explicitly when reporting "done," not silently treated as complete.
