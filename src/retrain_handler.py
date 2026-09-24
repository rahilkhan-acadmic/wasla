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
    - Downloads the CURRENTLY DEPLOYED model from the registry and evaluates
      it on the same held-out test set, for a fair apples-to-apples AUC
      comparison
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
import numpy as np
import xgboost as xgb

from features import build_feature_row, financials_from_dict, FEATURE_NAMES, has_complete_financials
from train_classifier import train_model

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


def _load_dataset_arrays():
    """Loads the training dataset. Prefers a fresh real dataset written to
    S3 by fetch_data_handler.py's scheduled run (DATASET_S3_KEY); falls
    back to a local file (DATASET_PATH env var, else the bundled synthetic
    dataset) if S3 isn't configured or the download fails -- e.g. before
    the fetch step has ever run, or if it errors on a given week. Same
    schema either way, so nothing below this function needs to know which
    source it came from."""
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
        raw = json.load(f)

    X, y = [], []
    for row in raw:
        if not has_complete_financials(row["financials"]):
            continue  # same guard as train_classifier.py -- see features.py's docstring
        fin = financials_from_dict(row["financials"])
        feats = build_feature_row(fin, row.get("headlines", []))
        X.append([feats[name] for name in FEATURE_NAMES])
        y.append(row["label_distressed"])
    return np.array(X), np.array(y)


def _evaluate_existing_model(X, y) -> float:
    """Downloads and scores the currently-registered model on the given
    data, for a fair comparison against the freshly trained candidate."""
    from sklearn.metrics import roc_auc_score

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
    X, y = _load_dataset_arrays()

    new_model, new_auc, _ = train_model(X, y)
    current_auc = _evaluate_existing_model(X, y)

    candidate_key = f"models/{MODEL_REGISTRY_KEY}/candidate/model-{int(time.time())}.json"
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        new_model.save_model(tmp.name)
        boto3.client("s3").upload_file(tmp.name, MODEL_BUCKET, candidate_key)

    return {
        "candidate_s3_key": candidate_key,
        "new_auc": round(new_auc, 4),
        "current_auc": round(current_auc, 4),
        "auc_improvement": round(new_auc - current_auc, 4),
    }


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
