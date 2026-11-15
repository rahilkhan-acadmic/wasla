"""
Tests for the manual market-data refresh ("Refresh now" on the dashboard):

  * start_refresh writes a "running" status before starting the job, refuses
    a second start while one runs (409 from the API), and allows a new one
    once a run is past its time budget (stale);
  * the S&P 500's 4 parts run one after another on a manual refresh: each
    part starts the next ("chain"), and the last one marks the run done;
  * a failing part marks the run failed; a scheduled (Sunday) run reports
    its status the same way;
  * GET/POST /market/refresh.

No network: S3 is moto-mocked, Lambda invokes and the data fetch are fakes.

Run from the project root: python tests/test_market_refresh.py
"""
import os
import sys
import time

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(_ROOT, "src"))

os.environ["AWS_DEFAULT_REGION"] = "ap-south-1"
os.environ["AWS_REGION"] = "ap-south-1"
os.environ["COGNITO_USER_POOL_ID"] = "ap-south-1_testpool"
os.environ["COGNITO_CLIENT_ID"] = "test-client-id"
for var in ("MODEL_BUCKET", "MARKET_SNAPSHOT_PATH", "MARKET_SNAPSHOT_PATH_US", "MARKET_UNIVERSE"):
    os.environ.pop(var, None)

import boto3
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from moto import mock_aws

import auth
import market_data

BUCKET = "distress-model-test"
_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class _FakeSigningKey:
    def __init__(self, key):
        self.key = key


class _FakeJwkClient:
    def get_signing_key_from_jwt(self, token):
        return _FakeSigningKey(_PRIVATE_KEY.public_key())


def _auth_header():
    auth._cached_jwk_client = _FakeJwkClient()
    now = int(time.time())
    token = jwt.encode(
        {"sub": "u-1", "cognito:username": "rahil", "aud": os.environ["COGNITO_CLIENT_ID"],
         "iss": f"https://cognito-idp.{os.environ['AWS_REGION']}.amazonaws.com/{os.environ['COGNITO_USER_POOL_ID']}",
         "iat": now, "exp": now + 3600},
        _PRIVATE_KEY, algorithm="RS256")
    return {"Authorization": f"Bearer {token}"}


class _Ctx:
    function_name = "distress-model-us-snapshot"

    def get_remaining_time_in_millis(self):
        return 600_000


