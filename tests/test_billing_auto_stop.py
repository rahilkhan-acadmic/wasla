"""
Tests billing_auto_stop.py's core safety property: it must act ONLY on the
hard-line alarm's ALARM state, and must ignore everything else arriving on
the same SNS topic -- the early-warning alarm, the hard-line alarm's own
OK/recovery notification, and any other alarm name.

Run from the project root: python tests/test_billing_auto_stop.py
"""
import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

os.environ["TARGET_ALARM_NAME"] = "billing-hard-line-2500inr"
os.environ["INSTANCE_REGION"] = "ap-south-1"
os.environ["INSTANCE_NAME_TAG"] = "distress-model-claude-code"

from moto import mock_aws  # noqa: E402
import boto3  # noqa: E402


def _sns_event(alarm_name: str, state: str) -> dict:
    message = json.dumps({"AlarmName": alarm_name, "NewStateValue": state})
    return {"Records": [{"Sns": {"Message": message}}]}


@mock_aws
def run():
    ec2 = boto3.client("ec2", region_name="ap-south-1")
    ami = ec2.describe_images(Owners=["amazon"])["Images"][0]["ImageId"]
    instance = ec2.run_instances(
        ImageId=ami, MinCount=1, MaxCount=1, InstanceType="t3.large",
        TagSpecifications=[{"ResourceType": "instance",
                             "Tags": [{"Key": "Name", "Value": "distress-model-claude-code"}]}],
    )["Instances"][0]
    instance_id = instance["InstanceId"]

    import billing_auto_stop as bas

    print("=== Test 1: early-warning alarm (wrong name) -- must NOT stop the instance ===")
    bas.handler(_sns_event("billing-early-warning-1500inr", "ALARM"), None)
    state = ec2.describe_instances(InstanceIds=[instance_id])["Reservations"][0]["Instances"][0]["State"]["Name"]
    assert state == "running", f"Early-warning alarm must never stop the instance, but state is '{state}'"
    print(f"PASSED (instance still '{state}')\n")

    print("=== Test 2: hard-line alarm but OK state (recovery notice) -- must NOT stop ===")
    bas.handler(_sns_event("billing-hard-line-2500inr", "OK"), None)
    state = ec2.describe_instances(InstanceIds=[instance_id])["Reservations"][0]["Instances"][0]["State"]["Name"]
    assert state == "running", f"An OK-state notification must never stop the instance, but state is '{state}'"
    print(f"PASSED (instance still '{state}')\n")

    print("=== Test 3: hard-line alarm in ALARM state -- MUST stop the instance ===")
    result = bas.handler(_sns_event("billing-hard-line-2500inr", "ALARM"), None)
    state = ec2.describe_instances(InstanceIds=[instance_id])["Reservations"][0]["Instances"][0]["State"]["Name"]
    assert state == "stopped", f"The hard-line ALARM state must stop the instance, but state is '{state}'"
    assert result["results"][0]["action"] == "stopped"
    assert instance_id in result["results"][0]["instance_ids"]
    print(f"PASSED (instance now '{state}')\n")

    print("=== Test 4: no matching running instance -- must not crash, reports 'none' ===")
    result = bas.handler(_sns_event("billing-hard-line-2500inr", "ALARM"), None)
    assert result["results"][0]["action"] == "none"
    print("PASSED (no crash, correctly reported nothing to stop)\n")

    print("ALL TESTS PASSED")


if __name__ == "__main__":
    run()
