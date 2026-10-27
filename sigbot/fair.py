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


# Alaska Senate and California Governor carry NO anchor under the three
# _PATTERNS above, and did so for the whole contest until this was found on
# 2026-10-27. Not a missing-match bug: both states use a top-four/top-two,
# candidate-centric primary system rather than a clean partisan ballot line,
# so Polymarket frames them per CANDIDATE ("Will Dan Sullivan win...") instead
# of per party, and no amount of regex tuning against the party-vs-party
# patterns will ever match that.
#
# Fixed by mapping each SIG party-side straight to its one, clearly dominant
# same-party candidate. Verified safe to trust before adding:
#   Alaska Senate:  Sullivan(R) 0.255 + Peltola(D) 0.745 = 1.000 exactly --
#     the race has in practice consolidated to these two, so treating it as a
#     clean two-outcome race (which devig_by_race requires to touch it) is
#     empirically justified, not assumed.
#   CA Governor:    SIG R ask 0.075 vs Hilton(R) 0.036 -> edge 0.039, ROC
#     4.2%, in-band and comparable to several already-held positions.
# Deliberately left out:
#   CA Governor D (exchange 850): Polymarket has no standalone "will Becerra
#     win" market, only 8 margin-banded sub-markets (e.g. "by 0%-10%"); summing
#     them is possible but not needed, since we only ever SELL the tail side
#     here and 850 is the favourite. Left unmapped rather than guessed at.
#   Alaska GOVERNOR: at least 9 named Republican-aligned candidates on
#     Polymarket with a visibly fragmented field -- no single one is a fair
#     stand-in for "the Republican Party," unlike the Senate race's clean
#     two-candidate consolidation. This approximation only holds where the
#     field actually has consolidated; forcing it where it has not would
#     manufacture an edge the same way devig_by_race already refuses to
#     invent probability for a known-incomplete outcome set.
#
# Second gap found the same day, same root cause one level deeper: the
# INDEPENDENT side of Nebraska Senate, Montana Senate and Rhode Island
# Governor carried no anchor either, because none of the three _PATTERNS
# handle Polymarket's "Will an independent win..." phrasing at all (they only
# ever match Democratic/Republican framings) -- unlike Alaska/California,
# this is a genuine pattern gap, not a structural one, but Polymarket DOES
# publish a clean, standalone market for each ("Will an independent win the
# Nebraska Senate race in 2026?" etc.), so the same hardcoded-token fix
# applies. Verified before trusting each:
#   Nebraska Senate I: SIG ask 0.315 vs anchor 0.28  -> edge 0.035, ROC 5.1%
#   Montana Senate I:  SIG ask 0.120 vs anchor 0.086 -> edge 0.035, ROC 3.9%
#   RI Governor I:     SIG ask 0.070 vs anchor 0.035 -> edge 0.035, ROC 3.8%
# All three races' R and D sides were already anchored via the normal pattern
# match (confirmed: RI Governor R is one of our largest existing holdings).
# Completing the I side means devig_by_race now sees all 3 known outcomes for
# each race instead of 2, so it switches from passing the pair through
# untouched to properly normalising all three -- a strictly more accurate
# fair value for the R/D sides too, not just a new tradeable I side.
#
# Token ids are Polymarket CLOB token ids, stable for the life of the market
# (verified directly via the Gamma API on 2026-10-27, not inferred).
_SPECIAL_CASE_TOKENS: dict[str, tuple[tuple[str, str, str], str]] = {
    # exchange_id -> (sig_key, polymarket_clob_token_id)
    "1067": (("SENATE", "ALASKA", "R"),
             "2618138322856109565904469085316346602627882727483900432328802655317079880335"),
    "1066": (("SENATE", "ALASKA", "D"),
             "72139607190315861034411702195742538105117960260100800877125381826122747504258"),
    "851": (("GOV", "CALIFORNIA", "R"),
            "62036777373156170213565171932095236744807107909020350504410807304822923031451"),
    "969": (("SENATE", "NEBRASKA", "I"),
            "47975366268282823322598946778919483335780002591367838795894307024076579116518"),
    "965": (("SENATE", "MONTANA", "I"),
            "29340710087203628054916881063653310634997647642374537159652441277893390730162"),
    "880": (("GOV", "RHODE ISLAND", "I"),
            "13165388174900569619328636459480727052834519645059869980549561071064022087971"),
}


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
    _apply_special_case_tokens(xw)
    return xw


