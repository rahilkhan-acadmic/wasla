"""
Loads the current production model, preferring a "pointer" stored in DynamoDB
(which points at a versioned object in S3), with a fallback to a local file.
This is what lets the inference API pick up a freshly retrained model just by
updating a DynamoDB item + uploading to S3 -- no code deployment required.

Environment variables (all optional -- unset means "use local file only"):
    MODEL_REGISTRY_TABLE   DynamoDB table name holding the "current" pointer
    MODEL_REGISTRY_KEY     Partition key value for this model (default: "distress-classifier")
    MODEL_BUCKET           S3 bucket the versioned model files live in
    MODEL_LOCAL_CACHE      Local path to cache the downloaded model (default: /tmp/model.json)
    MODEL_PATH             Fallback local model path when no registry is configured

Expected DynamoDB item shape (partition key: model_name):
    {
        "model_name": "distress-classifier",
        "s3_key": "models/distress-classifier/v7/model.json",
        "version": "v7",
        "promoted_at": "2026-09-08T12:00:00Z"
    }

The training pipeline's "register/promote" step is what writes this item --
see aws/state_machine.asl.json's RegisterModel state.
"""

import os
import logging

logger = logging.getLogger(__name__)

_cached_model = None
_cached_version = None


def _default_local_path() -> str:
    return os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "models", "distress_model.json"
    )


def _load_xgb(path: str):
    import xgboost as xgb
    model = xgb.XGBClassifier()
    model.load_model(path)
    return model


def _fetch_pointer(table_name: str, key_value: str):
    import boto3
    table = boto3.resource("dynamodb").Table(table_name)
    return table.get_item(Key={"model_name": key_value}).get("Item")


def _download_from_s3(bucket: str, key: str, local_path: str) -> str:
    import boto3
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    boto3.client("s3").download_file(bucket, key, local_path)
    return local_path


def get_model(force_reload: bool = False):
    """Return a loaded XGBClassifier.

    If MODEL_REGISTRY_TABLE and MODEL_BUCKET are both set, checks DynamoDB for
    the current promoted version and downloads it from S3 if it's new (or not
    yet cached in this process). Otherwise falls back to a local model file.
    Caches per warm process -- a warm Lambda container won't re-check the
    registry on every invocation unless force_reload=True.
    """
    global _cached_model, _cached_version

    table_name = os.environ.get("MODEL_REGISTRY_TABLE")
    bucket = os.environ.get("MODEL_BUCKET")
    key_value = os.environ.get("MODEL_REGISTRY_KEY", "distress-classifier")
    local_cache = os.environ.get("MODEL_LOCAL_CACHE", "/tmp/model.json")
    local_fallback = os.environ.get("MODEL_PATH", _default_local_path())

    if not table_name or not bucket:
        if _cached_model is None or force_reload:
            logger.info("No registry configured; loading local model at %s", local_fallback)
            _cached_model = _load_xgb(local_fallback)
            _cached_version = "local"
        return _cached_model

    try:
        item = _fetch_pointer(table_name, key_value)
    except Exception as e:
        logger.warning("Registry lookup failed (%s); using cached/local model instead", e)
        item = None

    if item is None:
        if _cached_model is not None:
            return _cached_model
        logger.warning("No registry pointer found; falling back to local model")
        _cached_model = _load_xgb(local_fallback)
        _cached_version = "local-fallback"
        return _cached_model

    version = item.get("version")
    if _cached_model is not None and version == _cached_version and not force_reload:
        return _cached_model

    logger.info("Loading model %s from s3://%s/%s", version, bucket, item["s3_key"])
    _download_from_s3(bucket, item["s3_key"], local_cache)
    _cached_model = _load_xgb(local_cache)
    _cached_version = version
    return _cached_model


def current_version():
    return _cached_version
