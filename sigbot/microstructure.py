"""
Market microstructure measurement.

Three standard results, each fitted to our own data rather than assumed:

1. **Huang-Stoll spread decomposition.** Splits what we capture at the moment
   of a fill from what we actually keep. A passive quoter earns the effective
   half-spread and then hands some of it back to whoever picked them off; the
   difference is adverse selection. This says whether our market making is
   genuinely paid for providing liquidity, or merely slow.

2. **Cont-de Larrard queue decay.** Fill probability falls geometrically with
   depth, `p(k) = r^k`, from a race between two Poisson clocks (market orders
   consuming the queue vs. price moves abandoning it). One parameter, fitted
   from depths we measured, which then predicts depths we never tested.

3. **Kyle's lambda.** Price impact per unit of signed volume.

Every function here takes YES-space mids and `side` separately, and converts
frames in exactly one place: `_value_in_fill_frame`. A `no` fill's price is
quoted in NO space while mids are always YES space, and conflating the two
previously inflated our measured edge seventeen-fold.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .algos import to_yes_frame


def _value_in_fill_frame(yes_mid: float, side: str) -> float:
    """Value of one share, expressed in the frame its price was quoted in."""
    return yes_mid if side == "yes" else (1.0 - yes_mid)


def quote_depth_ticks(side: str, action: str, price: float,
                      best_bid: float, best_ask: float,
                      tick: float = 0.005) -> float:
    """
    How far an order rests on the passive side of the mid, in ticks.

    Positive is passive (behind the mid), negative means the order is through
    the mid and would trade immediately. Frame conversion is handled, so a NO
    order may be passed exactly as the venue reports it.
    """
    yes_action, yes_price = to_yes_frame(side, action, price)
    mid = (best_bid + best_ask) / 2.0
    signed = (mid - yes_price) if yes_action == "buy" else (yes_price - mid)
    return signed / tick


def crosses_book(side: str, action: str, price: float,
                 best_bid: float, best_ask: float) -> bool:
    """True if the order would take liquidity rather than post it."""
    yes_action, yes_price = to_yes_frame(side, action, price)
    return (yes_price >= best_ask) if yes_action == "buy" else (yes_price <= best_bid)


# ----------------------------------------------- Huang-Stoll decomposition --

@dataclass(frozen=True)
class SpreadDecomposition:
    n: int
    effective: float          # half-spread captured at the fill
    realized: float           # half-spread still ours at horizon (== markout)
    adverse_selection: float  # effective - realized
    retention: float          # realized / effective

    def __str__(self) -> str:
        return (f"n={self.n} effective={self.effective:+.5f} "
                f"realized={self.realized:+.5f} "
                f"adverse={self.adverse_selection:+.5f} "
                f"retention={self.retention:.1%}")


def decompose_fill(fill_price: float, mid_at_fill: float, mid_later: float,
                   side: str = "yes", action: str = "buy") -> tuple[float, float]:
    """
    Return (effective_half_spread, realized_half_spread) for one passive fill.

    As the passive side, buying below the mid is the edge we capture:

        effective = value(mid_at_fill) - price      [buy]
        realized  = value(mid_later)  - price       [buy]

    and the difference, `effective - realized`, is what the mid moving against
    us took back. Selling is the mirror image. Note that `realized` is exactly
    the markout, so this decomposition explains a markout rather than
    replacing it.
    """
    v0 = _value_in_fill_frame(mid_at_fill, side)
    v1 = _value_in_fill_frame(mid_later, side)
    if action == "buy":
        return v0 - fill_price, v1 - fill_price
    return fill_price - v0, fill_price - v1


def decompose(fills) -> SpreadDecomposition:
    """
    Aggregate `decompose_fill` over an iterable of
    (fill_price, mid_at_fill, mid_later, side, action) tuples.
    """
    eff, real = [], []
    for f in fills:
        price, m0, m1 = f[0], f[1], f[2]
        side = f[3] if len(f) > 3 else "yes"
        action = f[4] if len(f) > 4 else "buy"
        e, r = decompose_fill(price, m0, m1, side, action)
        eff.append(e)
        real.append(r)
    if not eff:
        return SpreadDecomposition(0, 0.0, 0.0, 0.0, 0.0)
    e = float(np.mean(eff))
    r = float(np.mean(real))
    return SpreadDecomposition(
        n=len(eff), effective=e, realized=r, adverse_selection=e - r,
        retention=(r / e) if e != 0 else 0.0,
    )


# -------------------------------------------------- Cont-de Larrard queue --

@dataclass(frozen=True)
class QueueModel:
    base: float               # fill rate at depth 1, per order-hour
    ratio: float              # geometric decay per tick, mu/(mu+theta)

    def fill_rate(self, depth_ticks: int) -> float:
        """Expected fills per order-hour at `depth_ticks` from the touch."""
        d = max(1, int(depth_ticks))
        return self.base * self.ratio ** (d - 1)

    @property
    def mu_over_theta(self) -> float:
        """
        Consumption rate relative to price-move rate. r = mu/(mu+theta), so
        mu/theta = r/(1-r). Reported because it is the falsifiable claim: it
        should be roughly stable across depths if the model holds.
        """
        if not 0 < self.ratio < 1:
            return float("inf")
        return self.ratio / (1.0 - self.ratio)


def fit_queue_decay(observations) -> QueueModel:
    """
    Fit `rate(k) = base * r^(k-1)` by least squares in log space.

    `observations` is an iterable of (depth_ticks, fills_per_order_hour) with
    strictly positive rates. Two points suffice; more let the geometric
    assumption itself be checked rather than imposed.
    """
    pts = [(int(d), float(v)) for d, v in observations if v > 0 and d >= 1]
    if len(pts) < 2:
        raise ValueError("need at least two positive observations")
    x = np.array([d - 1 for d, _ in pts], dtype=float)
    y = np.log(np.array([v for _, v in pts], dtype=float))
    slope, intercept = np.polyfit(x, y, 1)
    return QueueModel(base=float(math.exp(intercept)),
                      ratio=float(math.exp(slope)))


# --------------------------------------------------------- Kyle's lambda ---

def kyle_lambda(signed_volume, price_changes) -> float:
    """
    OLS slope of price change on signed volume: dP = lambda * Q.

    Units are price per share. Higher lambda means a thinner book, so the same
    size moves the market further and passive quotes must sit deeper.
    """
    q = np.asarray(list(signed_volume), dtype=float)
    dp = np.asarray(list(price_changes), dtype=float)
    if len(q) < 2 or len(q) != len(dp):
        return float("nan")
    denom = float(np.dot(q, q))
    if denom <= 0:
        return float("nan")
    return float(np.dot(q, dp) / denom)


# --------------------------------------------- safety-first (Roy/Kataoka) --

def safety_first_ratio(expected_wealth: float, sd_wealth: float,
                       target: float) -> float:
    """
    Roy's criterion: maximising P(W >= b) is, under a location-scale
    approximation, maximising (E[W] - b) / sd(W).

    This replaces the Sharpe ratio when the objective is clearing a threshold
    rather than accumulating return. The two disagree in a way that matters
    here: when E[W] < b, the ratio is negative and is *increased* by more
    variance, which is exactly the barbell conclusion and the opposite of what
    Sharpe would advise.

    The Gaussian shortcut is least accurate for the lumpy, concentrated digital
    books that generate variance most efficiently -- for those, estimate
    P(W >= b) directly by Monte Carlo (see evaluate.prob_top_k). The
    probability form of Roy's criterion remains exact; only this closed form
    does not.
    """
    if sd_wealth <= 0:
        return math.inf if expected_wealth >= target else -math.inf
    return (expected_wealth - target) / sd_wealth


def prefers_more_variance(expected_wealth: float, target: float) -> bool:
    """
    True when adding variance raises P(W >= target).

    d/d(sigma) of (E-b)/sigma is -(E-b)/sigma^2, so the ratio improves with
    variance precisely when E[W] < b -- when we are behind the target. This is
    the formal statement of "bold play when behind, de-risk once ahead".
    """
    return expected_wealth < target
