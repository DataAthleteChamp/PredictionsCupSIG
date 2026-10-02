"""
HTTP client for the Super Market API.

Three things this module exists to get right, because the venue punishes each:

1. **Rate limiting.** Measured: 3 concurrent workers are safe, 6 produce 429s,
   sustainable throughput ~38 req/min. A token bucket keeps us under.
2. **Idempotency.** Order placement REQUIRES a client-supplied key. A
   `502 ORDER_STATUS_UNKNOWN` may already have executed, so a retry must reuse
   the SAME key. Reusing a key with a changed payload returns 409.
3. **Retry policy.** Only a specific set of codes is safe to retry. Everything
   else indicates a problem a retry will not fix.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from .config import Settings

# Retry ONLY these. Per the API docs, other 4xx are real errors.
RETRYABLE_STATUS = {429, 500, 502, 503}
RETRYABLE_CODES = {
    "RATE_LIMITED",
    "TX_CONFLICT",
    "SERVICE_UNAVAILABLE",
    "ORDER_STATUS_UNKNOWN",
    "REQUEST_IN_FLIGHT",
    "INTERNAL_ERROR",
}


class ApiError(RuntimeError):
    def __init__(self, status: int, code: str, message: str, details: Any = None):
        super().__init__(f"{status} {code}: {message}")
        self.status = status
        self.code = code
        self.message = message
        self.details = details

    @property
    def retryable(self) -> bool:
        return self.status in RETRYABLE_STATUS or self.code in RETRYABLE_CODES


class DryRunBlocked(RuntimeError):
    """Raised when a mutating call is attempted without both live latches set."""


class TokenBucket:
    """Simple thread-safe token bucket. Blocks until a token is available."""

    def __init__(self, rate_per_min: float, burst: int | None = None):
        if rate_per_min <= 0:
            raise ValueError("rate_per_min must be positive")
        self.rate = rate_per_min / 60.0
        self.capacity = burst if burst is not None else max(1, int(rate_per_min / 6))
        self._tokens = float(self.capacity)
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def take(self, n: int = 1, now: Callable[[], float] = time.monotonic) -> float:
        """Consume n tokens, sleeping if necessary. Returns seconds waited."""
        waited = 0.0
        while True:
            with self._lock:
                t = now()
                self._tokens = min(self.capacity, self._tokens + (t - self._last) * self.rate)
                self._last = t
                if self._tokens >= n:
                    self._tokens -= n
                    return waited
                deficit = n - self._tokens
                sleep_for = deficit / self.rate
            time.sleep(sleep_for)
            waited += sleep_for


@dataclass
class Response:
    status: int
    body: Any


def _default_transport(method: str, url: str, headers: dict, body: bytes | None,
                       timeout: float) -> Response:
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return Response(r.status, json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            parsed = json.loads(raw) if raw else None
        except Exception:
            parsed = {"error": {"code": "UNPARSEABLE", "message": raw[:200].decode(errors="replace")}}
        return Response(e.code, parsed)


class Client:
    """
    Thin, explicit API client.

    `transport` is injectable so the retry/idempotency logic can be unit-tested
    without touching the network.
    """

    def __init__(self, settings: Settings, transport=_default_transport,
                 sleep: Callable[[float], None] = time.sleep):
        self.s = settings
        self._transport = transport
        self._sleep = sleep
        self._bucket = TokenBucket(settings.rate_limit_per_min)
        self.request_count = 0

    # ------------------------------------------------------------- plumbing --

    def _headers(self, key: str, json_body: bool) -> dict:
        h = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
        if json_body:
            h["Content-Type"] = "application/json"
        return h

    def _call(self, method: str, path: str, *, key: str, body: dict | None = None,
              max_tries: int = 5, timeout: float = 45.0) -> Any:
        payload = json.dumps(body).encode() if body is not None else None
        url = self.s.base_url + path
        delay = 0.2
        last: ApiError | None = None
        for attempt in range(max_tries):
            self._bucket.take()
            self.request_count += 1
            resp = self._transport(method, url, self._headers(key, body is not None),
                                   payload, timeout)
            if 200 <= resp.status < 300:
                return resp.body
            err = resp.body.get("error", {}) if isinstance(resp.body, dict) else {}
            exc = ApiError(resp.status, err.get("code", "UNKNOWN"),
                           err.get("message", ""), err.get("details"))
            if not exc.retryable or attempt == max_tries - 1:
                raise exc
            last = exc
            self._sleep(delay)
            delay = min(delay * 2, 8.0)
        raise last  # pragma: no cover

    # ----------------------------------------------------------------- reads --

    def get(self, path: str) -> Any:
        return self._call("GET", path, key=self.s.recon_key)

    def account(self) -> dict:
        return self.get("/account")

    def open_orders(self, limit: int = 100) -> list[dict]:
        return self.get(f"/orders?status=open&limit={limit}").get("data", [])

    def positions(self) -> dict:
        return self.get(f"/tournaments/{self.s.tournament_slug}/portfolio/positions")

    def fills(self, limit: int = 200, cursor: str | None = None) -> dict:
        p = f"/tournaments/{self.s.tournament_slug}/portfolio/fills?limit={limit}"
        if cursor:
            p += f"&cursor={cursor}"
        return self.get(p)

    def prices(self, exchange_ids: list[str]) -> dict[str, dict]:
        """Bulk quote snapshot. 100 ids per call -> the whole universe in 3 calls."""
        out: dict[str, dict] = {}
        for i in range(0, len(exchange_ids), 100):
            chunk = exchange_ids[i:i + 100]
            d = self.get(f"/exchanges/prices?ids={','.join(chunk)}"
                         f"&tournamentId={self.s.tournament_id}")
            for q in d.get("data", []):
                out[str(q["exchangeId"])] = q
        return out

    def orderbook(self, exchange_id: str, depth: int = 20) -> dict:
        return self.get(f"/exchanges/{exchange_id}/orderbook"
                        f"?tournamentId={self.s.tournament_id}&depth={depth}")

    def trades(self, exchange_id: str, limit: int = 200, since: str | None = None) -> list[dict]:
        p = (f"/exchanges/{exchange_id}/trades"
             f"?tournamentId={self.s.tournament_id}&limit={limit}")
        if since:
            p += f"&from={since}"
        return self.get(p).get("data", [])

    # NOTE: price-history is deliberately NOT exposed. It returns empty data while
    # reporting coverage.complete=true. Build series from trades() instead.

    # ---------------------------------------------------------------- writes --

    def _require_live(self) -> None:
        if not self.s.trading_enabled:
            raise DryRunBlocked(
                "refusing to mutate: set DRY_RUN=false AND LIVE_TRADING=true")
        if not self.s.exec_key:
            raise DryRunBlocked("SIG_EXEC_KEY is not set")

    def place_order(self, exchange_id: str, side: str, action: str, quantity: int,
                    price: float | None, idempotency_key: str | None = None) -> dict:
        """
        Place one order. `quantity` is always positive; `side` carries direction.
        Omit `price` for a market order.

        The idempotency key is generated once here if not supplied. On a retryable
        failure the SAME key is reused by _call, which is what makes a 502 safe.
        """
        self._require_live()
        body: dict[str, Any] = {
            "idempotencyKey": idempotency_key or f"sigbot-{uuid.uuid4()}",
            "exchangeId": str(exchange_id),
            "side": side,
            "action": action,
            "quantity": int(quantity),
            "tournamentId": self.s.tournament_id,
        }
        if price is not None:
            body["price"] = price
        return self._call("POST", "/orders", key=self.s.exec_key, body=body)

    def place_batch(self, orders: list[dict],
                    idempotency_key: str | None = None) -> dict:
        """
        Place up to 50 orders in ONE request.

        This matters enormously for cycle latency: placing 229 orders singly costs
        229 requests (~7.9 min at our rate limit), by which time the quotes that
        produced them are long stale — measured dislocation reversion is ~2 min
        median. Batched, the same 229 orders cost 5 requests.

        The venue places them serially under a time budget and may return 207
        (partial) or 503 part-way, keeping orders already placed. Retrying with
        the SAME key resumes rather than duplicating.

        `orders` items are dicts of exchangeId/side/action/quantity/price.
        """
        self._require_live()
        if not orders:
            return {"results": []}
        if len(orders) > 50:
            raise ValueError("batch limit is 50 orders")
        body = {
            "idempotencyKey": idempotency_key or f"sigbot-batch-{uuid.uuid4()}",
            "orders": [{**o, "tournamentId": self.s.tournament_id} for o in orders],
        }
        return self._call("POST", "/orders/batch", key=self.s.exec_key, body=body)

    def cancel_order(self, order_id: int) -> Any:
        self._require_live()
        return self._call("DELETE", f"/orders/{order_id}", key=self.s.exec_key)

    def cancel_all(self, exchange_id: str | None = None,
                   market_id: str | None = None) -> Any:
        """
        Scoped sweep. The venue documents this as the correct way to re-quote —
        never cancel order-by-order.

        exchangeId and marketId are mutually exclusive (400 if both supplied).
        """
        self._require_live()
        if exchange_id and market_id:
            raise ValueError("exchangeId and marketId are mutually exclusive")
        body: dict[str, Any] = {"tournamentId": self.s.tournament_id}
        if exchange_id:
            body["exchangeId"] = str(exchange_id)
        if market_id:
            body["marketId"] = str(market_id)
        return self._call("POST", "/orders/cancel-all", key=self.s.exec_key, body=body)
