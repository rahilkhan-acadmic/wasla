# Progress status -- saved 2026-10-17, reconfirmed 2026-10-21

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
- A `deploy.yml` run was still `in_progress` as of this save
  (triggered by PR #28's merge, run 39013940774) -- expect it to pass the
  Cognito/Lambda steps cleanly (idempotent, no changes) and fail again at
  "Deploy dashboard hosting stack", same as every prior attempt. If so, just
  delete the resulting `ROLLBACK_COMPLETE` `distress-model-dashboard` stack
  (`aws cloudformation delete-stack --stack-name distress-model-dashboard
  --region ap-south-1`) so it's clean for the next retry -- this is routine
  at this point, not a new problem.

## What's still blocked

- **AWS account verification (CloudFront + public Lambda Function URLs)
  is still unresolved.** Re-confirmed multiple times on 2026-10-17, and
  again live on 2026-10-21 (deleted the `ROLLBACK_COMPLETE` stack and
  retried `distress-model-dashboard` once more) -- identical error every
  time: `"Your account must be verified before you can add new CloudFront
  resources."` This blocks the dashboard going live end-to-end; it's
  unrelated to the MFA work and pre-existing.
- A status-check follow-up for the open AWS Support case is drafted in
  `aws-support-followup.txt` (`doc/`, committed) but **not yet sent** --
  needs to be posted via the AWS Console (Support Center), since the
  Support API itself requires a Business/Enterprise support plan this
  account doesn't have (`SubscriptionRequiredException` confirmed when
  tried via CLI).
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

1. Post the follow-up in `aws-support-followup.txt` to the open AWS Support
   case via the Console.
2. Once AWS lifts the CloudFront/Function-URL restriction: no code changes
   needed, `deploy.yml` will deploy the dashboard automatically on the next
   push to `main` (or trigger it manually via `gh workflow run deploy.yml`).
3. After the dashboard is reachable: provision the first admin Cognito user
   (commands in `CLAUDE.md`'s MFA section) and walk through the login flow
   (new password -> TOTP QR setup -> confirm code) manually in a browser --
   this has never been tested against a real, reachable frontend yet, only
   locally/via unit tests.
4. Optional cleanup: apply the deploy-user policy change above from your own
   terminal if you want `finance-distress-deploy` to be able to check
   Support case status too (not required for anything currently blocked).

## Cost reminder

Per `CLAUDE.md`: stop this EC2 instance when not actively in use.
```bash
aws ec2 stop-instances --instance-ids <this-instance-id> --region ap-south-1
```
