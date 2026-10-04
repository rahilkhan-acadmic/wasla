# Working on this project

This is a financial distress screening model: real SEC EDGAR and NSE data,
an XGBoost classifier, served on AWS Lambda, with an automated weekly
retrain pipeline. Full context is in `README.md` — read it before making
architectural changes, especially the sections on the market plugin system,
the S3/DynamoDB model registry, and the evaluation methodology.

## Before any deploy: run the test suite

Never build or deploy without running these first, in order. All should
pass before anything ships, whether that's a direct deploy from this
instance or a PR into `main`:

```bash
python -m py_compile src/*.py data/*.py data/sources/*.py tests/*.py
python tests/test_retrain_handler.py
python tests/test_edgar_leakage_prevention.py
python tests/test_prediction_stability.py
python tests/test_env_args_contract.py
python tests/test_fetch_data_handler.py
python tests/test_no_label_derived_headlines.py
python tests/test_cross_validate.py
cfn-lint aws/*-stack.json aws/infrastructure.json
```

These exist because every one of them was written after something broke
silently: leaked labels through a `headlines` feature, a promotion gate
comparing models on different data, a Lambda crashing on an
`AttributeError` no local test caught, a false "no records" flag from a
market-code casing mismatch. Skipping this list reopens a specific, already-
identified bug.

If you change `requirements.txt` (especially `xgboost`, `scikit-learn`,
`numpy`, `pandas`), the stability test may fail — see its own docstring and
`tests/generate_prediction_snapshot.py` for what to do, which is NOT to
regenerate the snapshot reflexively without understanding why it changed.

## Two deploy paths — pick deliberately, don't default to the fast one

**Direct, from this instance** (Docker is installed for this):
```bash
docker build --platform linux/amd64 --provenance=false -f Dockerfile.lambda -t distress-model-api .
docker tag distress-model-api:latest <account-id>.dkr.ecr.ap-south-1.amazonaws.com/distress-model-api:<tag>
docker push <account-id>.dkr.ecr.ap-south-1.amazonaws.com/distress-model-api:<tag>
aws cloudformation deploy --template-file aws/lambda-stack.json --stack-name distress-model-lambda --region ap-south-1 --capabilities CAPABILITY_NAMED_IAM --parameter-overrides ImageUri=<account-id>.dkr.ecr.ap-south-1.amazonaws.com/distress-model-api:<tag>
```
Fast. Bypasses CI entirely — the test suite above is the ONLY safety net on
this path, since nothing else will check the code. Use for urgent fixes and
local iteration, always after running every test above, never before.

**Via GitHub** (the default for anything that isn't urgent):
```bash
git checkout develop
git add -A && git commit -m "..." && git push
# open a PR into main once CI is green; merge triggers deploy.yml automatically
```
Slower, but CI re-runs the full suite independently of whatever ran (or
didn't run) locally, and a PR is a deliberate checkpoint before anything
reaches production. Prefer this path by default.

## After any deploy, direct or via CI

Verify against the real endpoint, not just "the deploy command succeeded":
```bash
aws lambda invoke --function-name distress-model-api --region ap-south-1 --cli-binary-format raw-in-base64-out --payload file://aws/test_invoke_predict_payload.json response.json && cat response.json
```

## Key resource names (ap-south-1)

- Lambda functions: `distress-model-api`, `distress-model-train-evaluate`,
  `distress-model-register`, `distress-model-fetch-data`
- Step Functions: `distress-model-retrain`
- CloudFormation stacks: `distress-model-stack`, `distress-model-ecr`,
  `distress-model-lambda`, `distress-model-automation`,
  `distress-model-github-oidc`, `distress-model-claude-code`
- S3 bucket: `distress-model-<account-id>`
- DynamoDB table: `distress-model-registry`
- ECR repository: `distress-model-api`

## IAM identities — three separate things, don't confuse them

1. **`finance-distress-deploy`** (IAM user) — you, deploying from a terminal.
   Permissions split across two policies (`FinanceDistressDeployPolicy` +
   `FinanceDistressDeployPolicyManagement`, see `aws/iam-deploy-policy-*.json`)
   because a single managed policy caps at 6,144 non-whitespace characters.
   It also grants `ssm:StartSession`, scoped to instances tagged
   `Name=distress-model-claude-code` only, so this user can open a shell on
   the Claude Code box from a terminal (needs the Session Manager plugin
   installed locally) without being able to open one on anything else.
2. **`distress-model-claude-code-role`** (EC2 instance role, in
   `aws/claude-code-ec2-stack.json`) — what Claude Code can do *after* the
   EC2 instance exists. Trusted by `ec2.amazonaws.com`.
3. **`distress-model-cfn-gitsync-role`** (IAM role, created manually,
   definitions in `aws/claude-code-ec2-gitsync-service-role-trust.json` +
   `-policy.json`) — what CloudFormation itself can do when Git sync
   auto-deploys on a push to `aws/claude-code-ec2-deployment.yaml` or
   `aws/claude-code-ec2-stack.json`, with no human credentials available at
   that moment. Trusted by `cloudformation.amazonaws.com` specifically —
   this is why it couldn't reuse either of the roles above. Its inline
   policy, `distress-model-cfn-gitsync-policy`, reuses the exact same
   EC2/instance-profile/SSM-parameter/role-management statements already
   proven working in `FinanceDistressDeployPolicyManagement`, just under a
   different trust relationship.

## Known, open limitations — don't "fix" these without flagging it first

- **Evaluation is retrospective, not predictive.** The model separates
  already-failed companies from healthy ones; it has not been tested on
  forecasting a future failure. A time-based train/test split (train on
  older filings, test on newer ones) is the next real step here, not yet
  built.
- **`news_sentiment` is a constant 0.0 for every record**, deliberately.
  Every market plugin used to write label-derived headline text into this
  feature (a real leak, see `tests/test_no_label_derived_headlines.py`).
  Restoring it properly needs genuine, point-in-time, label-independent
  news per company, which does not exist yet.
- **India's healthy-company list is thin** (5 mega-caps in
  `data/sources/india_distress_labels.csv`). The India dataset is currently
  "15 small distressed companies vs. 5 giant healthy ones" — a real scale
  mismatch, not just a small-sample problem.
- **The promotion gate's held-out split is small** (~14 records at current
  dataset size). Treat any single retrain's `auc_improvement` with real
  skepticism; see `src/cross_validate.py` for a more trustworthy check
  before concluding a model is actually better.
