# Progress status -- saved 2026-10-17, updated 2026-11-15

Scratch file for session handoff. Read this first when picking the
session back up.

## 2026-11-25: retrain could never promote -- fixed (#52, deployed)

Looked at the weekly retrain's numbers (step 6) for the first time. All 8
runs from 2026-10-06 to 11-24 were **rejected**: candidate AUC 0.86-0.98 on
the 13 held-out (2023+) companies, but the live model `v1790617273`
(promoted 2026-09-28) scored **1.000 every week**. It predates the time
split (enabled 2026-10-10), so it almost certainly trained on those
companies; it may also predate the headline-leak fix. The gate needed
candidate - 1.000 > 0.01, which can't happen.

Fix: the registry now stores each promoted model's training provenance
(`eval_mode`, `trained_before`). A current model without it, or one that
may have trained on this run's held-out companies, isn't used as the bar;
the candidate must instead reach **AUC >= 0.85** (`PROMOTION_MIN_AUC`, set
on the train Lambda). The state machine branches on an explicit `promote`
flag, and both notifications carry `decision_reason`.

**Deployed and verified 2026-11-25 10:19 UTC** (deploy run 57): the live
state machine's `ShouldPromote` branches on `$.evaluation.promote`, the
"kept" notification carries `decision_reason`, and
`distress-model-train-evaluate` has `PROMOTION_MIN_AUC=0.85` with
`EVAL_SPLIT_CUTOFF_DATE=2023-01-01`. No retrain was started by hand; the
live model is still `v1790617273` until the scheduled run.

**Expected at the next retrain (Tue 2026-12-01 18:10 UTC):** promotion on the minimum
bar if the candidate scores like the last runs (Nov 24: 0.976). Then check:
the registry item has `eval_mode: time`, `trained_before: 2023-01-01`;
`/health` shows the new version; and whether live scores are less
polarised than the old model's ~2% / ~98%.

Also checked: **Infosys is fixed** in `datasets/real_companies.json` (market
cap dropped by the currency guard, book value used). The training set has
been the same **51 records since 2026-10-13** (US 17/15, India 15/4).

## Where things stand (end of 2026-11-15 session)

All work up to 2026-11-25 is merged and deployed (PRs #37-#52). Nothing is
open. #48 added the S&P 500, #49 fixed the market status column's universe,
#50 added a manual "Refresh now" for market data (deployed 13:17 UTC;
`/health` 200, API role has the new `market-data-manual-refresh` policy). The dashboard has four pages: Company Score, Market Overview,
Insolvency Watch and Model Info.

