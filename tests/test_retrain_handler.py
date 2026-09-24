"""
Integration test for retrain_handler.py using moto to mock S3 + DynamoDB --
so this actually exercises the real boto3 calls (upload, copy, get_item,
put_item) against a fake-but-real-behaving AWS backend, not just checking
that the code parses.

Run from the project root: python tests/test_retrain_handler.py
"""
import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

os.environ["MODEL_BUCKET"] = "test-distress-model-bucket"
os.environ["MODEL_REGISTRY_TABLE"] = "test-distress-model-registry"
os.environ["MODEL_REGISTRY_KEY"] = "distress-classifier"
os.environ["AWS_DEFAULT_REGION"] = "ap-south-1"

from moto import mock_aws
import boto3


@mock_aws
def run_test():
    s3 = boto3.client("s3", region_name="ap-south-1")
    s3.create_bucket(Bucket="test-distress-model-bucket",
                      CreateBucketConfiguration={"LocationConstraint": "ap-south-1"})

    ddb = boto3.client("dynamodb", region_name="ap-south-1")
    ddb.create_table(
        TableName="test-distress-model-registry",
        AttributeDefinitions=[{"AttributeName": "model_name", "AttributeType": "S"}],
        KeySchema=[{"AttributeName": "model_name", "KeyType": "HASH"}],
        BillingMode="PAY_PER_REQUEST",
    )

    import retrain_handler
    import importlib
    importlib.reload(retrain_handler)

    print("=== Test 1: train_and_evaluate_handler with NO existing model ===")
    result1 = retrain_handler.train_and_evaluate_handler({}, None)
    print(json.dumps(result1, indent=2))
    assert "candidate_s3_key" in result1
    assert result1["current_auc"] == 0.0
    assert result1["new_auc"] > 0.0
    print("PASSED\n")

    print("=== Test 2: register_model_handler promotes the candidate ===")
    result2 = retrain_handler.register_model_handler(result1, None)
    print(json.dumps(result2, indent=2))
    assert result2["version"].startswith("v")
    print("PASSED\n")

    print("=== Test 3: verify DynamoDB pointer was actually updated ===")
    item = boto3.resource("dynamodb", region_name="ap-south-1") \
        .Table("test-distress-model-registry") \
        .get_item(Key={"model_name": "distress-classifier"})["Item"]
    print(json.dumps(item, indent=2))
    assert item["s3_key"] == result2["s3_key"]
    print("PASSED\n")

    print("=== Test 4: train_and_evaluate_handler now finds the registered model ===")
    result4 = retrain_handler.train_and_evaluate_handler({}, None)
    print(json.dumps(result4, indent=2))
    assert result4["current_auc"] > 0.0
    print("PASSED\n")

    print("=== Test 5: _load_dataset_arrays prefers a real dataset in S3 over the bundled synthetic one ===")
    real_dataset = [
        {"ticker": "REAL1", "financials": {
            "total_assets": 100.0, "total_liabilities": 40.0, "current_assets": 30.0,
            "current_liabilities": 15.0, "retained_earnings": 20.0, "ebit": 10.0, "sales": 60.0},
         "headlines": [], "label_distressed": 0},
        {"ticker": "REAL2", "financials": {
            "total_assets": 20.0, "total_liabilities": 35.0, "current_assets": 3.0,
            "current_liabilities": 18.0, "retained_earnings": -12.0, "ebit": -5.0, "sales": 8.0},
         "headlines": [], "label_distressed": 1},
    ]
    boto3.client("s3", region_name="ap-south-1").put_object(
        Bucket="test-distress-model-bucket", Key="datasets/real_companies.json",
        Body=json.dumps(real_dataset),
    )
    os.environ["DATASET_S3_KEY"] = "datasets/real_companies.json"
    importlib.reload(retrain_handler)  # picks up the new DATASET_S3_KEY env var
    X, y = retrain_handler._load_dataset_arrays()
    assert len(X) == 2, f"Expected 2 records from the S3 dataset, got {len(X)}"
    print(f"PASSED: loaded {len(X)} records from S3 (the real dataset), not the bundled synthetic one\n")

    print("=== Test 6: falls back to local dataset if DATASET_S3_KEY points at nothing ===")
    os.environ["DATASET_S3_KEY"] = "datasets/does_not_exist.json"
    importlib.reload(retrain_handler)
    X, y = retrain_handler._load_dataset_arrays()
    assert len(X) > 2, "Expected the bundled synthetic dataset (120 records) as a fallback"
    print(f"PASSED: fell back to local dataset ({len(X)} records) when the S3 key was missing\n")

    print("ALL TESTS PASSED")


run_test()
