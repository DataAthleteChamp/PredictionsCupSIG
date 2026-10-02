"""Tests for the API client: rate limiting, retry policy, idempotency, latches."""
import json
import time

import pytest

from sigbot.api import (ApiError, Client, DryRunBlocked, Response, TokenBucket)
from sigbot.config import Settings


def make_settings(**kw):
    base = dict(base_url="https://x/api/v1", recon_key="r", exec_key="e",
                dry_run=True, live_trading=False, rate_limit_per_min=6000.0)
    base.update(kw)
    return Settings(**base)


class FakeTransport:
    """Records calls and replays a scripted sequence of responses."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append({
            "method": method, "url": url, "headers": headers,
            "body": json.loads(body) if body else None,
        })
        return self.responses.pop(0) if self.responses else Response(200, {})


def err(status, code):
    return Response(status, {"error": {"code": code, "message": code}})


# ------------------------------------------------------------- token bucket --

def test_token_bucket_allows_burst_then_throttles():
    b = TokenBucket(rate_per_min=60.0, burst=5)
    for _ in range(5):
        assert b.take() == 0.0           # burst is free
    waited = b.take()
    assert waited > 0                    # sixth must wait


def test_token_bucket_rejects_bad_rate():
    with pytest.raises(ValueError):
        TokenBucket(rate_per_min=0)


def test_token_bucket_refills_over_time():
    b = TokenBucket(rate_per_min=60.0, burst=1)
    b.take()
    time.sleep(1.1)
    assert b.take() == 0.0               # refilled


# ------------------------------------------------------------ retry policy --

def test_retries_retryable_status_then_succeeds():
    t = FakeTransport([err(503, "SERVICE_UNAVAILABLE"),
                       err(429, "RATE_LIMITED"),
                       Response(200, {"ok": True})])
    c = Client(make_settings(), transport=t, sleep=lambda s: None)
    assert c.get("/account") == {"ok": True}
    assert len(t.calls) == 3


def test_does_not_retry_client_errors():
    t = FakeTransport([err(400, "VALIDATION_ERROR"), Response(200, {"ok": True})])
    c = Client(make_settings(), transport=t, sleep=lambda s: None)
    with pytest.raises(ApiError) as e:
        c.get("/account")
    assert e.value.code == "VALIDATION_ERROR"
    assert len(t.calls) == 1             # exactly one attempt


def test_does_not_retry_insufficient_scopes():
    t = FakeTransport([err(403, "INSUFFICIENT_SCOPES")])
    c = Client(make_settings(), transport=t, sleep=lambda s: None)
    with pytest.raises(ApiError):
        c.get("/account")
    assert len(t.calls) == 1


def test_gives_up_after_max_tries():
    t = FakeTransport([err(503, "TX_CONFLICT")] * 10)
    c = Client(make_settings(), transport=t, sleep=lambda s: None)
    with pytest.raises(ApiError):
        c._call("GET", "/x", key="r", max_tries=4)
    assert len(t.calls) == 4


def test_order_status_unknown_is_retryable():
    """A 502 may already have executed; retrying the SAME key is the safe move."""
    assert ApiError(502, "ORDER_STATUS_UNKNOWN", "").retryable
    assert ApiError(409, "REQUEST_IN_FLIGHT", "").retryable
    assert not ApiError(409, "CONFLICT", "").retryable


# --------------------------------------------------------------- idempotency --

def test_place_order_sends_idempotency_key():
    t = FakeTransport([Response(200, {"orderId": 1})])
    c = Client(make_settings(dry_run=False, live_trading=True), transport=t,
               sleep=lambda s: None)
    c.place_order("36", "yes", "buy", 100, 0.42)
    body = t.calls[0]["body"]
    assert body["idempotencyKey"]
    assert body["exchangeId"] == "36"
    assert body["quantity"] == 100
    assert body["price"] == 0.42


def test_retry_reuses_the_same_idempotency_key():
    """This is the property that makes a 502 safe: no double-placement."""
    t = FakeTransport([err(503, "SERVICE_UNAVAILABLE"), Response(200, {"orderId": 7})])
    c = Client(make_settings(dry_run=False, live_trading=True), transport=t,
               sleep=lambda s: None)
    c.place_order("36", "yes", "buy", 10, 0.5)
    keys = {call["body"]["idempotencyKey"] for call in t.calls}
    assert len(t.calls) == 2
    assert len(keys) == 1


def test_explicit_idempotency_key_is_honoured():
    t = FakeTransport([Response(200, {})])
    c = Client(make_settings(dry_run=False, live_trading=True), transport=t,
               sleep=lambda s: None)
    c.place_order("36", "yes", "buy", 10, 0.5, idempotency_key="my-key")
    assert t.calls[0]["body"]["idempotencyKey"] == "my-key"


def test_market_order_omits_price():
    t = FakeTransport([Response(200, {})])
    c = Client(make_settings(dry_run=False, live_trading=True), transport=t,
               sleep=lambda s: None)
    c.place_order("36", "yes", "buy", 10, None)
    assert "price" not in t.calls[0]["body"]


# --------------------------------------------------------------- safety ------

def test_dry_run_blocks_placement():
    c = Client(make_settings(dry_run=True, live_trading=True),
               transport=FakeTransport([]), sleep=lambda s: None)
    with pytest.raises(DryRunBlocked):
        c.place_order("36", "yes", "buy", 1, 0.5)


def test_live_trading_flag_alone_is_not_enough():
    c = Client(make_settings(dry_run=False, live_trading=False),
               transport=FakeTransport([]), sleep=lambda s: None)
    with pytest.raises(DryRunBlocked):
        c.place_order("36", "yes", "buy", 1, 0.5)


def test_both_latches_required_for_cancel_too():
    c = Client(make_settings(dry_run=True, live_trading=False),
               transport=FakeTransport([]), sleep=lambda s: None)
    with pytest.raises(DryRunBlocked):
        c.cancel_order(1)
    with pytest.raises(DryRunBlocked):
        c.cancel_all(exchange_id="36")


def test_missing_exec_key_blocks_writes():
    c = Client(make_settings(dry_run=False, live_trading=True, exec_key=""),
               transport=FakeTransport([]), sleep=lambda s: None)
    with pytest.raises(DryRunBlocked):
        c.place_order("36", "yes", "buy", 1, 0.5)


def test_cancel_all_rejects_both_scopes():
    c = Client(make_settings(dry_run=False, live_trading=True),
               transport=FakeTransport([Response(200, {})]), sleep=lambda s: None)
    with pytest.raises(ValueError):
        c.cancel_all(exchange_id="1", market_id="2")


def test_reads_use_recon_key_and_writes_use_exec_key():
    t = FakeTransport([Response(200, {"balance": 1}), Response(200, {})])
    c = Client(make_settings(dry_run=False, live_trading=True), transport=t,
               sleep=lambda s: None)
    c.account()
    c.place_order("36", "yes", "buy", 1, 0.5)
    assert t.calls[0]["headers"]["Authorization"] == "Bearer r"
    assert t.calls[1]["headers"]["Authorization"] == "Bearer e"


def test_client_does_not_expose_price_history():
    """price-history returns empty with coverage.complete=true. Must not be used."""
    assert not hasattr(Client, "price_history")


# ------------------------------------------------------------------ bulk ----

def test_prices_chunks_at_100_ids():
    t = FakeTransport([Response(200, {"data": [{"exchangeId": i} for i in range(100)]}),
                       Response(200, {"data": [{"exchangeId": i} for i in range(100, 150)]})])
    c = Client(make_settings(), transport=t, sleep=lambda s: None)
    out = c.prices([str(i) for i in range(150)])
    assert len(t.calls) == 2
    assert len(out) == 150


def test_prices_empty_input_makes_no_calls():
    t = FakeTransport([])
    c = Client(make_settings(), transport=t, sleep=lambda s: None)
    assert c.prices([]) == {}
    assert not t.calls
