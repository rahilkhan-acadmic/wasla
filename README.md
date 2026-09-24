# Financial Distress / Penny-Stock Risk Screener (Prototype)

A starter pipeline that combines **structured financial ratios** (Altman
Z-Score family) with **text sentiment** (news/filings) into a single
distress-probability model, trained with gradient boosting (XGBoost).

This is a **research/screening tool prototype**, not a trading system and not
investment advice. Read the "Important limitations" section before using it
on real decisions.

## Why this architecture

A pure LLM is the wrong core engine for numeric financial forecasting —
gradient-boosted trees and classical distress models (Altman Z-Score) handle
structured numeric ratios far better. The LLM/text-model's job here is
narrower and more valuable: extracting sentiment and risk signal from
unstructured text (filings, headlines, transcripts) that ratios alone miss.
That's the split this project follows.

## Project structure

```
src/
  altman_zscore.py     Z-Score and Z''-Score distress ratio calculators
  edgar_client.py       Pulls real financial statement data from SEC EDGAR (free, no key)
  sentiment.py          FinBERT (real) with automatic offline VADER fallback
  features.py           Combines ratios + sentiment into one feature vector
  train_classifier.py   Trains an XGBoost distress classifier
  predict.py            Runs the full pipeline for one company
data/
  generate_sample_data.py   Builds a SYNTHETIC demo dataset (120 fake companies)
  sample_companies.json     ^ output of the above, checked in for convenience
models/
  distress_model.json       Trained model (produced by train_classifier.py)
```

## Setup

```bash
pip install -r requirements.txt
```

For real FinBERT sentiment (recommended over the offline fallback), also install:
```bash
pip install transformers torch
```
Without these, `sentiment.py` automatically falls back to VADER (offline,
weaker on financial jargon, but requires no model download).

## Quickstart (fully offline, synthetic data)

```bash
cd src
python train_classifier.py                       # trains on data/sample_companies.json
python predict.py --demo-ticker SYN027            # run inference on one synthetic company
```

## Using real data (requires internet access to sec.gov)

```bash
cd src
python edgar_client.py AAPL                       # sanity check: pull real financials
python predict.py --ticker GME --model ../models/distress_model.json
```

`edgar_client.py` pulls real, free financial statement data for any US
public filer straight from SEC EDGAR's XBRL API — this is the best free
source of fundamentals for micro-caps and penny stocks, since most paid data
APIs have poor small-cap coverage.

**Note:** EDGAR doesn't include live share price, so `market_value_equity`
won't be populated automatically from `edgar_client.py` alone. Pull a price
with something like `yfinance` and pass it in, or the pipeline will fall back
to book value of equity for the Z-Score calculation.

## Using Indian markets (NSE/BSE)

SEC EDGAR only covers US filers, so `edgar_client.py` won't work for Indian
stocks. Use `src/nse_client.py` instead, which pulls data via yfinance for
any `.NS` (NSE) or `.BO` (BSE) ticker:

```bash
pip install yfinance
cd src
python nse_client.py RELIANCE.NS                  # sanity check
python predict.py --nse-ticker TCS.NS --model ../models/distress_model.json
```

A few India-specific notes:

- **The Z''-Score variant already in `altman_zscore.py` is actually the
  better fit for Indian companies** — Altman designed it specifically for
  non-US, non-manufacturing, and emerging-market firms, which describes most
  Indian small/mid-caps well. Prefer `z_double_prime` over `z_score` in your
  analysis here.
- **yfinance's financial-statement coverage is real-time market cap
  (an advantage over EDGAR) but thinner on small/micro-cap fundamentals** —
  expect missing fields for many penny stocks. For anything beyond
  prototyping, Screener.in's API has better-curated Indian fundamentals
  (paid tiers) and NSE/BSE data libraries like `nsepython` or `jugaad-data`
  are worth evaluating.
- **Failure labels for training:** India's equivalent of US
  bankruptcy/delisting data comes from the **IBBI** (Insolvency and
  Bankruptcy Board of India) corporate insolvency resolution process filings
  and NSE/BSE delisting circulars, rather than SEC EDGAR's bankruptcy filings.
