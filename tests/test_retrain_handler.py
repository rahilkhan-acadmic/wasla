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

    print("=== Test 7: the live model is scored on the SAME held-out split as the new model ===")
    from train_classifier import split_dataset
    os.environ.pop("DATASET_S3_KEY", None)
    importlib.reload(retrain_handler)  # local bundled dataset again
    X_all, y_all = retrain_handler._load_dataset_arrays()
    _, _, _, y_expected_test = split_dataset(X_all, y_all)

    captured = {}
    real_eval = retrain_handler._evaluate_existing_model

    def spy(X_arg, y_arg):
        captured["y"] = list(y_arg)
        return real_eval(X_arg, y_arg)

    retrain_handler._evaluate_existing_model = spy
    result7 = retrain_handler.train_and_evaluate_handler({}, None)

    assert len(captured["y"]) < len(y_all), (
        f"Live model was scored on {len(captured['y'])} of {len(y_all)} records -- "
        f"the WHOLE dataset, not the held-out split the new model is scored on")
    assert captured["y"] == list(y_expected_test), \
        "Live model must be scored on exactly the held-out split split_dataset() produces"
    assert result7["test_set_size"] == len(y_expected_test)
    print(f"PASSED: both models scored on the same {result7['test_set_size']} held-out records "
          f"(not all {len(y_all)})\n")

    retrain_handler._evaluate_existing_model = real_eval

    print("=== Test 8: incumbent_comparable -- when the current model is a fair bar ===")
    ic = retrain_handler.incumbent_comparable
    assert ic(None, "time", "2023-01-01")[0] is False
    legacy = {"version": "v1790617273", "s3_key": "x"}  # promoted before provenance existed
    ok, why = ic(legacy, "time", "2023-01-01")
    assert not ok and "before training provenance" in why, why
    assert ic(legacy, "random", None)[0] is False
    timed = {"version": "v2", "eval_mode": "time", "trained_before": "2023-01-01"}
    assert ic(timed, "time", "2023-01-01")[0] is True
    assert ic(timed, "time", "2024-01-01")[0] is True       # trained on less than this run's train side
    assert ic(timed, "time", "2022-01-01")[0] is False      # trained on companies this run tests on
    assert ic(timed, "random", None)[0] is False
    assert ic({"version": "v3", "eval_mode": "random"}, "random", None)[0] is True
    assert ic({"version": "v3", "eval_mode": "random"}, "time", "2023-01-01")[0] is False
    print("PASSED: legacy/unknown/overlapping models are not comparable; time- and random-split "
          "models are, against runs that can't contain their training data\n")

    print("=== Test 9: the 2026-11 bug -- a legacy model trained on ALL data no longer blocks every candidate ===")
    from train_classifier import make_model
    import tempfile as _tf
    legacy_model = make_model()
    legacy_model.fit(X_all, y_all)  # saw every company, including the held-out ones
    with _tf.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        legacy_model.save_model(tmp.name)
        boto3.client("s3", region_name="ap-south-1").upload_file(
            tmp.name, "test-distress-model-bucket", "models/distress-classifier/v1790617273/model.json")
    table = boto3.resource("dynamodb", region_name="ap-south-1").Table("test-distress-model-registry")
    table.put_item(Item={"model_name": "distress-classifier", "version": "v1790617273",
                         "s3_key": "models/distress-classifier/v1790617273/model.json",
                         "promoted_at": "2026-09-28T17:41:14Z"})
    r9 = retrain_handler.train_and_evaluate_handler({}, None)
    print(json.dumps(r9, indent=2))
    assert r9["current_auc"] >= r9["new_auc"], "a model that saw the test set should look at least as good"
    assert r9["decision"] == "minimum_bar" and "before training provenance" in r9["decision_reason"]
    assert r9["promote"] == (r9["new_auc"] >= retrain_handler.PROMOTION_MIN_AUC)
    assert str(retrain_handler.PROMOTION_MIN_AUC) in r9["decision_reason"]
    print(f"PASSED: judged on the minimum bar (AUC {r9['new_auc']} vs {retrain_handler.PROMOTION_MIN_AUC}), "
          f"promote={r9['promote']}, despite the legacy model's {r9['current_auc']}\n")

    print("=== Test 10: promotion records provenance; the next run compares fairly ===")
    reg = retrain_handler.register_model_handler(r9, None)
    item = table.get_item(Key={"model_name": "distress-classifier"})["Item"]
    assert item["eval_mode"] == "random" and "trained_before" not in item, item
    assert item["decision"] == "minimum_bar" and item["new_auc"] == str(r9["new_auc"]), item
    r10 = retrain_handler.train_and_evaluate_handler({}, None)
    assert r10["decision"] == "compared", r10
    assert r10["promote"] == (r10["auc_improvement"] > retrain_handler.PROMOTION_AUC_MARGIN)
    # A time-split promotion stores its cutoff.
    retrain_handler.register_model_handler({**r9, "eval_mode": "time", "trained_before": "2023-01-01"}, None)
    item = table.get_item(Key={"model_name": "distress-classifier"})["Item"]
    assert item["eval_mode"] == "time" and item["trained_before"] == "2023-01-01", item
    print(f"PASSED: registry stores eval_mode/trained_before; next run 'compared' "
          f"(improvement {r10['auc_improvement']}, promote={r10['promote']})\n")

    print("ALL TESTS PASSED")


run_test()