def _apply_special_case_tokens(xw: Crosswalk) -> None:
    """
    Apply the known structural exceptions (see _SPECIAL_CASE_TOKENS) on top of
    the generic pattern match, not instead of it -- these are markets the
    three _PATTERNS can never match by construction, not ones the match failed
    on. Mutates `xw` in place; only touches an exchange the generic pass
    already recognised as a real SIG market (`key_by_exchange`), and only sets
    `token_by_exchange`, never overriding `key_by_exchange` itself.
    """
    for exch, (_k, token) in _SPECIAL_CASE_TOKENS.items():
        if exch in xw.key_by_exchange:          # the SIG market must exist
            xw.token_by_exchange[exch] = token


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
    """
    Turns external (Polymarket) prices into fair values for SIG exchanges.

    Deliberately NOT a blend with SIG's own price. The disagreement between the
    two venues is the entire signal; averaging them shrinks it.
    """

    def __init__(self, crosswalk: Crosswalk):
        self.xw = crosswalk

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

        Only a COMPLETE outcome set may be normalised. Three races -- Nebraska
        and Montana Senate, Rhode Island Governor -- carry a serious
        Independent, so P(R) + P(D) is genuinely less than 1 there. Forcing a
        partial set to sum to 1 is the complement assumption this codebase
        bans: with the Independent's mass redistributed, raw values of
        R=0.70/D=0.05 come back as 0.933/0.067, inventing 23 points of
        probability and a large fictitious edge.

        When outcomes are missing the values pass through untouched. Carrying a
        small overround is harmless; manufacturing probability is not.
        """
        groups: dict[tuple, dict[str, float]] = {}
        for ex, p in probs.items():
            k = self.xw.key_by_exchange.get(ex)
            if k is None:
                continue
            groups.setdefault((k[0], k[1]), {})[ex] = p
        # How many outcomes the race actually has, from the full SIG universe.
        known: dict[tuple, int] = {}
        for k in self.xw.key_by_exchange.values():
            known[(k[0], k[1])] = known.get((k[0], k[1]), 0) + 1
        out: dict[str, float] = {}
        for race_key, race in groups.items():
            if len(race) == known.get(race_key, len(race)):
                out.update(devig(race))
            else:
                out.update(race)
        return out

    def combine(self, books: dict[str, dict],
                clob_mids: dict[str, float]) -> dict[str, float]:
        """
        Final fair value per exchange: the external anchor, de-vigged.

        A fair value is produced ONLY where an external anchor exists. The
        previous version seeded the result with the venue's own microprice, so
        a Polymarket outage -- or simply one of the nine unmatched markets --
        silently produced a "fair value" derived from the very book we were
        about to trade against. That is not a neutral fallback: de-vigging
        moves the internal value away from its own touch whenever the separate
        R and D books do not sum to one, so it manufactures a relative-value
        signal out of nothing. Replaying our own tape with the external feed
        emptied still generated 33 orders, including a 63-lot sell of Alaska
        Senate D against a fair value computed entirely from Alaska Senate D.

        The anchor is also used undiluted. Blending it with SIG's own microprice
        is circular: the disagreement between the two venues IS the signal, and
        averaging them shrinks exactly the quantity being traded. research/
        METHODS.md states this directly -- "Do NOT ensemble with SIG's own live
        price - that is circular and erases the very edge we are trying to
        measure" -- and the 0.65 blend did it anyway, attenuating the
        favourite-longshot edge below the trading threshold in the tails where
        it was actually validated.
        """
        return self.devig_by_race(self.external(clob_mids))