- **Sentiment coverage:** FinBERT and VADER both work adequately on
  English-language Indian financial news, but neither has real training
  exposure to Hindi or other regional-language financial media, which is a
  meaningful source of retail-investor-moving news for smaller Indian
  companies. A multilingual or Indian-language-specific model would close
  that gap if it matters for your use case.

## Building a REAL training set (the actual hard part)

The synthetic data only proves the pipeline runs end-to-end — it is
intentionally separable and will make the model look far better than it will
ever be on real data. `data/build_dataset.py` and `data/sources/` build a
real one, selectable by market, or combined:

```bash
python data/build_dataset.py --market us            # SEC EDGAR only
python data/build_dataset.py --market india          # Curated India CSV only
python data/build_dataset.py --market us,india       # Combined, comma-separated
python data/build_dataset.py --market all            # Every registered market
```

### Adding a new market — this is a real plugin system, not just an if/elif

Every market lives in its own module in `data/sources/`, and needs to expose
exactly three things — demonstrated by all three bundled examples:

```python
MARKET_CODE = "xx"                # the --market value that selects it
def add_cli_args(parser): ...     # adds this market's own CLI args (API keys, date ranges, etc.)
def build(args) -> list[dict]:    # returns records in the shared schema
```

Then register it with one line in `data/build_dataset.py`'s `MARKET_REGISTRY`
dict. Nothing else in `build_dataset.py` — the CLI, merging, or summary
logic — needs to change. This was verified two ways: a full dry run using
fake builders in place of the real (network-dependent) ones proved the
registry → parse → build → merge → summarize → write pipeline works
end-to-end, and `--market us --help` vs `--market all --help` were checked
to confirm each market's CLI arguments are only registered when that market
is actually selected (so picking `--market us` never demands a UK API key).

**Three markets are bundled, at three different levels of completeness —
deliberately, since that's an honest reflection of real-world data
availability:**

- **`us_edgar_labels.py`** — the strongest of the three. SEC EDGAR's Form
  8-K **Item 1.03** is a structured, unambiguous "we filed for bankruptcy"
  disclosure. Healthy comparisons are sampled from ordinary EDGAR 10-K
  filers in the same window (not a hardcoded list), to avoid survivorship
  bias. `edgar_client.py`'s `as_of_date` cutoff (unit-tested in
  `tests/test_edgar_leakage_prevention.py`) prevents a company's
  post-failure filings from leaking into its own "distress" features.
- **`india_labels.py`** — a manually curated seed CSV of real,
  well-documented insolvencies (Jet Airways, DHFL, and others), since no
  free structured ticker-linked equivalent of EDGAR exists for India. Two
  real limitations documented in its module docstring: every seed example
  is a large, nationally-known case (this project's actual focus is penny
  stocks, a different scale entirely), and there's no `as_of_date` leakage
  protection yet.
- **`uk_companies_house_labels.py`** — a **deliberately partial** example,
  included specifically to show that not every market is equally easy to
  add. Companies House's `company_status` field (`liquidation`,
  `administration`, `receivership`, ...) is a genuinely clean, free, official
  label source — as good as EDGAR's Item 1.03. But unlike EDGAR, Companies
  House doesn't expose financial statement figures as structured API
  fields — they're embedded in filed iXBRL/PDF documents. This module
  fetches real labels correctly, but returns `None` for every financial
  field rather than faking numbers, so its records are correctly filtered
  out downstream until someone implements iXBRL parsing (a genuine,
  scoped-out piece of future work, not a bug).
- **`china_labels.py`** — arguably the **cleanest label mechanism of any
  market here**. Since 2001, Shanghai/Shenzhen exchanges (under CSRC rules)
  prefix a distressed company's own stock short name with "ST" or "*ST" —
  no search API needed at all, just the current A-share roster, filtered by
  name prefix. Uses **AKShare**, not `yfinance`, since Yahoo Finance's
  coverage of Chinese A-shares is known to be unreliable — AKShare is the
  standard free tool the Chinese quant research community actually uses.
  **Important caveat, unlike every other market module**: AKShare's
  function names and (Chinese-language) column names shift more often than
  SEC EDGAR's stable government API, and this module's field mappings were
  written in good faith but **could not be verified against a live akshare
  install** in the sandboxed environment it was built in — sanity-check
  `ak.stock_zh_a_spot_em()`'s actual columns before trusting this fully.

