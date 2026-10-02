"""
Fair value estimation.

Three independent sources, combined:

1. **Microprice** from our own book — Stoikov's weighted mid. Cheap, always
   available, but it only tells us what this venue thinks.
2. **Polymarket** — real money, deep liquidity, well calibrated in aggregate.
   This is the external anchor that tells us when the venue is wrong.
3. **De-vigging** — R and D are separate books here, so their prices do not sum
   to 1. Normalising within a race removes the overround.

Critical implementation rule: **read prices from the CLOB, never from Gamma.**
Gamma returns `cache-control: max-age=300`, so it can legitimately serve data
five minutes stale. Gamma is for discovery and metadata only.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from .algos import devig, microprice

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"

# Polymarket question patterns that map onto our market titles.
_PATTERNS = [
    (re.compile(r"^Will the (Democratic|Republican) Party control the (Senate|House) "
                r"after the 2026", re.I),
     lambda m: ("CONTROL", m.group(2).upper(), m.group(1)[0].upper())),
    (re.compile(r"^Will the (Democrats|Republicans) win the (.+?) "
                r"(Senate|governor|gubernatorial) race in 2026\?$", re.I),
     lambda m: ("SENATE" if m.group(3).lower() == "senate" else "GOV",
                m.group(2).upper(), m.group(1)[0].upper())),
    (re.compile(r"^Will the (Democratic|Republican) Party win the "
                r"([A-Z]{2})-(\d{1,2}) House seat\?$"),
     lambda m: ("HOUSE", f"{m.group(2)}-{int(m.group(3)):02d}", m.group(1)[0].upper())),
]

_SIG = re.compile(r"^Will the (\w+) Party win the (.+)\?$")


def sig_key(title: str) -> tuple[str, str, str] | None:
    """Normalise one of our market titles into (office, locus, party)."""
    m = _SIG.match(title or "")
    if not m:
        return None
    party = {"Republican": "R", "Democratic": "D", "Independent": "I"}.get(m.group(1))
    if party is None:
        return None
    race = m.group(2)
    if race == "U.S. Senate":
        return ("CONTROL", "SENATE", party)
    if race == "U.S. House":
        return ("CONTROL", "HOUSE", party)
    if race.endswith(" Senate"):
        return ("SENATE", race[:-7].strip().upper(), party)
    if race.endswith(" Governor"):
        return ("GOV", race[:-9].strip().upper(), party)
    if re.match(r"^[A-Z]{2}-\d+ House race$", race):
        return ("HOUSE", race.split(" ")[0].upper(), party)
    return None


def poly_key(question: str) -> tuple[str, str, str] | None:
    for pat, fn in _PATTERNS:
        m = pat.match(question or "")
        if m:
            return fn(m)
    return None


def _fetch(url: str, timeout: float = 30.0):
    req = urllib.request.Request(url, headers={"User-Agent": "sigbot/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


@dataclass
class Crosswalk:
    """Maps our exchange ids to Polymarket CLOB token ids."""

    token_by_exchange: dict[str, str] = field(default_factory=dict)
    key_by_exchange: dict[str, tuple] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.token_by_exchange)

    def save(self, path: str) -> None:
        with open(path, "w") as f:
            json.dump({"token_by_exchange": self.token_by_exchange,
                       "key_by_exchange": {k: list(v)
                                           for k, v in self.key_by_exchange.items()}}, f)

    @classmethod
    def load(cls, path: str) -> "Crosswalk":
        d = json.load(open(path))
        return cls(token_by_exchange=d["token_by_exchange"],
                   key_by_exchange={k: tuple(v) for k, v in d["key_by_exchange"].items()})


def build_crosswalk(sig_markets: list[dict], max_pages: int = 12) -> Crosswalk:
    """
    One-off discovery. Gamma is used ONLY for metadata (question text and the
    CLOB token ids); prices come from the CLOB.

    `clobTokenIds` arrives as a JSON-encoded string, so it needs decoding twice.
    Index 0 is the YES token.
    """
    poly: dict[tuple, str] = {}
    for page in range(max_pages):
        url = (f"{GAMMA}/events?tag_slug=midterms&closed=false"
               f"&limit=100&offset={page * 100}")
        try:
            events = _fetch(url)
        except Exception:
            break
        if not events:
            break
        for ev in events:
            for mk in ev.get("markets", []):
                if mk.get("closed") or not mk.get("active"):
                    continue
                k = poly_key(mk.get("question", ""))
                if k is None or k in poly:
                    continue
                try:
                    tokens = json.loads(mk.get("clobTokenIds") or "[]")
                except Exception:
                    continue
                if tokens:
                    poly[k] = tokens[0]          # index 0 == YES
    xw = Crosswalk()
    for m in sig_markets:
        exch = (m.get("exchanges") or [{}])[0].get("id")
        k = sig_key(m.get("title", ""))
        if exch and k:
            xw.key_by_exchange[str(exch)] = k
            if k in poly:
                xw.token_by_exchange[str(exch)] = poly[k]
    return xw


def clob_midpoints(token_ids: list[str], chunk: int = 50,
                   budget_seconds: float = 25.0,
                   per_request_timeout: float = 4.0) -> dict[str, float]:
    """
    Live midpoints from the CLOB. Never Gamma — Gamma is edge-cached for 300s.

    Bounded by a wall-clock budget. Previously this made one sequential request
    per token with a 30s timeout each; at 228 tokens a degraded Polymarket could
    stall the trading loop for over an hour without raising anything, and every
    quote the cycle then acted on was correspondingly stale.
    """
    import time as _time
    out: dict[str, float] = {}
    deadline = _time.monotonic() + budget_seconds
    for tid in token_ids:
        if _time.monotonic() > deadline:
            break
        try:
            d = _fetch(f"{CLOB}/midpoint?token_id={urllib.parse.quote(tid)}",
                       timeout=per_request_timeout)
            if d and d.get("mid") is not None:
                out[tid] = float(d["mid"])
        except Exception:
            continue
    return out


class FairValueEngine:
    """Blends the venue's own microprice with the external anchor."""

    def __init__(self, crosswalk: Crosswalk, anchor_weight: float = 0.65):
        if not 0.0 <= anchor_weight <= 1.0:
            raise ValueError("anchor_weight must be in [0, 1]")
        self.xw = crosswalk
        self.w = anchor_weight

    def internal(self, books: dict[str, dict]) -> dict[str, float]:
        """Microprice per exchange from top-of-book depth."""
        out = {}
        for ex, b in books.items():
            bid, ask = b.get("bestBid"), b.get("bestAsk")
            if bid is None or ask is None:
                continue
            out[ex] = microprice(bid, ask, b.get("bidSize", 1.0) or 1.0,
                                 b.get("askSize", 1.0) or 1.0)
        return out

    def external(self, mids: dict[str, float]) -> dict[str, float]:
        """Map CLOB midpoints back onto our exchange ids."""
        return {ex: mids[tok] for ex, tok in self.xw.token_by_exchange.items()
                if tok in mids}

    def devig_by_race(self, probs: dict[str, float]) -> dict[str, float]:
        """
        Normalise each race so its outcomes sum to 1. R and D are separate books
        here, so raw prices carry an overround that must be removed before they
        can be compared to anything.
        """
        groups: dict[tuple, dict[str, float]] = {}
        for ex, p in probs.items():
            k = self.xw.key_by_exchange.get(ex)
            if k is None:
                continue
            groups.setdefault((k[0], k[1]), {})[ex] = p
        out: dict[str, float] = {}
        for race in groups.values():
            out.update(devig(race))
        return out

    def combine(self, books: dict[str, dict],
                clob_mids: dict[str, float]) -> dict[str, float]:
        """
        Final fair value per exchange.

        Where we have an external anchor, blend it with the internal microprice.
        Where we do not, fall back to the internal view alone — which yields no
        relative-value signal, correctly, since there is nothing to disagree with.
        """
        internal = self.devig_by_race(self.internal(books))
        external = self.devig_by_race(self.external(clob_mids))
        out = dict(internal)
        for ex, anchor in external.items():
            own = internal.get(ex)
            out[ex] = anchor if own is None else self.w * anchor + (1 - self.w) * own
        return out