- **NSE and Companies House are undocumented APIs.** If
  `data/sources/nse_gsm_labels.py` or `uk_companies_house_labels.py` starts
  failing, that's the likely cause, not a bug in this codebase — check their
  module docstrings.

## Cost note

The EC2 instance this file lives on costs money by the hour while running,
unlike the rest of this project (Lambda/Step Functions/DynamoDB on-demand
cost nothing when idle). Stop it when not actively in use:
```bash
aws ec2 stop-instances --instance-ids <this-instance-id> --region ap-south-1
```

Budget target: **under INR 2,500/month total**. At `t3.large` on-demand
pricing in `ap-south-1` (~$0.09/hour) plus the 40GB EBS volume, that limit
works out to roughly 7.5 hours/day of the instance actually running — stay
well under that with the stop habit above, not right at the edge of it.

### Billing alarms (both required, both in us-east-1 -- not ap-south-1)

AWS billing metrics only exist in `us-east-1`, regardless of which region
your resources run in. Two alarms exist, both on the `billing-alerts` SNS
topic:

- **Early warning at $15 (~INR 1,500)**: `billing-early-warning-1500inr` — email only.
- **Hard line at $25 (~INR 2,500)**: `billing-hard-line-2500inr` — email, AND
  triggers `aws/billing-auto-stop-stack.json`'s Lambda, which automatically
  runs `ec2:StopInstances` on whatever's tagged `Name=distress-model-claude-code`.

**Prerequisite, one-time, can't be scripted:** Billing and Cost Management →
Billing preferences → "Receive Billing Alerts" must be checked in the
console, or the underlying metric never gets published and both alarms sit
in `INSUFFICIENT_DATA` forever, silently.

If these ever need recreating (e.g. after deleting and redeploying from
scratch):
```bash
aws sns create-topic --name billing-alerts --region us-east-1
aws sns subscribe --topic-arn <TopicArn> --protocol email --notification-endpoint <your-email> --region us-east-1

aws cloudwatch put-metric-alarm --alarm-name "billing-early-warning-1500inr" --namespace "AWS/Billing" --metric-name EstimatedCharges --dimensions Name=Currency,Value=USD --statistic Maximum --period 21600 --evaluation-periods 1 --threshold 15 --comparison-operator GreaterThanThreshold --alarm-actions <TopicArn> --region us-east-1

aws cloudwatch put-metric-alarm --alarm-name "billing-hard-line-2500inr" --namespace "AWS/Billing" --metric-name EstimatedCharges --dimensions Name=Currency,Value=USD --statistic Maximum --period 21600 --evaluation-periods 1 --threshold 25 --comparison-operator GreaterThanThreshold --alarm-actions <TopicArn> --region us-east-1

aws cloudformation deploy --template-file aws/billing-auto-stop-stack.json --stack-name distress-model-billing-auto-stop --region us-east-1 --capabilities CAPABILITY_NAMED_IAM --parameter-overrides BillingTopicArn=<TopicArn>
```

Two honest limits: billing metrics update a few times a day, not in real
time, so there's lag between actual spend and the alert. And the auto-stop
only stops the EC2 instance — it does not touch Lambda, Step Functions, or
anything else in the project, since those are pay-per-use and don't
meaningfully drive cost the way idle EC2 hours do.