def _setup_bucket():
    os.environ["MODEL_BUCKET"] = BUCKET
    s3 = boto3.client("s3", region_name="ap-south-1")
    s3.create_bucket(Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": "ap-south-1"})
    for cache in market_data._snapshot_caches.values():
        cache.update(value=None, loaded_at=0.0)


def _fake_run(calls, fail_on=None):
    def run(u, shard, shards, context):
        calls.append((u.id, shard, shards))
        if fail_on == shard:
            raise RuntimeError("Yahoo said no")
        return {"universe": u.id, "shard": f"{shard + 1} of {shards}"}
    return run


@mock_aws
def test_start_refresh_writes_status_and_refuses_a_second_run():
    _setup_bucket()
    try:
        invoked = []
        st = market_data.start_refresh("us", requested_by="rahil", invoker=lambda fn, ev: invoked.append((fn, ev)))
        assert st["state"] == "running" and st["trigger"] == "manual" and st["requested_by"] == "rahil"
        assert invoked == [("distress-model-us-snapshot", {"trigger_reason": "manual", "universe": "us",
                                                           "shard": 0, "shards": 4, "chain": True})], invoked
        assert market_data.read_refresh_status("us")["state"] == "running"

        try:
            market_data.start_refresh("us", invoker=lambda fn, ev: invoked.append((fn, ev)))
        except market_data.RefreshInProgress as e:
            assert e.status["started_at"] == st["started_at"]
        else:
            raise AssertionError("second start should be refused while running")
        assert len(invoked) == 1

        # NSE is independent and runs as one job, no shards.
        market_data.start_refresh("nse", invoker=lambda fn, ev: invoked.append((fn, ev)))
        assert invoked[-1] == ("distress-model-nse-snapshot", {"trigger_reason": "manual", "universe": "nse"})

        # A run that never reported back is stale after its budget: allowed again.
        old = {**st, "started_at": "2026-01-01T00:00:00Z", "heartbeat_at": "2026-01-01T00:05:00Z"}
        market_data.write_refresh_status("us", old)
        assert market_data.effective_state(old, "us") == "stale"
        market_data.start_refresh("us", invoker=lambda fn, ev: invoked.append((fn, ev)))
        assert len(invoked) == 3

        # Lambda refusing the invoke -> status failed, error raised.
        market_data.write_refresh_status("us", {"state": "done"})

        def broken(fn, ev):
            raise PermissionError("AccessDenied")
        try:
            market_data.start_refresh("us", invoker=broken)
        except PermissionError:
            pass
        else:
            raise AssertionError("expected the invoke error")
        failed = market_data.read_refresh_status("us")
        assert failed["state"] == "failed" and "AccessDenied" in failed["error"], failed

        assert market_data.effective_state(None, "nse") == "idle"
        # Stale is measured from the last sign of life, not the start: a long
        # run with a recent heartbeat (Sunday's parts are 25 min apart) is fine.
        long_run = {"state": "running", "started_at": "2026-11-15T02:00:00Z", "heartbeat_at": "2026-11-15T02:57:00Z"}
        now = market_data._parse_iso("2026-11-15T03:14:00Z")
        assert market_data.effective_state(long_run, "us", now=now) == "running"
        assert market_data.effective_state(long_run, "us", now=now + 20 * 60) == "stale"
    finally:
        os.environ.pop("MODEL_BUCKET", None)
    print("PASS: start_refresh: running status, invoke (US chained 4 parts), 2nd start refused, stale "
          "allowed, invoke failure -> failed")


@mock_aws
def test_chained_parts_run_in_turn_and_last_marks_done():
    _setup_bucket()
    real_run = market_data._run_snapshot
    calls, invoked = [], []
    try:
        market_data._run_snapshot = _fake_run(calls)
        st = market_data.start_refresh("us", requested_by="rahil", invoker=lambda fn, ev: invoked.append(ev))
        # Simulate Lambda: run each invoked event in turn.
        while invoked:
            ev = invoked.pop(0)
            market_data.snapshot_handler(ev, _Ctx(), invoker=lambda fn, e: invoked.append(e))
            if ev["shard"] < 3:
                cur = market_data.read_refresh_status("us")
                assert cur["state"] == "running" and cur["progress"] == f"{ev['shard'] + 1} of 4 parts done", cur
        assert calls == [("us", i, 4) for i in range(4)], calls
        done = market_data.read_refresh_status("us")
        assert done["state"] == "done" and done["finished_at"] and done["progress"] == "4 of 4 parts done"
        # The manual request's start time and requester are kept by part 1.
        assert done["started_at"] == st["started_at"] and done["requested_by"] == "rahil", done
    finally:
        market_data._run_snapshot = real_run
        os.environ.pop("MODEL_BUCKET", None)
    print("PASS: manual US refresh: parts 1-4 run one after another, progress reported, last marks done")


@mock_aws
def test_failures_and_scheduled_runs_report_status():
    _setup_bucket()
    real_run = market_data._run_snapshot
    calls, invoked = [], []
    try:
        market_data._run_snapshot = _fake_run(calls, fail_on=1)
        market_data.snapshot_handler({"trigger_reason": "manual", "universe": "us", "shard": 0, "shards": 4,
                                      "chain": True}, _Ctx(), invoker=lambda fn, e: invoked.append(e))
        try:
            market_data.snapshot_handler(invoked.pop(), _Ctx(), invoker=lambda fn, e: invoked.append(e))
        except RuntimeError:
            pass
        else:
            raise AssertionError("part 2 should fail")
        st = market_data.read_refresh_status("us")
        assert st["state"] == "failed" and st["error"].startswith("Part 2 of 4: RuntimeError"), st
        assert invoked == []  # the chain stops at the failure

        # Sunday: NSE single run, scheduled -> running then done, trigger scheduled.
        market_data._run_snapshot = _fake_run(calls)
        market_data.snapshot_handler({"trigger_reason": "scheduled"}, _Ctx())
        st = market_data.read_refresh_status("nse")
        assert st["state"] == "done" and st["trigger"] == "scheduled" and st["requested_by"] is None, st

        # Scheduled US parts (no chain) don't start each other; part 4 marks done.
        for i in range(4):
            market_data.snapshot_handler({"trigger_reason": "scheduled", "universe": "us", "shard": i, "shards": 4},
                                         _Ctx(), invoker=lambda fn, e: invoked.append(e))
            assert invoked == []
        st = market_data.read_refresh_status("us")
        assert st["state"] == "done" and st["trigger"] == "scheduled" and st["error"] is None, st
    finally:
        market_data._run_snapshot = real_run
        os.environ.pop("MODEL_BUCKET", None)
    print("PASS: a failing part marks the run failed and stops the chain; scheduled runs report status too")


@mock_aws
def test_refresh_endpoints():
    _setup_bucket()
    import importlib
    import app as app_module
    importlib.reload(app_module)
    from fastapi.testclient import TestClient
    client = TestClient(app_module.app)
    h = _auth_header()
    invoked = []
    real_invoke = app_module.market_data._invoke_async
    app_module.market_data._invoke_async = lambda fn, ev: invoked.append((fn, ev))
    try:
        assert client.get("/market/refresh").status_code == 401
        assert client.post("/market/refresh").status_code == 401
        assert client.post("/market/refresh?universe=mars", headers=h).status_code == 400

        idle = client.get("/market/refresh?universe=us", headers=h).json()
        assert idle["state"] == "idle" and idle["index"] == "S&P 500" and idle["expected_minutes"] == 30

        r = client.post("/market/refresh?universe=us", headers=h)
        assert r.status_code == 202 and r.json()["state"] == "running", r.text
        assert invoked[0][0] == "distress-model-us-snapshot" and invoked[0][1]["chain"] is True
        assert market_data.read_refresh_status("us")["requested_by"] == "rahil"

        again = client.post("/market/refresh?universe=us", headers=h)
        assert again.status_code == 409 and again.json()["detail"]["status"]["state"] == "running", again.text
        assert len(invoked) == 1

        nse = client.post("/market/refresh", headers=h)
        assert nse.status_code == 202 and nse.json()["universe"] == "nse" and nse.json()["expected_minutes"] == 12
        assert client.get("/market/refresh", headers=h).json()["state"] == "running"
    finally:
        app_module.market_data._invoke_async = real_invoke
        os.environ.pop("MODEL_BUCKET", None)
    print("PASS: GET/POST /market/refresh: auth, 400 unknown index, 202 start, 409 while running")


if __name__ == "__main__":
    test_start_refresh_writes_status_and_refuses_a_second_run()
    test_chained_parts_run_in_turn_and_last_marks_done()
    test_failures_and_scheduled_runs_report_status()
    test_refresh_endpoints()
    print("\nAll market refresh tests passed.")
