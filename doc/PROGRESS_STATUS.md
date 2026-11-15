# Progress status -- saved 2026-10-17, updated 2026-11-15

Scratch file for session handoff. Read this first when picking the
session back up.

## First real human login works end-to-end (2026-11-15)

Worked from a claude.ai/code **cloud** session for the first time (see
`doc/claude-code-cloud-setup.md`). AWS access there comes through the
official `aws-core` plugin's MCP server, signed in as
`finance-distress-deploy`. Plain `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`
environment variables do **not** work in that sandbox: they reach the
session as placeholder values, so SigV4 signing fails with
`InvalidClientTokenId`. The plugin is the working path.

- **First admin user provisioned**: `rahilkhan` in pool
  `ap-south-1_kcGHQgK50` (created by the account owner as root, via the
  Cognito console). Status `CONFIRMED`, TOTP MFA registered.
- **Two login bugs found and fixed**, both in PR #37 (merged and deployed by
  `deploy.yml` run 42):
  1. The first-login new-password step failed with *"Cannot modify an
     already provided email"*. `dashboard/lib/auth.ts` echoed the user's
     existing attributes back in `completeNewPasswordChallenge`, and Cognito
     refuses to re-set an attribute the user already has. It now sends `{}`.
  2. The MFA setup step only printed the raw secret, with no QR code.
     `dashboard/components/LoginForm.tsx` now renders an `otpauth://` URI as
     a QR code client-side (`qrcode.react` 4.2.0), with the text key kept as
     a manual fallback.
- **Verified by the account owner**: full login (password, then QR scan,
  then 6-digit code) works against the live dashboard.

**Things noticed but not yet acted on:**
- `/health` reports `model_version: null` (the registry is configured).
  Possibly the model only loads on the first prediction. Worth confirming.
- Next.js 16.4.0 aborts every other `next build` with a "known security
  vulnerability" notice; the retry passes. Upgrade Next.js in its own PR.
- `finance-distress-deploy` can't call `cloudformation:ListStacks`,
  `lambda:ListFunctions`, `cognito-idp:AdminListUserAuthEvents` or
  `cognito-idp:AdminSetUserMFAPreference`. Describing resources by name
  works, so nothing is blocked today.
