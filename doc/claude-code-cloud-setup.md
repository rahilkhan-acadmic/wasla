# Connecting a claude.ai/code cloud session to this AWS account

So far this project has only been worked on from a Claude Code **terminal**
session on the `distress-model-claude-code` EC2 instance, which gets AWS
access for free via its instance role (`distress-model-claude-code-role`).

A claude.ai/code **cloud** session is a different thing: it runs in an
Anthropic-managed sandbox, not inside this AWS account or on this EC2
instance. There is no SSH/VPC path from that sandbox into this instance, and
it doesn't share this box's filesystem. The two sessions only share state
through this GitHub repo and through the AWS account itself — not through
disk. Push/pull between them accordingly; don't assume one can see the
other's local, uncommitted changes.

None of this project's AWS surface (Lambda, S3, DynamoDB, Step Functions,
CloudFormation, ECR) is VPC-internal, so a cloud session with the right IAM
credentials has everything it needs to deploy and inspect this project —
it just can't reach *this specific instance*.

## 1. Connect the GitHub repo

In the cloud session's settings, connect this repository so the session is
working on the same codebase.

## 2. Give it AWS credentials

Use the `finance-distress-deploy` IAM user (see `CLAUDE.md`, "IAM identities"
section) — the same identity meant for deploying from a terminal. Do **not**
use the EC2 instance role; it's intentionally scoped tighter (e.g. it can't
even list that user's access keys, let alone create one).

Create an access key for that user from somewhere with IAM admin rights —
this cannot be done from the EC2 instance's own session, by design:

```bash
aws iam list-access-keys --user-name finance-distress-deploy --region ap-south-1
# IAM caps a user at 2 keys — delete/deactivate an old one first if already at 2
aws iam create-access-key --user-name finance-distress-deploy --region ap-south-1
```

AWS shows the `SecretAccessKey` exactly once. Copy both values straight into
the cloud session's environment variables / secrets, and nowhere else:

```
AWS_ACCESS_KEY_ID=<AccessKeyId>
AWS_SECRET_ACCESS_KEY=<SecretAccessKey>
AWS_DEFAULT_REGION=ap-south-1
```

Never commit these to the repo.

## 3. Verify

```bash
aws sts get-caller-identity
```
Should return the `finance-distress-deploy` user's ARN in account
`345736954421`.

## 4. What the cloud session can and can't do

- **Can**: run the "Direct, from this instance" deploy path in `CLAUDE.md`
  (docker build/push to ECR, `aws cloudformation deploy`, `aws lambda
  invoke`), run the test suite, read/write DynamoDB and S3 directly for
  debugging.
- **Can't**: `ssm:StartSession` onto the EC2 box, or anything scoped to the
  instance role specifically.
- **Still required**: the full test suite in `CLAUDE.md` ("Before any
  deploy") before any deploy from either session — the cloud sandbox isn't
  exempt just because it isn't this EC2 instance.

## Rotation

Access keys are long-lived credentials. Rotate periodically and delete the
old key once the cloud session is confirmed working on the new one:
```bash
aws iam delete-access-key --user-name finance-distress-deploy --access-key-id <old-id> --region ap-south-1
```
