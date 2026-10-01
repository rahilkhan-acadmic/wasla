"""
Stops the Claude Code EC2 instance automatically when the hard-line billing
alarm fires. Subscribed to the SAME SNS topic as the early-warning alarm
(billing-alerts), so it must check WHICH alarm actually triggered rather
than acting on every message -- otherwise it would also stop the instance
on the INR 1,500 early warning, which is meant to just be a heads-up email.

The Lambda itself runs in us-east-1 (where AWS::Billing alarms are required
to live), but makes its EC2 calls against ap-south-1 explicitly, since
that's where the actual instance runs -- a Lambda's own region and the
region its API calls target are independent.

Matches the instance by its Name tag rather than a hardcoded instance ID,
so this keeps working even if the EC2 stack is ever deleted and redeployed
with a new instance ID.
"""

import json
import os

import boto3

TARGET_ALARM_NAME = os.environ.get("TARGET_ALARM_NAME", "billing-hard-line-2500inr")
INSTANCE_REGION = os.environ.get("INSTANCE_REGION", "ap-south-1")
INSTANCE_NAME_TAG = os.environ.get("INSTANCE_NAME_TAG", "distress-model-claude-code")


def handler(event, context):
    results = []

    for record in event.get("Records", []):
        message = json.loads(record["Sns"]["Message"])
        alarm_name = message.get("AlarmName")
        new_state = message.get("NewStateValue")

        if alarm_name != TARGET_ALARM_NAME:
            print(f"Ignoring: alarm '{alarm_name}' is not the hard-line alarm "
                  f"('{TARGET_ALARM_NAME}') -- likely the early-warning alarm, no action taken.")
            continue
        if new_state != "ALARM":
            print(f"Ignoring: hard-line alarm state is '{new_state}', not 'ALARM' "
                  f"(e.g. this may be the OK/recovery notification).")
            continue

        ec2 = boto3.client("ec2", region_name=INSTANCE_REGION)
        resp = ec2.describe_instances(Filters=[
            {"Name": "tag:Name", "Values": [INSTANCE_NAME_TAG]},
            {"Name": "instance-state-name", "Values": ["running"]},
        ])
        instance_ids = [
            i["InstanceId"] for r in resp["Reservations"] for i in r["Instances"]
        ]

        if instance_ids:
            print(f"Hard-line billing alarm fired -- stopping instance(s): {instance_ids}")
            ec2.stop_instances(InstanceIds=instance_ids)
            results.append({"action": "stopped", "instance_ids": instance_ids})
        else:
            print(f"Hard-line billing alarm fired, but no running instance tagged "
                  f"'{INSTANCE_NAME_TAG}' was found -- nothing to stop.")
            results.append({"action": "none", "reason": "no matching running instance"})

    return {"results": results}