- The AWS GitSync bot posts "Change set creation failed" on every PR (it
  also did on PR #36). The `distress-model-claude-code` stack is healthy and
  the PRs deploy fine; most likely a no-changes preview reported as failed.

## Dashboard redesign: agreed plan (2026-11-15)

Status: PR 1 (#39), PR 2 (#40) and PR 3 (#41) merged; PR 4 open (Insolvency Watch).

**PR 4 as built:** `dashboard/data/insolvency_cases.json`, 20 hand-curated
cases (13 acquired, 4 liquidated, 3 ongoing; 11 of RBI's first 12, Era Infra
left out as unverifiable), each with at least one source link. Unverifiable
fields are null rather than estimated. `tests/test_insolvency_data.py`
validates the structure and keeps the `in_training_labels` flags in exact
sync with `india_distress_labels.csv`. The page shows facts only, with no
model scores. Status as of 2026-11-15; this needs a manual refresh as cases
move (RCom, Videocon and Amtek Auto are the open ones).

**Training data fixed (PR after #42):**
- **Infosys, LIVE training data:** the 2026-11-10 dataset had an INR market
  cap over USD statements, giving a market-value / liabilities ratio of 707.6
  (peers 1.6-16.7; Altman Z ~428 instead of ~4.6). `nse_client` now drops a
  market cap whose currency differs from the statements' in the training
  fetch too (shared `_market_cap_and_currency`), so the next weekly fetch
  corrects it. Cross-validated AUC on `real_companies_full.json`:
  0.829 ± 0.146 before and after. Infosys is healthy either way, so this is a
  correctness fix, not an accuracy change.
- `india_distress_labels.csv`: removed `ESSARSHIPPING.BO` (Essar Shipping
  mislabelled as Essar Steel; Essar Steel delisted in 2015, so there's no
  ticker to re-point to). Corrected admission dates: Videocon 2018-06-06 (and
  not liquidated), DHFL 2019-12-03, RCom 2018-05-15 (stayed 2018-05-30 to
  2019-04-30). These distressed rows only feed the offline `india` source;
  the live pipeline (`FETCH_MARKETS=us,india_gsm`) uses this file's healthy
  rows only.
- `tests/test_india_training_labels.py` ties every "NCLT CIRP admission"
  date to the sourced Insolvency Watch data, and fails on the old file.
- Not addressed: `fetch_financials_for_ticker` still fills a blank latest-
  year field from an older year (mixed periods in one record). That's a
  training behaviour change, worth its own look.

**First real snapshot (2026-11-15 10:39 UTC, right after PR 2 deployed):**
the constituent CSV downloaded fine from niftyindices.com (no seed needed);
250/250 companies fetched with 0 errors; 203 complete. 242 have FY ending
March 2026. Of the 47 incomplete, 41 are Financial Services: banks, NBFCs
and insurers have no current assets/liabilities split, so Altman-style
features don't exist for them. PR 3 labels these "model doesn't apply".
Infosys's statements are in USD on Yahoo while its market cap is INR,
which inflates the market-value ratio ~85x. PR 3 detects
`financialCurrency != trading currency` and drops the market cap (book
value is used instead). The live snapshot still has the mixed-currency
Infosys record until the job re-runs (Sunday, or a manual invoke).

**PR 3 as built:** `src/scoring.py` (shared by /predict and the overview,
identical results, tested); `GET /market/overview` scores every complete
company with the CURRENT model on request (one batched predict, cached
per snapshot + model version, so a mid-week promotion shows immediately).
Dashboard Market Overview: risk donut (click to filter), loss-making tile,
not-scored tile (split into "doesn't apply" vs missing data), sortable and
filterable table, rows open `#/score/<SYMBOL>`. On the bundled synthetic
sample, the current model is very polarised (no "moderate" companies);
see whether real Indian companies look the same before trusting the pie.

**PR 2 as built:**
- `src/market_data.py` + Lambda `distress-model-nse-snapshot` (in
  `aws/automation-stack.json`, schedule Sundays 01:30 UTC) writes
  `s3://distress-model-<account>/market-data/nse-largemidcap250/latest.json`
  plus `history/<date>.json`. The constituent list comes from niftyindices.com,
  then NSE's archive host, then a manually uploaded seed CSV at
  `market-data/nse-largemidcap250/constituents.csv` (same columns as NSE's
  CSV) if both hosts block AWS. Neither host was reachable from the
  claude.ai cloud sandbox, so this is untested against the real sites.
- `deploy.yml` async-invokes the job once if `latest.json` doesn't exist, so
  the ticker list fills in a few minutes after the first deploy rather
  than on the next Sunday.
- API: `GET /companies`, `GET /companies/{symbol}`, `GET /lookup/{ticker}`
  (auth required). Custom tickers are fetched live (NSE, then BSE, then
  bare), cached 6h per warm Lambda, 20s deadline.
- Auto-fill takes every figure from **one fiscal year**
  (`nse_client.fetch_financials_with_period`). The older
  `fetch_financials_for_ticker`, used by **training**, still falls back to
  an older year per field when the latest is blank. Not changed in PR 2;
  worth a deliberate look, since it mixes periods in training records.
- Display data only: nothing from the snapshot feeds training.

Four separate PRs, in this order:
1. **UI shell** (front-end only): top bar with burger | logo + "WASLA" |
   breadcrumb | sign-out; collapsible left panel; pages Company Score,
   Market Overview, Model Info; form-left / chart-right split; bar chart of
   the entered financials and a Z-score gauge.
2. **NSE data layer**: weekly snapshot of the **Nifty LargeMidcap 250**
   (yfinance) to S3/DynamoDB, plus `GET /companies`,
   `GET /companies/{ticker}` and `GET /lookup/{ticker}`. Powers the ticker
   dropdown, auto-fill and custom-ticker lookup. Must be backend-side: the
   browser can't call NSE/Yahoo directly.
3. **Market Overview**: score all 250 weekly; pie of Low / Moderate / High
   risk (banded probability) plus a separate "N loss-making" count. Not a
   pie slice, because loss-making overlaps the risk bands. Needs a visible
   "screening signal, not a rating" note, given the thin India training data.
4. **Insolvency Watch**: hand-curated list (IBBI/NCLT sources, one link per
   row) of major listed CIRP cases since 2016, with outcome (acquired /
   liquidated / ongoing / withdrawn), acquirer and recovery %. Timeline,
   outcome and recovery charts. The list can double as training labels, but
   only with a date split: "what the model would have said" may be shown
   only for held-out cases, never for training companies. Many pre-2022
   cases have no pre-failure yfinance data, so they appear facts-only.

## Dashboard is now fully live end-to-end (2026-11-09)

The Function URL anonymous-403 was **not** actually the account-verification
restriction riding along behind the CloudFront issue -- that theory held as
of 2026-10-22 but turned out to be wrong. The real cause: AWS changed Function
URL requirements in October 2025 -- `AuthType: NONE` now needs **two**
resource-policy statements, `lambda:InvokeFunctionUrl` *and*
`lambda:InvokeFunction` (the latter scoped with the
`lambda:InvokedViaFunctionUrl` condition). `aws/lambda-stack.json` only ever
granted the first one. Confirmed by the error message changing from the old
generic account-block text to a specific
`"Invoking a Function URL requires both the lambda:InvokeFunctionUrl and
lambda:InvokeFunction permissions"` -- which is exactly what
https://docs.aws.amazon.com/lambda/latest/dg/urls-auth.html documents.

Fixed by adding `ApiFunctionUrlPublicInvokeFunctionPermission` (a second
`AWS::Lambda::Permission` with `Action: lambda:InvokeFunction`,
`Principal: "*"`, `InvokedViaFunctionUrl: true`) next to the existing
`ApiFunctionUrlPublicInvokePermission` in `aws/lambda-stack.json`. Full test
suite + `cfn-lint` run clean, deployed directly via
`aws cloudformation deploy --template-file aws/lambda-stack.json
--stack-name distress-model-lambda --region ap-south-1`. Verified live:
anonymous `curl .../health` -> `200 {"status":"ok",...}`,
CloudFront (`https://d3777jqr8y94ft.cloudfront.net/`) -> `200`.

**Standalone AWS Support case `179258268000268` (Function URL 403) can be
closed/withdrawn** -- not an AWS-side account restriction, was a missing
resource-policy statement in our own template. No further AWS Support
action needed for either half of the original combined case; both are
resolved now, one by AWS lifting the CloudFront verification block
(2026-10-21), the other by this code fix (2026-11-09).

~~**Next real step:** provision the first admin Cognito user and walk the
login flow.~~ **Done 2026-11-15**, see the section at the top of this file.

## What's done and live in production

- **MFA/Cognito auth shipped and deployed.** PR #27 (feature) and PR #28
  (permission fix) both merged into `main`. `distress-model-auth` (Cognito
  User Pool, TOTP-only MFA, no self-signup) is deployed; `distress-model-api`
  Lambda is redeployed with `COGNITO_USER_POOL_ID`/`COGNITO_CLIENT_ID` wired
  in. `/predict`, `/predict/demo/{ticker}`, `/model/info` now require a
  valid Cognito ID token (`Authorization: Bearer ...`); `/health` stays open.
  See `CLAUDE.md`'s "MFA-gated access" section and `mfa-plan.md` for full
  design detail.
- **CloudFront account-verification restriction cleared, dashboard stack
  deployed (2026-10-21).** AWS Support resolved the CloudFront half of the
  account-verification case. Deleted the manual S3 bucket + OAC left over
  from the console-fallback attempt (confirmed empty first), then ran a
  clean `aws cloudformation deploy --template-file aws/dashboard-stack.json
  --stack-name distress-model-dashboard --region ap-south-1`. Stack reached
  `CREATE_COMPLETE`: `DistributionId=E3SU1RNVVEI0GH`,
  `DistributionDomainName=d3777jqr8y94ft.cloudfront.net`,
  `DashboardBucketName=distress-model-dashboard-345736954421`.
- **Dashboard build synced and CORS fixed (2026-10-21).** Rebuilt the
  dashboard with real build-time env vars (API Function URL, Cognito User
  Pool/Client IDs -- the `out/` build on disk before this had empty values
  and would have shipped broken), synced to the bucket, invalidated the
  CloudFront cache. Also fixed two CORS bugs in `aws/lambda-stack.json`:
  `DashboardOrigin` was still blank, and `AllowHeaders` was missing
  `authorization` (the dashboard sends a bearer token on every protected
  call). Both fixed and redeployed; verified live via a manual OPTIONS
  preflight matching the dashboard's origin. Committed in `536b38a`.

## What's still blocked

Nothing AWS-side anymore. The Lambda Function URL anonymous-403 (previously
listed here as "the sole remaining blocker") is **RESOLVED 2026-11-09** --
see the section at the top of this file. It was never the account
restriction it was assumed to be; it was a missing `lambda:InvokeFunction`
resource-policy statement in `aws/lambda-stack.json`, fixed in code.
Standalone support case `179258268000268` can be closed -- AWS Support
action was never actually required for it.

IAM permission drift on `finance-distress-deploy` -- **RESOLVED
2026-10-22**, see the dated TODO section below for the full
policy-by-policy verification.

**Known gap, documented in `CLAUDE.md`:** the post-deploy verification
command (`aws lambda invoke ... aws/test_invoke_predict_payload.json`)
targets `/predict/demo/SYN027`, which now requires auth -- it will 401,
not return a prediction. No scripted fix for this yet (would need a real
Cognito login to generate a token). Use `/health` instead for a quick
liveness check (now reachable anonymously, confirmed live), verify
authenticated routes manually via the dashboard.

## Next steps, roughly in order

1. ~~Post the Function URL issue to AWS Support.~~ ~~Done 2026-10-22,
   Case ID `179258268000268`.~~ Turned out unnecessary -- root cause found
   and fixed in code 2026-11-09, case can be closed.
2. ~~Provision the first admin Cognito user and walk through the login
   flow.~~ **Done 2026-11-15**: `rahilkhan` logs in with password + TOTP
   against the live dashboard, after the two fixes in PR #37.
3. Close AWS Support case `179258268000268` (needs the account owner's
   console login; `finance-distress-deploy` only has support read access).
4. Dashboard redesign, PRs 1-4 in the plan at the top of this file.
5. Look at the weekly retrain's actual eval numbers per run (still only
   checked that executions `SUCCEEDED`; last one 2026-11-10).

## TODO -- 2026-10-22

Full project scan while still blocked on the Function URL restriction (this
has since been resolved 2026-11-09, see top of file).
Confirmed the weekly retrain schedule (`distress-model-weekly-retrain`) is
healthy -- 4 consecutive `SUCCEEDED` executions since the time-split eval
went live (2026-09-29, 10-06, 10-13, 10-20).

**RESOLVED 2026-10-22.** IAM permission drift found on
`finance-distress-deploy` (the human terminal user) -- both repo files were
brought to correct target state (commit `68964fa`), then applied live by
the account owner from their own terminal (the EC2 instance role is
deliberately denied `iam:CreatePolicyVersion` on both policies, confirmed
via a live `AccessDenied` test -- this is the identity-separation boundary
in `CLAUDE.md`'s "IAM identities" section, not a bug to fix).

| # | Policy ARN | File | `Sid` section | Live result |
|---|---|---|---|---|
| 1 | `FinanceDistressDeployPolicy` | `aws/iam-deploy-policy-resources.json` | `CognitoUserPoolManagement` | **Applied.** New default version `v18` (2026-10-22), diffed byte-for-byte against the repo file from this instance -- exact match. |
| 2a | `FinanceDistressDeployPolicy` | `aws/iam-deploy-policy-resources.json` | `CloudFrontDashboard` | **Applied.** Same `v18`, same exact-match diff. |
| 2b | `FinanceDistressDeployPolicy` | `aws/iam-deploy-policy-resources.json` | `S3ModelAndDataBuckets` (actions folded into existing statement) | **Applied.** Same `v18`, same exact-match diff. |
| 3 | `FinanceDistressDeployPolicyManagement` | `aws/iam-deploy-policy-management.json` | `SupportCaseReadOnly` | **Applied.** New default version `v4` (2026-10-22, ~6 min after being set, up from `v3` which was 17 days old) -- account owner pasted the live document, manually confirmed all 13 statements match the repo file exactly (EC2 role can't read this policy itself, by design). |

`finance-distress-deploy` now has everything the direct-deploy path in
`CLAUDE.md` needs for `auth-stack.json` and `dashboard-stack.json` --
Cognito, CloudFront, S3 bucket-policy, and Support-case read access, all
live and matching the repo. No further action needed on this item.

Deliberately did not automate the apply step itself -- doing so would mean
some CI-triggered identity could rewrite the human terminal user's own
permissions on a merge, which reopens the same escalation question the
three-identity split in `CLAUDE.md` exists to avoid. Revisit only with a
specific design for that boundary, not as a side effect of convenience.

**Remaining tasks:**

- ~~Test the full MFA login flow (new password -> TOTP QR -> confirm
  code).~~ Done against the live dashboard 2026-11-15 (PR #37).
- Widen US `n_healthy`/`n_distressed` now that the CIK-diversity bug is
  fixed (flagged as a follow-up in the time-split work, not yet done).
- Keep watching the weekly retrain's AUC hold up over more runs before
  trusting the 0.93 result -- check actual eval numbers per run, not just
  that the Step Functions execution `SUCCEEDED`.
- India's healthy-company list is still thin (5 mega-caps vs. 15
  distressed) -- real scale-mismatch gap, addressable independently.
- `news_sentiment` is still a hardcoded `0.0` -- needs a real,
  label-independent, point-in-time news source; unsolved design problem.
- `data/sources/uk_companies_house_labels.py:27` has a standing TODO
  marking the financials half as unimplemented.

## Cost reminder

Per `CLAUDE.md`: stop this EC2 instance when not actively in use.
```bash
aws ec2 stop-instances --instance-ids <this-instance-id> --region ap-south-1
```
