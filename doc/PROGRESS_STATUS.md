# Progress status -- saved 2026-10-17, updated 2026-10-22

Scratch file for session handoff. Read this first when picking the
session back up.

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

- **The Lambda Function URL anonymous-403 restriction is still active --
  this is now the sole remaining blocker on reaching the dashboard
  end-to-end.** It's the other half of the same original AWS Support case
  as the CloudFront issue, but did NOT clear with it: a direct, anonymous
  `curl` to `https://tg5xe3bzwsu2uexhrmnxbncidq0clvqy.lambda-url.ap-south-1.on.aws/health`
  still returns `403 Forbidden` / `AccessDeniedException` at the
  authorization layer, confirmed fresh on 2026-10-21, even though
  `AuthType: NONE` and the resource policy are both correct (checked via
  `get-function-url-config` / `get-policy`). This means no anonymous
  browser request can reach the API at all yet, regardless of CORS being
  fixed.
- **Standalone support ticket SUBMITTED 2026-10-22, Case ID
  `179258268000268`.** Filed using `doc/aws-support-function-url-403.txt`
  verbatim (the account-wide repro via a disposable test Lambda, the
  distinction from the already-resolved CloudFront half). Can't poll
  status via CLI/API (`SubscriptionRequiredException` -- this account has
  no Business/Enterprise support plan), so check the Support Center
  Console for replies. This is now the single open item blocking the
  dashboard end-to-end.
- IAM permission drift on `finance-distress-deploy` -- **RESOLVED
  2026-10-22**, see the dated TODO section below for the full
  policy-by-policy verification.
- **Known gap, documented in `CLAUDE.md`:** the post-deploy verification
  command (`aws lambda invoke ... aws/test_invoke_predict_payload.json`)
  targets `/predict/demo/SYN027`, which now requires auth -- it will 401,
  not return a prediction. No scripted fix for this yet (would need a real
  Cognito login to generate a token). Use `/health` instead for a quick
  liveness check, verify authenticated routes manually via the dashboard
  once it's reachable.

## Next steps, roughly in order

1. ~~Post the Function URL issue to AWS Support.~~ **Done 2026-10-22** --
   Case ID `179258268000268`. Waiting on AWS's response; check the Support
   Center Console periodically (no CLI/API polling on this plan).
2. Once AWS lifts the Function-URL restriction: no code changes needed,
   the dashboard is already built, synced, and CORS-correct -- it'll work
   as soon as anonymous Function URL invocation is unblocked.
3. Provision the first admin Cognito user (commands in `CLAUDE.md`'s MFA
   section) and walk through the login flow (new password -> TOTP QR
   setup -> confirm code) manually in a browser once the Function URL
   restriction clears -- this has never been tested against a real,
   reachable frontend yet, only locally/via unit tests.

## TODO -- 2026-10-22

Full project scan while still blocked on the Function URL restriction.
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

**Remaining tasks that don't depend on AWS lifting the Function URL
restriction:**

- Submit the standalone ticket (`doc/aws-support-function-url-403.txt`) via
  the AWS Support Console -- the actual unblocking lever, has to be pasted
  in by hand.
- Test the full MFA login flow (new password -> TOTP QR -> confirm code)
  against local `uvicorn` + `next dev` -- never exercised end-to-end as a
  real human login yet, only unit-tested.
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
