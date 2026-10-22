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
- `doc/aws-support-followup.txt` was rewritten (2026-10-21, committed in
  `536b38a`) to report the CloudFront fix and ask specifically about this
  remaining Function URL restriction, but is **not yet sent** -- still
  needs to be posted via the AWS Console (Support Center), since the
  Support API requires a Business/Enterprise support plan this account
  doesn't have (`SubscriptionRequiredException` confirmed via CLI, same
  limitation as before).
- **One permission change is file-only, not applied live yet:**
  `aws/iam-deploy-policy-management.json` (the `support:DescribeCases`/
  `DescribeCommunications` grant for `finance-distress-deploy`, the human
  terminal user) was edited and committed, but applying it to the live
  `FinanceDistressDeployPolicyManagement` managed policy needs to run from
  your own terminal (the EC2 instance role can't modify that policy by
  design):
  ```bash
  aws iam create-policy-version --policy-arn arn:aws:iam::345736954421:policy/FinanceDistressDeployPolicyManagement --policy-document file://aws/iam-deploy-policy-management.json --set-as-default --region ap-south-1
  ```
  (The equivalent grant on the EC2 instance role itself IS already live --
  that's how the CloudFront/Support checks this session worked.)
- **Known gap, documented in `CLAUDE.md`:** the post-deploy verification
  command (`aws lambda invoke ... aws/test_invoke_predict_payload.json`)
  targets `/predict/demo/SYN027`, which now requires auth -- it will 401,
  not return a prediction. No scripted fix for this yet (would need a real
  Cognito login to generate a token). Use `/health` instead for a quick
  liveness check, verify authenticated routes manually via the dashboard
  once it's reachable.

## Next steps, roughly in order

1. Post the rewritten follow-up in `aws-support-followup.txt` to the open
   AWS Support case via the Console -- specifically flags that the
   Function URL restriction is separate from the now-resolved CloudFront
   one.
2. Once AWS lifts the Function-URL restriction: no code changes needed,
   the dashboard is already built, synced, and CORS-correct -- it'll work
   as soon as anonymous Function URL invocation is unblocked.
3. Provision the first admin Cognito user (commands in `CLAUDE.md`'s MFA
   section) and walk through the login flow (new password -> TOTP QR
   setup -> confirm code) manually in a browser once the Function URL
   restriction clears -- this has never been tested against a real,
   reachable frontend yet, only locally/via unit tests.
4. Optional cleanup: apply the deploy-user policy change above from your own
   terminal if you want `finance-distress-deploy` to be able to check
   Support case status too (not required for anything currently blocked).

## TODO -- 2026-10-22

Full project scan while still blocked on the Function URL restriction.
Confirmed the weekly retrain schedule (`distress-model-weekly-retrain`) is
healthy -- 4 consecutive `SUCCEEDED` executions since the time-split eval
went live (2026-09-29, 10-06, 10-13, 10-20).

**IAM permission drift found on `finance-distress-deploy` (the human
terminal user) -- both repo files are now correct target state (updated
2026-10-22, commit `68964fa`); only the live `create-policy-version` apply
is still pending, and has to be run by the account owner (the EC2 instance
role is deliberately denied `iam:CreatePolicyVersion` on both, confirmed
via a live `AccessDenied` test -- this is the identity-separation boundary
in `CLAUDE.md`'s "IAM identities" section, not a bug to fix).**

| # | Policy ARN | File (now correct) | `Sid` section | Live status | What's missing live |
|---|---|---|---|---|---|
| 1 | `FinanceDistressDeployPolicy` | `aws/iam-deploy-policy-resources.json` | `CognitoUserPoolManagement` (own statement, line ~101) | `v17`, 2026-10-01, stale | Entire statement missing (predates MFA work, PR #27/#28) |
| 2a | `FinanceDistressDeployPolicy` | `aws/iam-deploy-policy-resources.json` | `CloudFrontDashboard` (own statement, line ~36) | same `v17` | Entire statement missing -- file-side gap fixed 2026-10-22, was absent from the repo file too, not just live |
| 2b | `FinanceDistressDeployPolicy` | `aws/iam-deploy-policy-resources.json` | `S3ModelAndDataBuckets` (existing statement, line ~5 -- actions folded into it, not a new statement) | same `v17` | `s3:GetBucketPolicy`/`PutBucketPolicy`/`DeleteBucketPolicy`/`GetBucketPublicAccessBlock`/`PutBucketPublicAccessBlock` added to the existing action list |
| 3 | `FinanceDistressDeployPolicyManagement` | `aws/iam-deploy-policy-management.json` | `SupportCaseReadOnly` (own statement, line ~176) | unknown (EC2 role can't read this policy by design) | Entire statement already in the file; per 2026-10-21 notes, not yet applied live |

Apply commands (run from your own terminal, not this instance):
```bash
aws iam create-policy-version --policy-arn arn:aws:iam::345736954421:policy/FinanceDistressDeployPolicy --policy-document file://aws/iam-deploy-policy-resources.json --set-as-default --region ap-south-1
aws iam create-policy-version --policy-arn arn:aws:iam::345736954421:policy/FinanceDistressDeployPolicyManagement --policy-document file://aws/iam-deploy-policy-management.json --set-as-default --region ap-south-1
```

None of these currently block anything in progress -- every real deploy so
far has gone through CI's GitHub OIDC role or the EC2 instance role, both
of which already have what they need. These only matter if the direct,
from-this-terminal deploy path in `CLAUDE.md` is actually used for
`auth-stack.json` or `dashboard-stack.json`.

Deliberately not automating the apply step itself for now -- doing so would
mean some CI-triggered identity could rewrite the human terminal user's own
permissions on a merge, which reopens the same escalation question the
three-identity split in `CLAUDE.md` exists to avoid. Revisit only with a
specific design for that boundary, not as a side effect of convenience.

**Remaining tasks that don't depend on AWS lifting the Function URL
restriction:**

- Submit the standalone ticket (`doc/aws-support-function-url-403.txt`) via
  the AWS Support Console -- the actual unblocking lever, has to be pasted
  in by hand.
- Apply the three IAM fixes above.
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
