"""
Tests for GET /model/info in src/app.py, using moto to mock DynamoDB so the
real boto3 get_item path is exercised, not just the no-registry fallback.

Run from the project root: python tests/test_model_info_endpoint.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

os.environ["AWS_DEFAULT_REGION"] = "ap-south-1"

from moto import mock_aws
import boto3


def _client():
    import importlib
    import app as app_module
    importlib.reload(app_module)
    from fastapi.testclient import TestClient
    return TestClient(app_module.app)


def test_no_registry_configured():
    os.environ.pop("MODEL_REGISTRY_TABLE", None)
    client = _client()
    r = client.get("/model/info")
    assert r.status_code == 200, r.text
    assert r.json() == {
        "registry_configured": False,
        "version": None,
        "promoted_at": None,
        "s3_key": None,
    }
    print("PASSED: no registry configured")


@mock_aws
def _with_mock_table(table_name, fn):
    ddb = boto3.client("dynamodb", region_name="ap-south-1")
    ddb.create_table(
        TableName=table_name,
        AttributeDefinitions=[{"AttributeName": "model_name", "AttributeType": "S"}],
        KeySchema=[{"AttributeName": "model_name", "KeyType": "HASH"}],
        BillingMode="PAY_PER_REQUEST",
    )
    fn()


def test_registry_configured_with_item():
    table_name = "test-distress-model-registry-info"
    os.environ["MODEL_REGISTRY_TABLE"] = table_name
    os.environ["MODEL_REGISTRY_KEY"] = "distress-classifier"

    def run():
        boto3.resource("dynamodb", region_name="ap-south-1").Table(table_name).put_item(
            Item={
                "model_name": "distress-classifier",
                "s3_key": "models/distress-classifier/v7/model.json",
                "version": "v7",
                "promoted_at": "2026-09-08T12:00:00Z",
            }
        )
        client = _client()
        r = client.get("/model/info")
        assert r.status_code == 200, r.text
        assert r.json() == {
            "registry_configured": True,
            "version": "v7",
            "promoted_at": "2026-09-08T12:00:00Z",
            "s3_key": "models/distress-classifier/v7/model.json",
        }
        print("PASSED: registry configured with item")

    _with_mock_table(table_name, run)


def test_registry_configured_no_item():
    table_name = "test-distress-model-registry-empty"
    os.environ["MODEL_REGISTRY_TABLE"] = table_name
    os.environ["MODEL_REGISTRY_KEY"] = "distress-classifier"

    def run():
        client = _client()
        r = client.get("/model/info")
        assert r.status_code == 200, r.text
        assert r.json() == {
            "registry_configured": True,
            "version": None,
            "promoted_at": None,
            "s3_key": None,
        }
        print("PASSED: registry configured, no item present (not a 500)")

    _with_mock_table(table_name, run)


if __name__ == "__main__":
    test_no_registry_configured()
    test_registry_configured_with_item()
    test_registry_configured_no_item()
    print("\nAll /model/info tests passed.")
