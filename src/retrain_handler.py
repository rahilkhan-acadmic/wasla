"""
Lambda handlers for the automated retrain pipeline, called by Step Functions
(see aws/state_machine.asl.json). Two handlers, deployed as two Lambda
functions sharing the SAME container image as app.py (distress-model-api) --
just with a different handler entry point configured per-function, so no
separate image build is needed.

train_and_evaluate_handler:
    - Loads the training dataset -- prefers a fresh one at DATASET_S3_KEY in
      S3 (written by fetch_data_handler.py's scheduled run), falling back to
      a local bundled file if that isn't present. See _load_dataset_arrays.
    - Trains a new model
    - Downloads the CURRENTLY DEPLOYED model from the registry and scores it
      on the same held-out split (via train_classifier.split_dataset) that
      the new model is scored on, so the two AUCs are computed on identical
      records.

      KNOWN LIMITATION: this is comparable, not clean. The deployed model was
      trained on earlier fetches that overlap heavily with this week's data,
      so it has likely already SEEN some of these held-out records -- which
      flatters it relative to the new model. The rigorous fix is a fixed
      holdout set that no model ever trains on, or a time-based split (train
      on older filings, test on newer ones). Until then, treat a small AUC
      gap either way with suspicion, and watch test_set_size in the output:
      with a few dozen records the held-out set is a handful of companies.
    - Writes the new candidate model to a "candidate" key in S3 (NOT the
      live path -- it isn't promoted yet)
    - Returns both AUC scores and the candidate's S3 key so Step Functions'
      Choice state can decide whether to promote it

register_model_handler:
    - Called only when the Choice state decides the candidate improved
    - Copies the candidate model to a new versioned key
    - Updates the DynamoDB pointer to that new version
    - This is the ONLY step that actually changes what the live inference
      Lambda serves -- and it does so with zero redeploy of that Lambda
"""

import json
import os
import time
import tempfile

import boto3
import xgboost as xgb
from sklearn.metrics import roc_auc_score

from train_classifier import (
    train_model, split_dataset, make_model, rows_to_arrays,
    time_split_dataset, check_time_split_gate,
)

MODEL_BUCKET = os.environ.get("MODEL_BUCKET")
MODEL_REGISTRY_TABLE = os.environ.get("MODEL_REGISTRY_TABLE")
MODEL_REGISTRY_KEY = os.environ.get("MODEL_REGISTRY_KEY", "distress-classifier")
DATASET_S3_KEY = os.environ.get("DATASET_S3_KEY")  # written by fetch_data_handler.py, if configured
SAMPLE_DATA_PATH = os.environ.get(
    "SAMPLE_DATA_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "sample_companies.json"),
)

# Minimum AUC improvement required to promote a new model over the current
# one. Guards against promoting a model that's different only due to random
# noise in a small dataset. Tune once real data makes AUC deltas meaningful.
PROMOTION_AUC_MARGIN = float(os.environ.get("PROMOTION_AUC_MARGIN", "0.01"))

# If set (YYYY-MM-DD), evaluation uses train_classifier.time_split_dataset
# instead of a random split -- train on companies dated before this, test on
# companies dated at/after it. Left unset by default: at the current real
# dataset's size this gate fails for every reasonable cutoff (see
# CLAUDE.md's known-limitations notes), so there is nothing to gain from
# forcing it on yet. When it IS set and the gate fails anyway (too few
# unique companies per class on one side), this handler logs why and falls
# back to the random split rather than crashing the scheduled run.
EVAL_SPLIT_CUTOFF_DATE = os.environ.get("EVAL_SPLIT_CUTOFF_DATE")
EVAL_MIN_PER_CLASS = int(os.environ.get("EVAL_MIN_PER_CLASS", "5"))


def _load_dataset_records() -> list[dict]:
    """Loads the raw training dataset records, unfiltered and with
    event_date/market intact -- needed for time_split_dataset(). Prefers a
    fresh real dataset written to S3 by fetch_data_handler.py's scheduled
    run (DATASET_S3_KEY); falls back to a local file (DATASET_PATH env var,
    else the bundled synthetic dataset) if S3 isn't configured or the
    download fails -- e.g. before the fetch step has ever run, or if it
    errors on a given week. Same schema either way, so nothing below this
    function needs to know which source it came from."""
    dataset_path = None

    if DATASET_S3_KEY and MODEL_BUCKET:
        try:
            with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
                boto3.client("s3").download_file(MODEL_BUCKET, DATASET_S3_KEY, tmp.name)
                dataset_path = tmp.name
            print(f"Loaded dataset from s3://{MODEL_BUCKET}/{DATASET_S3_KEY}")
        except Exception as e:
            print(f"Could not load dataset from s3://{MODEL_BUCKET}/{DATASET_S3_KEY} "
                  f"({e}); falling back to local dataset.")

    if dataset_path is None:
        dataset_path = os.environ.get("DATASET_PATH", SAMPLE_DATA_PATH)
        print(f"Loaded dataset from local file {dataset_path}")

    with open(dataset_path) as f:
        return json.load(f)