**US (`data/sources/us_edgar_labels.py`):** uses SEC EDGAR's full-text
search to find real Form 8-K **Item 1.03** filings — the specific,
structured disclosure item reserved for "Bankruptcy or Receivership". This
is a genuinely clean, unambiguous signal, not a heuristic. A healthy
comparison sample is drawn from ordinary 10-K filers in the same date range
(excluding anyone who filed Item 1.03), rather than a hardcoded list of
"well-known healthy companies" — the latter would just be a leaky proxy for
survivorship. Crucially, `edgar_client.py` now supports an `as_of_date`
cutoff (verified with `tests/test_edgar_leakage_prevention.py`, using a
synthetic fixture that proves it correctly excludes filings dated after a
company's failure) — without this, financials filed *after* a company went
bankrupt would silently leak into its own "distress" features.

**India (`data/sources/india_labels.py` + `india_distress_labels.csv`):**
there is no free, structured, ticker-linked equivalent of EDGAR for Indian
corporate failures — IBBI's public registry exists, but the overwhelming
majority of listed cases are private companies with no NSE/BSE ticker,
useless for a pipeline built on `yfinance`. The bundled CSV is a **manually
curated seed list** of real, well-documented, publicly-listed insolvencies
(Jet Airways, DHFL, Reliance Communications, Bhushan Steel, and others) —
not a comprehensive or automatically-sourced dataset. **Read the
`india_labels.py` module docstring before trusting this beyond a demo** —
it documents two real, current limitations:
- Every seed example is a *large*, nationally-known case, while this
  project's actual focus is penny stocks — a model trained on
  mega-cap-scale failures won't transfer to small-cap distress signatures.
  Expand the CSV with real small/mid-cap examples (screener.in,
  moneycontrol.com, NSE/BSE delisting circulars) before relying on this.
- Unlike the US path, there's no `as_of_date` leakage protection for India
  yet — `yfinance` doesn't expose the kind of dated historical filings
  EDGAR does. This is a real, currently-unsolved gap.

**Every market plugin writes to the same schema** as `data/sample_companies.json`
(plus `market`, `region`, `company_name`, `event_date`, `source` for
provenance), so
the output is a drop-in replacement everywhere the synthetic file is
currently used. Verified compatible end-to-end against
`tests/fixture_real_schema_companies.json` (a small hand-built fixture
mixing US and India records) — `train_classifier.py` trains on it without
any changes needed to the training code itself.

```bash
python src/train_classifier.py --data data/real_companies.json --out models/distress_model_real.json
```

Expect ROC-AUC well below the 1.0 you saw on synthetic data — anything
meaningfully above 0.65–0.75 on a real, properly time-split test set would
be a solid result for this problem.

**These scripts need real internet access to `efts.sec.gov` / `data.sec.gov`
and Yahoo Finance's endpoints — they were built and unit-tested for their
internal logic (see `tests/`), but the live network calls themselves could
not be exercised in the sandboxed environment they were written in. Run
them on your own machine, and expect to iterate on rate limits, occasional
missing data for individual filers, and EDGAR's full-text search index only
covering filings from 2001 onward.**

## Important limitations (read before relying on this for anything real)

- **Penny stocks are unusually hard to model.** Thin trading and frequent
  pump-and-dump manipulation mean a lot of "signal" in penny-stock price
  action isn't fundamentals-driven — the model risks learning to detect
  manipulation patterns rather than genuine distress or growth signals.
- **Markets are largely efficient.** Professional quant funds with vastly
  more data/compute still struggle to beat the market consistently. Treat
  this as a research-triage tool that flags candidates for human review, not
  an autonomous predictor.
- **This is not investment advice, and I'm not a financial or legal advisor.**
  If you ever move from personal research to distributing predictions to
  others (especially for pay), that can trigger RIA (Registered Investment
  Adviser) registration requirements under SEC/FINRA rules — worth a real
  compliance consult before going that direction.

## Suggested next upgrades

- Swap XGBoost for a model that also ingests time-series price/volume data
  (e.g. an LSTM or temporal transformer) alongside the fundamentals.
- Add insider trading data (Form 4 filings, also free on EDGAR) as a feature.
- Look at **FinGPT** (github.com/AI4Finance-Foundation/FinGPT) — an
  open-source, actively maintained financial LLM framework built on Llama-2
  — for a more capable text-understanding layer than FinBERT alone.

## Deploying on AWS

`src/app.py` is a FastAPI service exposing `/predict` and `/predict/demo/{ticker}`.
Two deployment paths are provided:

**Lambda (recommended for this project's traffic pattern)** — a screening
tool gets bursty, not constant, traffic, so a serverless API that scales to
zero is the cheapest fit:
```bash
docker build -f Dockerfile.lambda -t distress-model-api .
# push to ECR, then create a Lambda function (container image type) from it,
# handler = app.handler, and put API Gateway or a Function URL in front of it
```

**Standard container (ECS / App Runner / any VM)** — if you want a normal
always-on server instead:
```bash
docker build -t distress-model-api .
docker run -p 8000:8000 distress-model-api
```

**Recommended AWS architecture for full automation** (see the two deployment
diagrams from the conversation for the visual version):

| Stage | Service |
|---|---|
| Scheduled data ingestion | Lambda + EventBridge Scheduler |
| Feature store | S3 (Parquet) + Glue Data Catalog |
| Training | AWS Batch on Fargate, orchestrated by Step Functions |
| Model registry | S3 (versioned) + DynamoDB for metadata |
| Inference API | Lambda (container image) + API Gateway |
| Dashboard | CloudFront + S3 |
| Alerting | SNS → Slack/email |
| Monitoring & retrain trigger | CloudWatch alarms → EventBridge → Step Functions |

**Important for production:** both Dockerfiles currently `COPY` the model
into the image at build time. That means shipping a new model version
requires rebuilding and redeploying the container — fine for a prototype,
but you'll want the Lambda/container to instead pull the latest model from
S3 at cold-start (check a DynamoDB "current version" pointer, download that
model file to `/tmp`, then load it) so retraining doesn't require a code
deployment. That's a natural next piece to add once the base deployment is
working.

## Automated retraining: S3/DynamoDB model registry + Step Functions

`src/model_loader.py` solves the "rebuild the container to ship a new model"
problem above. It's already wired into `app.py`:

- If `MODEL_REGISTRY_TABLE` and `MODEL_BUCKET` env vars are set, the API
  checks DynamoDB for the current promoted model version on each cold start
  (cached per warm process) and downloads it from S3 if it's new.
- If those env vars are unset (e.g. local dev), it transparently falls back
  to the local `models/distress_model.json` file — no behavior change for
  local testing.

**Architecture note:** this was originally scoped with AWS Batch for the
training step. In practice, `train_classifier.py` runs in seconds on a small
dataset — Batch's compute-environment/VPC provisioning is real overhead for
a workload this size. The retrain pipeline runs entirely on **Lambda**
instead, reusing the exact same container image as the inference API
(`distress-model-api`) with a different handler — no second image to build
or maintain.

**`src/retrain_handler.py`** has two functions, deployed as two Lambda
functions from that shared image:
- `train_and_evaluate_handler` — loads the dataset (see below), retrains,
  evaluates the new candidate against the *currently deployed* model on the
  same data for a fair comparison, and writes the candidate to a non-live
  S3 key
- `register_model_handler` — only called if the candidate actually improved:
  promotes it to a versioned key and updates the DynamoDB pointer

Both were verified with `tests/test_retrain_handler.py`, which uses `moto`
to mock S3/DynamoDB and exercises the real boto3 calls end-to-end — training
a model, evaluating against nothing (first run), registering it, then
confirming a second evaluation correctly finds and scores the newly
registered model.

### The retrain loop now runs on real data automatically, not synthetic data

**`src/fetch_data_handler.py`** is a third Lambda, sharing the same image,
that runs `data/build_dataset.py`'s logic *inside AWS* and writes the result
to S3 (`datasets/real_companies.json` by default) — this is what actually
closes the "still trains on synthetic data" gap and removes the need to run
anything from your own laptop. It's scoped to the **US market only** by
default (`FETCH_MARKETS=us` env var) since that's the most robust,
best-tested path with real leakage protection and no API key required —
widen this later via the same env var once you've verified India/UK/China
work the way you want (UK needs `COMPANIES_HOUSE_API_KEY` set as a Lambda
env var or, better, a Secrets Manager secret; China's AKShare calls to
Chinese data providers from AWS Lambda's network haven't been tested).

One genuine advantage of this running in AWS rather than on a laptop: Lambda's
outbound internet access doesn't route through a corporate proxy, so the
SSL/CA-bundle workaround this project needed locally simply doesn't apply here.

The Step Functions flow is now **FetchData → TrainAndEvaluate → ShouldPromote
→ RegisterModel/NotifyRejected** — verified end-to-end with `moto`: a fake
market builder standing in for the real (rate-limited, slow) SEC EDGAR calls
confirmed the handler correctly dispatches through the plugin registry,
filters out any incomplete records, and writes real, readable-back content
to S3.

`src/retrain_handler.py`'s `_load_dataset_arrays()` now prefers whatever
`fetch_data_handler.py` most recently wrote to S3 (`DATASET_S3_KEY`),
falling back to a local file if that's missing or the download fails —
tested explicitly for both cases (prefers S3 when present; falls back
cleanly to the bundled synthetic dataset when it's not).

**`aws/state_machine.asl.json`** documents the flow standalone for
reference; **`aws/automation-stack.json`** is what you actually deploy — a
CloudFormation template defining all three Lambda functions, their shared
execution role, the Step Functions state machine (with the same definition
embedded), an SNS topic, and a weekly EventBridge schedule, all in one
deploy:

```bash
aws cloudformation deploy --template-file aws/automation-stack.json --stack-name distress-model-automation --profile finance-distress --region ap-south-1 --capabilities CAPABILITY_NAMED_IAM --parameter-overrides ImageUri=<account-id>.dkr.ecr.ap-south-1.amazonaws.com/distress-model-api:latest
```

Deploy this *after* `distress-model-lambda` exists, since it reuses that
same ECR image — **but this update genuinely does need a fresh image push**
first, since `fetch_data_handler.py` is a new file. Same lesson as before:
rebuild with `--platform linux/amd64 --provenance=false`, push under a new
tag, and pass that tag as `ImageUri` here.

**The evaluation gate matters** — it doesn't blindly deploy every retrain,
only ones that improve AUC by more than 0.01 over the currently deployed
model (tune `PROMOTION_AUC_MARGIN` once real data makes AUC deltas
meaningful), and always notifies via the SNS topic either way.

**For the drift-triggered path** (off-cycle retrain when CloudWatch detects
drift, rather than waiting for the weekly schedule), `aws/cloudwatch_drift_alarm.json`
+ `aws/eventbridge_drift_pattern.json` + `aws/eventbridge_drift_targets.json`
are still there from the original design — update their `<placeholder>` ARNs
to point at the state machine this stack outputs, then apply them the same
way as before:
```bash
aws cloudformation describe-stacks --stack-name distress-model-automation --profile finance-distress --region ap-south-1 --query "Stacks[0].Outputs" --output table
aws cloudwatch put-metric-alarm --cli-input-json file://aws/cloudwatch_drift_alarm.json --profile finance-distress
aws events put-rule --name distress-model-drift-triggered-retrain --event-pattern file://aws/eventbridge_drift_pattern.json --profile finance-distress
aws events put-targets --rule distress-model-drift-triggered-retrain --targets file://aws/eventbridge_drift_targets.json --profile finance-distress
```


## MCP server: talking to this model directly from Claude

`src/mcp_server.py` exposes the model as an MCP (Model Context Protocol)
server, so Claude Desktop, Claude Code, or any other MCP-compatible client
can call it directly in conversation — "what's the distress score for
RELIANCE.NS?" — without a dashboard or custom API integration code.

Four tools are exposed: `score_company` (custom financials), `score_demo_ticker`
(bundled synthetic data), `fetch_us_financials` (SEC EDGAR), and
`fetch_india_financials` (yfinance). All four were tested directly against
the trained model and confirmed working.

Run it locally and point Claude Desktop at it:
```json
{
  "mcpServers": {
    "distress-model": {
      "command": "python",
      "args": ["/absolute/path/to/src/mcp_server.py"]
    }
  }
}
```

This uses MCP Python SDK v2 (`from mcp.server.mcpserver import MCPServer`).
If you have v1 installed instead, swap that import for
`from mcp.server.fastmcp import FastMCP as MCPServer` — the rest of the code
is unchanged.

**Is this worth adding, and does it duplicate the FastAPI service?** They
serve different purposes, not redundant ones:
- `app.py` (FastAPI) is for **programmatic/automated** access — your
  dashboard, scheduled batch scoring, other services calling it over HTTP.
- `mcp_server.py` is for **conversational/ad-hoc** access — an analyst
  asking Claude about a ticker mid-conversation, without opening a
  dashboard or writing a curl command. It's genuinely a different usage
  pattern (exploration and one-off questions) than the AWS-deployed service
  (automated, scheduled, always-on).

You can run both, and both can even share the exact same model file — the
MCP server doesn't need its own copy of the model or its own deployment
lifecycle if you point it at the same model path (or extend it to use
`model_loader.py` too, for consistency with the S3 registry).

## Deploying the MCP server on AWS

`mcp_server.py` now exposes `http_app` — a real Starlette ASGI app from
`mcp.streamable_http_app(stateless_http=True)` — and `handler`, a
Mangum-wrapped Lambda handler built from it. This was tested end-to-end: a
real MCP client (not just curl) connected over HTTP, ran the full
initialize → list tools → call tool handshake, and got a correct result
back from the trained model.

Because it's the same ASGI-app-behind-Mangum pattern as `app.py`, it deploys
identically:

**Lambda (recommended, same reasoning as the FastAPI service):**
```bash
docker build -f Dockerfile.lambda-mcp -t distress-model-mcp .
# push to ECR, create a Lambda function (container image) from it,
# handler = mcp_server.handler, put a Function URL or API Gateway in front
```

**Standard container (ECS / App Runner):**
```bash
uvicorn mcp_server:http_app --host 0.0.0.0 --port 8765
```

### Securing a remote MCP server (don't skip this)

Local stdio MCP servers are inherently private — only your own machine can
launch them. The moment you deploy over Streamable HTTP, the server is
internet-reachable, and unlike the FastAPI service (which is arguably fine
as a semi-open screening tool), an MCP server also exposes `fetch_us_financials`
and `fetch_india_financials`, which make outbound calls on your behalf — you
don't want those open to anyone who finds the URL. Pick one:

- **Lambda Function URL with `AUTH_TYPE=AWS_IAM`** — simplest if the only
  clients are your own AWS-authenticated tools/scripts.
- **API Gateway + API key or a Lambda authorizer** — simplest if you want a
  shareable-but-controlled secret for a small team.
- **OAuth 2.1** — the MCP spec's native auth mechanism, worth using if
  you're exposing this to Claude.ai's remote connector feature for multiple
  people rather than a single Claude Desktop config. More setup than the
  two options above; only worth it once you have real multi-user demand.

For a single person connecting from Claude Desktop or Claude Code, an API
Gateway API key is a reasonable, low-effort starting point.

## AWS account and IAM setup (do this first)

Before deploying any of the above, you need an AWS account and a properly
scoped IAM identity to deploy from — not your root account, and not a
blanket `AdministratorAccess` grant.

**`aws/iam-deploy-policy.json`** is a ready-to-use, scoped-down policy
covering exactly the services this project touches (S3, DynamoDB, Lambda,
ECR, Step Functions, EventBridge/Scheduler, Batch, CloudWatch, SNS, and the
`iam:PassRole` permission needed to hand roles to Lambda/Batch/Step
Functions at deploy time) — not a general-purpose grant.

Quick setup:
1. Enable MFA on your AWS root account, then stop using it day-to-day.
2. Create an IAM user for yourself (e.g. `yourname-deploy`) with
   programmatic access.
3. Create a policy from `aws/iam-deploy-policy.json` (replace the
   `<account-id>` placeholder with your AWS account ID, and `<region>` with
   the region you'll actually deploy resources in — `ap-south-1` (Mumbai) if
   you're India-based, since every service this project uses is available
   there and it's lower-latency for India-based access than a US region)
   and attach it to that user.
4. Install the AWS CLI, then run:
   ```bash
   aws configure --profile finance-distress
   aws sts get-caller-identity --profile finance-distress   # sanity check
   ```
5. Use `--profile finance-distress` on every AWS CLI command in this README
   from here on.

**Note the distinction:** this IAM user is *you*, deploying from your
machine. It's separate from the service roles (Lambda execution role, Batch
job role, Step Functions execution role) that you'll create individually as
you deploy each piece — those are what the *services* assume at runtime to
talk to each other, not what you use from the CLI.

## Infrastructure as Code: provisioning S3 + DynamoDB with CloudFormation

`aws/infrastructure.json` is a CloudFormation template defining the model
registry's S3 bucket and DynamoDB table declaratively — no more manually
running `create-bucket`/`create-table` commands and hoping you remember the
exact configuration (versioning enabled, on-demand billing, etc.) next time.

```bash
# Provision (or re-provision) both resources in one command:
aws cloudformation deploy --template-file aws/infrastructure.json --stack-name distress-model-stack --profile finance-distress --region ap-south-1

# Tear both down in one command (empty the bucket first -- see below):
aws s3 rm s3://distress-model-<account-id> --recursive --profile finance-distress
aws cloudformation delete-stack --stack-name distress-model-stack --profile finance-distress --region ap-south-1
```

Note that the template only creates the empty bucket and table structures —
it doesn't know about your actual trained model file or the registry
pointer item, since those are data, not infrastructure. After deploying (or
re-deploying) the stack, re-run the upload and `put-item` commands from the
earlier setup steps to repopulate them:

```bash
aws s3 cp models/distress_model.json s3://distress-model-<account-id>/models/distress-classifier/v1/model.json --profile finance-distress
aws dynamodb put-item --table-name distress-model-registry --item file://aws/initial_registry_item.json --region ap-south-1 --profile finance-distress
```

**Worth extending this template later** rather than managing it separately:
the Lambda function, its execution role, and the ECR repository from the
deployment section above are also good candidates to fold into this same
CloudFormation template once that path is proven out — at that point,
`cloudformation deploy` becomes the single command that provisions the
entire project's AWS footprint, not just the registry.

## CI/CD: GitHub Actions, with no stored AWS access keys

`.github/workflows/ci.yml` and `.github/workflows/deploy.yml` automate
everything from "push code" to "it's live," eliminating most of the manual
terminal work this project was built with:

- **`ci.yml`** — runs on every push and pull request, from any branch or
  fork. Compiles all Python modules, runs the full test suite (`moto`-mocked
  retrain handler tests, EDGAR leakage-prevention tests), validates every
  CloudFormation template with `cfn-lint`, and smoke-tests the FastAPI app.
  Deliberately needs **no AWS credentials at all** — everything runs against
  local fixtures and mocks, which is what makes it safe to run on PRs from
  forks.
- **`deploy.yml`** — runs only on pushes to `main` (or a manual trigger from
  the Actions tab). Builds the Lambda-compatible Docker image (with the
  `--platform linux/amd64 --provenance=false` flags this project needed the
  hard way), pushes it to ECR tagged with the commit SHA (always traceable
  back to exactly what code produced it), and deploys the inference and
  automation CloudFormation stacks with that new image.

**Authentication uses OIDC federation, not stored AWS access keys.**
`aws/github-oidc-stack.json` sets up a trust relationship where GitHub
itself proves to AWS "this workflow run genuinely came from your repo's
`main` branch," and AWS hands out temporary credentials in response — no
long-lived secret ever sits in GitHub, which is the safer pattern AWS
itself recommends over storing access keys. The trust policy is scoped
specifically to the branch you specify (not `*`, which would let any
branch or PR assume deploy permissions) — `cfn-lint` caught this exact
looseness during development, when a parameter meant to enforce it turned
out to be declared but never actually used.

```bash
aws cloudformation deploy --template-file aws/github-oidc-stack.json --stack-name distress-model-github-oidc --profile finance-distress --region ap-south-1 --capabilities CAPABILITY_NAMED_IAM --parameter-overrides GitHubOrgRepo=<your-username>/<your-repo> GitHubBranch=main
```

The only thing you configure on GitHub's side is one repository secret,
`AWS_DEPLOY_ROLE_ARN` (the role this template outputs) — notably, not an
access key or secret key.

**Natural next layer, once this baseline is proven reliable**: adding
Anthropic's official `claude-code-action` to automatically investigate and
propose fixes when CI fails, rather than a human reading the failure and
diagnosing it — the same debugging pattern this project's development relied
on throughout, just running unattended.
