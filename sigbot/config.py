"""Configuration. All secrets come from the environment, never from source."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

TOURNAMENT_SLUG = "midterm-elections"
TOURNAMENT_ID = "bda92870-621e-47b0-bc3c-3602c5c26f55"

TICK = 0.005
MIN_PRICE = 0.005
MAX_PRICE = 0.995
START_BALANCE = 100_000.0

# Trading closes 2026-11-04 12:00 ET. Positions settle weeks later.
TRADING_CLOSE_UTC = "2026-11-04T17:00:00+00:00"


def _f(name: str, default: float) -> float:
    """
    Read a float from the environment.

    An ABSENT variable falls back to the default; a PRESENT but malformed one
    raises. Silently swallowing `SIG_MAX_DEPLOYED_FRACTION=0.O5` and returning
    the 0.90 default is precisely how this bot once ran for hours on a cap
    nobody intended. A typo in a risk limit must stop the process, not quietly
    widen it.
    """
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError as e:
        raise RuntimeError(
            f"{name}={raw!r} is not a number; refusing to fall back to "
            f"{default} for a risk limit") from e


@dataclass(frozen=True)
class RiskLimits:
    """Hard caps. The allocator enforces these; strategies cannot override them."""

    max_deployed_fraction: float = 0.90      # never commit the whole stack
    # Must stay above SettlementConfig.per_market_fraction, or the strategy's
    # own sizing is vetoed by the risk manager on every top-up and the book
    # silently stops concentrating. This default was 0.05 while the strategy
    # asked for 0.08, so the code was correct only when .env happened to
    # override it -- the same config/behaviour divergence as the deployment cap
    # that once ran at 0.90 while every log line said 5%.
    max_per_market_fraction: float = 0.09
    max_position_shares: int = 50_000
    max_drawdown_fraction: float = 0.20      # kill switch
    # Measured: both tail buckets markout negative. Do not buy inside these.
    no_buy_below: float = 0.15
    no_buy_above: float = 0.95

    def __post_init__(self) -> None:
        if not 0 < self.max_deployed_fraction <= 1:
            raise ValueError("max_deployed_fraction must be in (0, 1]")
        if not 0 < self.max_per_market_fraction <= 1:
            raise ValueError("max_per_market_fraction must be in (0, 1]")
        if not 0 <= self.no_buy_below < self.no_buy_above <= 1:
            raise ValueError("no-buy band is inverted")


@dataclass(frozen=True)
class StrategyBudget:
    """
    Barbell allocation. Fractions of EQUITY, must sum to 1.

    A high-Sharpe core (ladder + relvalue) funds and protects a small convex
    sleeve. This is the Friedman-Savage "safe layer + aspirational layer" /
    Black-Perold CPPI structure the literature recommends when the objective is
    P(reaching a goal) rather than expected wealth.

    The core alone cannot reach a podium ~6x away; the sleeve alone would be
    paying the longshot premium with the whole stack.

    Reweighted 2026-10-08 around the settlement book. The rules decide the
    competition on balance AFTER resolution, the anchor disagrees with the
    venue on 122 of 228 markets, and the measured capacity of that trade (37.5M
    shares resting on bids above fair) exceeds our capital by ~300x. An edge
    that large and that well evidenced should hold the majority of the book,
    and the grind that earned +44/day should not.

    `reserve` is no longer a risk buffer -- the settlement book's loss is
    bounded by its own collateral and the venue cannot margin-call us -- but an
    OPERATING buffer. At literally zero free cash the ladder cannot post a bid
    and the pair strategy cannot lift a leg, so the bot stops functioning
    before it stops being solvent.
    """

    settlement: float = 0.91      # held-to-resolution convergence book
    ladder: float = 0.04
    relvalue: float = 0.01
    sleeve: float = 0.01          # aspirational layer
    reserve: float = 0.03         # operating buffer, never deployed

    @property
    def core(self) -> float:
        return self.ladder + self.relvalue + self.settlement

    def validate(self) -> None:
        total = (self.settlement + self.ladder + self.relvalue
                 + self.sleeve + self.reserve)
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"budgets must sum to 1.0, got {total}")
        if self.sleeve > self.core:
            raise ValueError("sleeve must not exceed the core it is funded by")


@dataclass(frozen=True)
class Settings:
    base_url: str
    recon_key: str
    exec_key: str
    tournament_id: str = TOURNAMENT_ID
    tournament_slug: str = TOURNAMENT_SLUG

    # Two independent latches. BOTH must be set for a live order to leave the process.
    dry_run: bool = True
    live_trading: bool = False

    rate_limit_per_min: float = 30.0         # measured safe ~38/min; stay under
    max_concurrency: int = 3                 # 6 workers produced 429s
    # Bounds how stale the last order in a cycle can be. Measured dislocation
    # reversion is ~2 min median, so a cycle must stay well inside that.
    max_orders_per_cycle: int = 150

    limits: RiskLimits = field(default_factory=RiskLimits)
    budgets: StrategyBudget = field(default_factory=StrategyBudget)

    @property
    def trading_enabled(self) -> bool:
        """Live orders require dry_run off AND live_trading on."""
        return (not self.dry_run) and self.live_trading

    @classmethod
    def from_env(cls) -> "Settings":
        base = os.environ.get("SIG_BASE_URL", "").rstrip("/")
        recon = os.environ.get("SIG_RECON_KEY", "")
        ex = os.environ.get("SIG_EXEC_KEY", "")
        if not base:
            raise RuntimeError("SIG_BASE_URL is not set")
        if not recon:
            raise RuntimeError("SIG_RECON_KEY is not set")
        # Deployment cap is env-overridable so a live validation run can be
        # hard-limited well below the normal ceiling.
        limits = RiskLimits(
            max_deployed_fraction=_f("SIG_MAX_DEPLOYED_FRACTION", 0.90),
            max_per_market_fraction=_f("SIG_MAX_PER_MARKET_FRACTION", 0.05),
        )
        s = cls(
            base_url=base,
            recon_key=recon,
            exec_key=ex,
            dry_run=os.environ.get("DRY_RUN", "true").lower() != "false",
            live_trading=os.environ.get("LIVE_TRADING", "false").lower() == "true",
            rate_limit_per_min=_f("SIG_RATE_LIMIT_PER_MIN", 30.0),
            max_orders_per_cycle=int(_f("SIG_MAX_ORDERS_PER_CYCLE", 150)),
            limits=limits,
        )
        s.budgets.validate()
        return s

    def risk_banner(self) -> str:
        """
        The effective caps, rendered for the startup log.

        A deployment cap once existed only as a shell export in the terminal
        that launched the bot. The process restarted without it and ran for
        hours on the 0.90 default while every log line and every mental model
        said 5%. Nothing crashed, because the per-market and per-strategy
        budgets bound first -- which is precisely why it went unnoticed.

        Printing the resolved numbers makes a missing override visible in the
        first line of output rather than discoverable only by reading config.
        """
        return (f"caps: deployed<={self.limits.max_deployed_fraction:.1%} "
                f"per_market<={self.limits.max_per_market_fraction:.1%} "
                f"budgets(settlement={self.budgets.settlement:.0%},"
                f"ladder={self.budgets.ladder:.0%},"
                f"relvalue={self.budgets.relvalue:.0%},"
                f"sleeve={self.budgets.sleeve:.0%},"
                f"reserve={self.budgets.reserve:.0%}) "
                f"max_deployable_by_budget={self.max_deployable_fraction:.1%}")

    @property
    def max_deployable_fraction(self) -> float:
        """
        The binding cap: strategy budgets and the deployment limit are two
        independent ceilings, and the lower one is what actually applies.
        """
        return min(self.limits.max_deployed_fraction, self.budgets.core
                   + self.budgets.sleeve)


# Settlement-hold policy. One definition, because every strategy must agree:
# ExitStrategy decides not to close these, and the opening strategies must not
# trade into them. When only ExitStrategy knew, Ladder bought back a protected
# short and opened the opposite exposure in the same cycle.
SETTLEMENT_HOLD_EDGE = 0.02        # 4 ticks, well above the ~0.4-tick grind edge
# Raised from 0.10 with the settlement book. This budget decides how much of
# the portfolio ExitStrategy is forbidden to recycle and Ladder is forbidden to
# trade into. While it was 0.10 the hold rule could only cover a tenth of
# equity, which was ample for an accidental 111-share tail book and useless for
# a deliberate one: everything above the budget would have been handed straight
# back to the exit strategy for a sub-tick profit. It must cover the settlement
# budget, or the two rules fight and the exit wins.
SETTLEMENT_HOLD_BUDGET = 0.95      # fraction of equity; must exceed budgets.settlement

# Anchor-feed health. Below this fraction of quoted markets carrying a fair
# value, the fetch is treated as DEGRADED rather than as news.
#
# Measured 2026-10-08: 171 of 172 cycles returned 228 of 228 anchors, one
# returned 117. That one cycle made six settlement shorts look like positions
# whose edge had vanished -- ExitStrategy went from 2 orders to 12, the
# kill-switch exemption dropped from 21 holds to 15, and the planner cancelled
# 52 of 54 resting orders and replaced 50 of them on the next cycle.
#
# Coverage is bimodal (100% or broken), so the threshold only has to separate
# those two modes; 0.90 sits well clear of normal jitter (226/228 = 99%) and
# well above the observed failure (117/228 = 51%).
MIN_ANCHOR_COVERAGE = 0.90

# How many consecutive degraded cycles to sit out before planning anyway.
#
# Skipping is the right response to bad data, but skipping FOREVER leaves
# resting orders unmanaged while the market moves away from them. Three cycles
# is about 15 minutes: long enough to ride out a transient, short enough that
# stale quotes cannot be adversely selected for long.
MAX_DEGRADED_SKIPS = 3

# Hours before TRADING_CLOSE_UTC at which the GRIND strategies stop opening.
#
# The grind (ladder, relvalue, pair, sleeve) earns a sub-tick edge by round
# -tripping inventory over minutes. A position it opens shortly before the
# close cannot be round-tripped: it stops being a scratch trade and becomes an
# unhedged bet on the election, at a price chosen by a strategy that was never
# asked that question.
#
# The settlement book is deliberately exempt. Selling an overpriced tail an
# hour before resolution is the BEST version of that trade, not the worst --
# there is no time left for the venue to move against the anchor.
GRIND_STOP_HOURS_BEFORE_CLOSE = 6.0
