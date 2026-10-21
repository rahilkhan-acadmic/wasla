# Progress status -- saved 2026-10-17, updated 2026-10-21

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

## Cost reminder

Per `CLAUDE.md`: stop this EC2 instance when not actively in use.
```bash
aws ec2 stop-instances --instance-ids <this-instance-id> --region ap-south-1
```
