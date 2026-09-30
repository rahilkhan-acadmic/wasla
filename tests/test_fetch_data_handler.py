"""
End-to-end test of fetch_data_handler with FETCH_MARKETS=us,india_gsm, using
the REAL _EnvArgs and the REAL india_gsm plugin code path -- only the
network calls (SEC, NSE, yfinance) are faked, and S3 is moto-mocked.

Three scenarios:
  1. Healthy: every source works -> both markets appear in records_by_market
  2. One-sided: NSE blocked but yfinance works -> healthy-only rows, flagged
  3. Degraded: NSE blocks the request (plausible from AWS datacenter IPs) ->
     the handler must NOT crash, must still deliver the US data, and must
     make the silent failure visible via markets_with_no_records.

Run from the project root: python tests/test_fetch_data_handler.py
"""
import os
import sys
import json

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(_ROOT, "src"))
sys.path.insert(0, os.path.join(_ROOT, "data"))

os.environ.update({
    "MODEL_BUCKET": "test-bucket",
    "DATASET_S3_KEY": "datasets/real_companies.json",
    "FETCH_MARKETS": "us,india_gsm",
    "AWS_DEFAULT_REGION": "ap-south-1",
})

from moto import mock_aws  # noqa: E402
import boto3  # noqa: E402

GOOD_FINANCIALS = {
    "total_assets": 1e6, "total_liabilities": 4e5, "current_assets": 3e5,
    "current_liabilities": 1e5, "retained_earnings": 2e5, "ebit": 1e5, "sales": 5e5,
}


def _us_records(args):
    # NOTE: the real US plugin stamps records "US" (uppercase) while its
    # registry code is "us". This fake deliberately mirrors that -- an earlier
    # version used lowercase "us" here, which masked a bug where the handler
    # compared the two and falsely flagged a healthy US fetch as empty.
    return [
        {"ticker": "US-1", "company_name": "US Distressed", "market": "US",
         "financials": GOOD_FINANCIALS, "headlines": [], "label_distressed": 1,
         "event_date": None, "source": "fake"},
        {"ticker": "US-2", "company_name": "US Healthy", "market": "US",
         "financials": GOOD_FINANCIALS, "headlines": [], "label_distressed": 0,
         "event_date": None, "source": "fake"},
    ]


@mock_aws
def run():
    boto3.client("s3", region_name="ap-south-1").create_bucket(
        Bucket="test-bucket", CreateBucketConfiguration={"LocationConstraint": "ap-south-1"})

    # Patch through the REGISTRY so we hit the exact module objects the
    # handler uses (importing nse_gsm_labels directly would load a second,
    # separate copy of the module, and the fakes would land on the wrong one).
    import build_dataset
    gsm = build_dataset.MARKET_REGISTRY["india_gsm"]
    build_dataset.MARKET_REGISTRY["us"].build = _us_records

    gsm.fetch_financials_for_ticker = lambda t: GOOD_FINANCIALS
    gsm.fetch_recent_news_headlines = lambda t: []

    import fetch_data_handler as fdh

    print("=== Scenario 1: healthy -- both markets deliver ===")
    gsm.fetch_gsm_list = lambda max_results=20: [
        {"symbol": "AGSTRA", "company_name": "AGS Transact", "stage": "IBC", "is_ibc": True}]
    result = fdh.fetch_data_handler({}, None)
    print(json.dumps(result["records_by_market"], indent=2))
    assert result["records_by_market"]["us"] == {"distressed": 1, "healthy": 1}
    assert result["records_by_market"]["india_gsm"]["distressed"] == 1
    assert result["records_by_market"]["india_gsm"]["healthy"] == 5
    assert result["markets_with_no_records"] == [], \
        f"A healthy run must not flag anything, got {result['markets_with_no_records']}"
    assert result["markets_missing_a_class"] == []
    print("PASSED\n")

    print("=== Scenario 2: one-sided -- NSE blocked but yfinance still works, "
          "leaving india_gsm with only healthy rows ===")

    def blocked_gsm(max_results=20):
        raise RuntimeError("403 Forbidden (simulating NSE blocking a datacenter IP)")
    gsm.fetch_gsm_list = blocked_gsm
    result = fdh.fetch_data_handler({}, None)
    assert result["records_by_market"]["india_gsm"] == {"distressed": 0, "healthy": 5}
    assert result["markets_with_no_records"] == []
    assert result["markets_missing_a_class"] == ["india_gsm"], \
        "A market returning only one class skews the dataset and must be flagged"
    assert "us" not in result["markets_missing_a_class"]
    print("PASSED\n")

    print("=== Scenario 3: fully degraded -- NSE blocks the request AND the healthy "
          "comparison fetch fails; handler must not crash ===")

    def blocked(max_results=20):
        raise RuntimeError("403 Forbidden (simulating NSE blocking a datacenter IP)")
    gsm.fetch_gsm_list = blocked
    gsm.fetch_financials_for_ticker = lambda t: {k: None for k in GOOD_FINANCIALS}

    result = fdh.fetch_data_handler({}, None)
    print(json.dumps({k: result[k] for k in ("markets_with_no_records", "markets_missing_a_class", "records_by_market")}, indent=2))
    assert result["records_by_market"]["us"] == {"distressed": 1, "healthy": 1}, \
        "US data must still be delivered when another market's source is down"
    assert "india_gsm" in result["markets_with_no_records"], \
        "A silently failed market must be flagged, not hidden"
    print("PASSED\n")

    obj = boto3.client("s3", region_name="ap-south-1").get_object(
        Bucket="test-bucket", Key="datasets/real_companies.json")
    assert len(json.loads(obj["Body"].read())) == 2
    print("ALL TESTS PASSED")


run()