**Company Score, after PRs #44-#46:**
- **Search (#45):** the ticker box searches by ticker (3+ characters) or
  company name (5+). `GET /search` returns index members from the weekly
  snapshot first, then Yahoo Finance matches (`yfinance.Search`, equities
  only, cached 6h, 8s cap). If Yahoo fails, index results come back with
  `online_ok: false`. Exactly one match auto-fills the form. This replaced
  the old "Data available, autopopulate?" prompt.
- **Scoring (#44):** figures are scored as soon as an auto-fill completes.
  `dashboard/lib/useScorer.ts` fingerprints each request and never re-sends
  identical inputs: unchanged -> skipped ("Scored ✓"); identical in-flight
  -> joined; superseded responses -> dropped. POST /predict is unchanged.
- **Market status column (#46):** a donut of the NSE LargeMidcap 250 by
  Altman Z zone (safe / grey / distress) or model risk band, from
  `/market/overview`, with the scored company outlined. Three columns at
  1500px and wider, stacked below. `StatusDonut` is shared with Market
  Overview's `RiskDonut`.

**S&P 500 universe (#48, this PR):** a second index next to the NSE one.
- `src/market_data.py` has a `UNIVERSES` registry (`nse`, `us`). The S&P 500
  list comes from the datasets/s-and-p-500-companies CSV on GitHub (S3 seed
  at `market-data/us-sp500/constituents.csv` as fallback). Yahoo tickers use
  dashes for class shares (BRK.B -> BRK-B). Industry = GICS sector.
- New Lambda `distress-model-us-snapshot`, run as **4 shards** on staggered
  Sunday schedules (02:00, 02:25, 02:50, 03:15 UTC): 500 companies don't fit
  in one 15-minute run at the NSE pace (250 in ~12 min). Each shard writes
  `market-data/us-sp500/parts/part-<i>-of-4.json`; once all four exist,
  each shard re-merges them into `latest.json` (newer record wins). Past the
  time budget, remaining companies are recorded as "Skipped", not lost.
- API: `?universe=nse|us` on `/companies`, `/companies/{symbol}` and
  `/market/overview`; `/search` and `/lookup` cover both indexes. HAL is a
  real collision (Hindustan Aeronautics on NSE, Halliburton in the S&P 500),
  so links carry the universe: `#/score/HAL/us`, `#/market/us`.
- Dashboard: the market status column's selector is enabled and follows
  the loaded company's market; Market Overview has an NSE 250 / S&P 500
  switch. The "Try a sample company" card is removed (synthetic SYN tickers;
  `/predict/demo` stays on the API for the post-deploy check).
- **First US snapshot: done 2026-11-15 12:58 UTC** (shards invoked by hand,
  one after another). 503 companies, **450 complete**, 0 fetch errors, 0
  skipped for time, all USD. Of the 53 incomplete: **44 Financials** (banks,
  insurers, brokers: AIG, C, MS, ...) without the current/non-current split,
  shown as "model doesn't apply"; 9 others missing one figure (REITs ARE,
  DLR, DOC, VTR and JNJ, HONA, VYLR without retained earnings; ELV, HUM
  without the current split). As-of years: 410 FY2025, 93 FY2026.
- **Timing surprise:** each US shard took ~40 s (126 companies), so the
  whole S&P 500 takes ~3 min, not the ~30 planned for from the NSE run
  (250 in ~12 min on Sunday 01:30). The 4-shard split is therefore far more
  than needed; it's harmless, but one shard would do. Worth checking whether
  the NSE run is slow because of NSE/Indian tickers on Yahoo or because of
  rate limiting at that hour before changing anything.
- **#49 (market status fix):** each score now carries its market (the
  loaded company's, else an .NS/.BO suffix, else the index on screen); the
  card switches to it for every new score and marks the company only there.

**Manual refresh (#50):** Market Overview has a "Refresh now" button per
index (NSE ~12 min, S&P 500 ~3 min in practice).
- `POST /market/refresh?universe=nse|us` starts the snapshot job in the
  background (409 while one runs); `GET /market/refresh` reports
  idle/running/done/failed/stale and progress.
- Status lives in `market-data/<index>/refresh-status.json`. The API writes
  it on request and the job itself writes it too, so Sunday's runs show the
  same way. Stale = no heartbeat for 30 min.
- On a manual refresh the S&P 500's 4 parts run one after another, each
  starting the next.
- The API's snapshot cache is now 5 min (was 1 h).
- **Not verified live yet:** a real click. The first one creates the status
  file, and the S&P 500 chain needs the snapshot role's new invoke
  permission. If the button reports "failed", the error text says which
  step broke.

**Data state:** the NSE snapshot was re-run manually at 10:57 UTC after the
currency fix (#41): 250 fetched, 203 complete, 0 errors. Infosys and HCL Tech
report in USD, so their market caps are dropped. The live training dataset
still has the old Infosys record until the next weekly fetch (Sunday), since
the #43 fix only applies to new fetches.

**Not verified yet:**
- **Live Yahoo search from Lambda (#45).** The sandbox can't reach Yahoo,
  and `/search` needs a login token, so this needs a manual check on the
  dashboard: type "zomat" and expect Zomato to auto-fill. Index-only
  results with "Online search unavailable" mean Yahoo is failing from AWS.
- **Whether real Indian companies score as polarised** (near 2% / 98%) as
  the synthetic sample does. Look at the live Market Overview donut.

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

Status: all four PRs merged: #39 (UI shell), #40 (NSE data layer),
#41 (Market Overview), #42 (Insolvency Watch). Follow-ups #43 (training data),
#44 (auto-score + dedup), #45 (search), #46 (market status column) are
merged too; see "Where things stand" at the top.

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
4. ~~Dashboard redesign, PRs 1-4.~~ **Done 2026-11-15** (#39-#42, plus
   #44-#46).
5. Check the live Yahoo search on the dashboard (see "Not verified yet" at
   the top).
6. ~~Look at the weekly retrain's eval numbers.~~ **Done 2026-11-25:**
   found the gate could never promote; fixed (see the top section). Left:
   confirm the next retrain promotes and the registry records provenance.
7. **US universe:** shipped (#48), first snapshot done (450/503 complete).
   Left: look at the live S&P 500 donut, and consider 1 shard instead of 4
   (see the timing note above).
8. **Mixed fiscal years in training records:** `fetch_financials_for_ticker`
   fills a blank latest-year field from an older year. The dashboard path
   doesn't; the training path should get the same one-year rule, checked
   with `cross_validate.py` before and after.
9. Upgrade Next.js (16.4.0 aborts every other build with a vulnerability
   notice).
10. Refresh `dashboard/data/insolvency_cases.json` as RCom, Videocon and
    Amtek Auto move; `tests/test_insolvency_data.py` validates edits.
11. **New section: Event Breakout** (trading momentum after RBI / FOMC /
    Union Budget, Nifty and Bitcoin). Research, gap analysis and strategy
    v1 in `doc/event-breakout-strategy.md` (2026-11-25). Event calendar
    done: `data/events/macro_events.json` (92 events 2021-2026, incl. the
    upcoming RBI Dec 4 and FOMC Dec 9, 2026), `tests/test_macro_events.py`.
    Notable: RBI **hiked** to 5.50% on 2026-10-07 and the Fed **hiked** to
    3.75-4.00% on 2026-09-16. **All 36 past RBI entries verified against
    RBI's own Governor's Statements (2026-11-25)**, now linked as official
    sources. Network: rbi.org.in, rbidocs, fbil, nseindia, nsearchives,
    niftyindices, sebi, kite/zerodha/upstox docs are allowed in the
    environment; use `www.rbi.org.in`, as bare `rbi.org.in` is refused.
    Daily-data study done (2026-11-25): see doc/event-breakout-strategy.md
    §6a. Headlines: only the Budget moves Nifty more than an ordinary day;
    India VIX falls on event days (crush); FOMC -> Nifty gap-and-go lost
    8W/16L (drop it); RBI follow-through no edge. Data:
    data/events/index_daily.csv (NSE files, refresh with
    data/events/fetch_index_history.py). Next: Event Watch dashboard
    section (strategy trade outcome = success/failure), then FBIL surprise.
    Superseded next step: the daily-data study (gaps, ranges,
    follow-through vs non-event days). Data plan: daily Nifty/Bank Nifty/
    VIX from NSE (bhavcopy; NSE also has an official MCP server, EOD 5 yrs
    + delayed live, not reachable from this sandbox), BTC minute data from
    a public exchange API, Nifty intraday collected going forward.

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