def _load_dataset_arrays():
    """Backward-compatible (X, y) view of _load_dataset_records(), for
    callers that don't need the time-based split."""
    X, y, _ = rows_to_arrays(_load_dataset_records())
    return X, y


def _evaluate_existing_model(X, y) -> float:
    """Downloads and scores the currently-registered model on the given
    data, for a fair comparison against the freshly trained candidate."""
    ddb = boto3.resource("dynamodb").Table(MODEL_REGISTRY_TABLE)
    item = ddb.get_item(Key={"model_name": MODEL_REGISTRY_KEY}).get("Item")
    if item is None:
        return 0.0  # no current model -- any real candidate beats "nothing"

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        boto3.client("s3").download_file(MODEL_BUCKET, item["s3_key"], tmp.name)
        current_model = xgb.XGBClassifier()
        current_model.load_model(tmp.name)

    probs = current_model.predict_proba(X)[:, 1]
    return float(roc_auc_score(y, probs))


def train_and_evaluate_handler(event, context):
    records = _load_dataset_records()

    # Try a time-based eval split (train on companies dated before the
    # cutoff, test on companies dated at/after it) when EVAL_SPLIT_CUTOFF_DATE
    # is configured. Falls back to the random split -- the ONLY mode that
    # existed before this -- if it's unset, or if the gate finds too few
    # unique companies of either class on either side to trust the result.
    # This is a graceful degrade, not a silent one: the fallback reason is
    # surfaced in the returned eval_gate_reason field.
    eval_mode = "random"
    gate_reason = None

    if EVAL_SPLIT_CUTOFF_DATE:
        try:
            train_rows, test_rows = time_split_dataset(records, EVAL_SPLIT_CUTOFF_DATE)
            check_time_split_gate(train_rows, test_rows, min_per_class=EVAL_MIN_PER_CLASS)
            eval_mode = "time"
        except ValueError as e:
            gate_reason = str(e)
            print(f"Time split gate failed, falling back to random split: {gate_reason}")

    if eval_mode == "time":
        X_train, y_train, _ = rows_to_arrays(train_rows)
        X_test, y_test, _ = rows_to_arrays(test_rows)
        new_model = make_model()
        new_model.fit(X_train, y_train)
        new_auc = float(roc_auc_score(y_test, new_model.predict_proba(X_test)[:, 1]))
    else:
        X, y, _ = rows_to_arrays(records)
        new_model, new_auc, _ = train_model(X, y)
        # Score the currently-deployed model on the SAME held-out split the
        # new model was scored on (split_dataset is deterministic), so the
        # two AUCs are actually comparable. Previously this scored the live
        # model on ALL records while the new model was scored only on its
        # held-out quarter -- different data, so the comparison meant
        # nothing.
        _, X_test, _, y_test = split_dataset(X, y)

    current_auc = _evaluate_existing_model(X_test, y_test)

    candidate_key = f"models/{MODEL_REGISTRY_KEY}/candidate/model-{int(time.time())}.json"
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        new_model.save_model(tmp.name)
        boto3.client("s3").upload_file(tmp.name, MODEL_BUCKET, candidate_key)

    result = {
        "candidate_s3_key": candidate_key,
        "new_auc": round(new_auc, 4),
        "current_auc": round(current_auc, 4),
        "auc_improvement": round(new_auc - current_auc, 4),
        "eval_mode": eval_mode,
        # How many records both AUCs were computed on. With a small dataset
        # this is tiny, and the AUCs are correspondingly noisy -- surfaced
        # here so it's visible next to the numbers rather than buried.
        "test_set_size": int(len(y_test)),
    }
    if gate_reason:
        result["eval_gate_reason"] = gate_reason
    return result


def register_model_handler(event, context):
    """event is the output of train_and_evaluate_handler, passed through by
    Step Functions after the Choice state approves promotion."""
    candidate_key = event["candidate_s3_key"]
    version = f"v{int(time.time())}"
    promoted_key = f"models/{MODEL_REGISTRY_KEY}/{version}/model.json"

    s3 = boto3.client("s3")
    s3.copy_object(
        Bucket=MODEL_BUCKET,
        CopySource={"Bucket": MODEL_BUCKET, "Key": candidate_key},
        Key=promoted_key,
    )

    boto3.resource("dynamodb").Table(MODEL_REGISTRY_TABLE).put_item(Item={
        "model_name": MODEL_REGISTRY_KEY,
        "s3_key": promoted_key,
        "version": version,
        "promoted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })

    return {"version": version, "s3_key": promoted_key}
