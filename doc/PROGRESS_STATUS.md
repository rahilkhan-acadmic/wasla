# Progress status -- saved 2026-10-17, updated 2026-11-09

Scratch file for session handoff. Read this first when picking the
session back up.

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

**Next real step:** provision the first admin Cognito user and walk the
login flow (new password -> TOTP QR -> confirm code) against the live
dashboard at `https://d3777jqr8y94ft.cloudfront.net/` -- never exercised
end-to-end as a real human login, only unit-tested so far.

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
2. Provision the first admin Cognito user (commands in `CLAUDE.md`'s MFA
   section) and walk through the login flow (new password -> TOTP QR
   setup -> confirm code) manually in a browser against the now-live
   dashboard (`https://d3777jqr8y94ft.cloudfront.net/`) -- this has never
   been tested against a real, reachable frontend yet, only locally/via
   unit tests.

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
