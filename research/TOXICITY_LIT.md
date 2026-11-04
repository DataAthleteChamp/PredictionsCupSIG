# Detecting Informed / Distressed / Panic Order Flow from Top-of-Book + Trade Tape — Research Findings

**Question:** With ~9 days left before the Nov 4 venue lock, can the ladder (passive market-making across ~80 markets) legitimately detect "toxic" or panic/capitulation order flow from public order-book + trade-tape data alone, and should it respond by widening/pulling back, or by leaning in (posting more aggressively on the side being dumped)? What is actually computable from this venue's real data (verified against the live schema, not assumed), and what's the simplest robust implementation?

**Bottom line:** The literature gives a clean, mechanism-level answer: **adverse selection (informed, permanent-impact flow) says widen/retreat; compensated liquidity provision (transient, non-informational imbalance) says lean in** — and these are not in tension, they are different regimes of the *same* taxonomy (Glosten-Milgrom vs. Grossman-Miller/Nagel). The deciding variable is whether price impact is **permanent or transient**, which is exactly what your own markout/decay-curve machinery (`sigbot/microstructure.py`) already measures — this report's main contribution is a concrete design for conditioning that existing measurement on a real-time flow-toxicity flag, plus three verified, venue-specific data facts that change what's actually computable here relative to the generic HFT-equities literature this field is built on. Two of the three facts are good news: your trade tape's `side` field is **ground-truth signed order flow**, not an inferred classification (verified empirically below), which eliminates an entire layer of the literature (Lee-Ready, tick rule, BVC) you'd otherwise need. The third is a constraint: your bulk quote feed has **no size field at all** (confirmed from the OpenAPI schema and your own `Quote` dataclass, where `bid_size`/`ask_size` are always `0.0` in the live loop), so classical order-flow-imbalance (OFI) and microprice/imbalance — already implemented in `algos.py` — cannot fire from your primary live feed. They *can* fire from a separate, already-documented depth endpoint, but only economically for a small, adaptively-selected watchlist, not all 80 markets every cycle.

---

## 0. Your actual data, verified (not assumed)

This section exists because every formula below is only as useful as its fit to what you actually have, and three non-obvious things are true of your specific venue that are not true of the generic microstructure literature.

**0.1 The bulk quote feed has no size, confirmed at the schema level.** `research/collector.py`'s `quote` table (`ts, exchange_id, last, bid, ask, spread`) mirrors the `BulkExchangePrice` schema in `sig_openapi.json` exactly: `exchangeId, marketId, option, latestPrice, bestBid, bestAsk, spread` — no quantity field exists on this endpoint at all. `sigbot/strategies/base.py`'s `Quote` dataclass has `bid_size: float = 0.0` and `ask_size: float = 0.0`, but `sigbot/runner.py:376` constructs every `Quote` from exactly this bulk endpoint (`Quote(ex, q.get("bestBid"), q.get("bestAsk"))`), so these fields are **structurally always zero** in the live loop. `sigbot/algos.py`'s `microprice()` and `imbalance()` functions, which take `bid_size`/`ask_size` as arguments, are consequently dead code against live data today — not broken, just never fed real inputs. **[own data finding, verified via schema + source read]**

**0.2 Real depth exists, but on a different, per-exchange endpoint.** The schema also defines `CombinedOrderbookExchange` (`bids`/`asks` arrays of `OrderbookLevel{price, quantity}`) and `TournamentExchangeWithOrderbook` — genuine L2 depth, confirming your own `sig_orderbook_depth.csv`/`sig_wall_levels.csv` research snapshots came from this endpoint. It is called per-exchange-id, not in the 100-at-a-time batch the bulk price feed allows, so polling it for all ~80 markets every cycle at your ~38 req/min budget is not viable — but polling it for a handful of *flagged* markets is (§4.4). **[own data finding]**

**3. Your trade tape's `side` field is ground-truth signed flow, not an inferred label — and I verified this, because the schema's own field description looked initially inconsistent with your project's hard-won NO-space bug history.** `ExchangeTrade.side` is documented as `"Whether the fill happened in YES or NO space"` (enum `YES`/`NO`), and `price` is documented as `"YES-normalized fill price"`. Your own `sigbot/microstructure.py` docstring records a real, test-caught bug where a *different* price field (fill/order prices in your own position accounting) was **not** YES-normalized for NO-side fills (the NO@0.945/YES-mid@0.0475 example). I checked whether the same problem applies to the public trade tape by querying `research/data/tape.db` directly: averaging YES-side vs. NO-side trade prices **per exchange_id** across 15 liquid markets shows them tracking each other almost exactly (e.g., exchange 1000: avg YES=0.892, avg NO=0.925; exchange 1005: avg YES=0.060, avg NO=0.063) — **not** complementary (`1 − avg_yes`), which is what you'd see if NO prices were quoted in NO-space. This confirms the schema's claim is correct for *this* endpoint specifically: **the public trade tape's `price` is already YES-normalized regardless of `side`, so `side` is a clean, already-known, ground-truth buy/sell-direction label** (`side="YES"` ⇒ someone bought YES ⇒ +1 YES-direction pressure; `side="NO"` ⇒ someone bought NO ⇒ economically sold YES ⇒ −1). This is a materially better starting point than the general literature assumes: **you do not need Lee-Ready, the tick rule, or Bulk Volume Classification at all** — every paper below that spends effort on trade-classification error is solving a problem your venue's own matching engine has already solved and published for you. Treat this as verified against your own data, not asserted from the schema text alone, precisely because the schema's wording has been wrong before on this exact class of issue. **[own data finding, empirically verified this session]**

---

## 1. Standard metrics for informed/urgent flow — computability audit [Q1]

| Metric | What it needs | Computable from your data? |
|---|---|---|
| **Signed trade-flow imbalance** (native `side`) | trade tape only | **Yes — and better than the literature's default, since `side` is ground truth, not inferred** |
| **VPIN** (volume-bucketed \|buy−sell\|) | trade tape + a volume clock | **Yes**, and simpler than the textbook version (§4.2) because you skip BVC entirely |
| **Kyle's λ** (price impact per signed volume) | mid-price series + signed volume | **Yes** — already implemented in `sigbot/microstructure.py::kyle_lambda`, just needs a proper rolling-window driver (§4.3) |
| **PIN** (structural, MLE-fitted) | buy/sell trade *counts* per day, enough trades to identify 4 parameters | **Weak** — your per-market daily trade counts are almost certainly too thin for a stable 4-parameter MLE (see §1.4 caveat) |
| **Order Flow Imbalance (OFI)**, Cont-Kukanov-Stoikov | best bid/ask **price and size** at each book event | **No, not from the bulk feed** (no size, §0.1) — only via the adaptive per-market depth endpoint (§4.4) |
| **Microprice / `imbalance()`** | bid/ask size | **No**, same constraint — already dead code in your own `algos.py` against live data |
| **Trade-size clustering** (stealth trading) | trade tape only | **Yes**, but the signature you want (capitulation) is the *opposite* pattern from the classic "stealth" literature (§1.5) |
| **Quote-stuffing / cancel-to-trade / order-to-trade ratio** | individual order messages (new/modify/cancel), not just resulting top-of-book | **No** — this requires message-level data from the matching engine that a public quote/trade feed structurally cannot provide |

### 1.1 VPIN — Volume-Synchronized Probability of Informed Trading

**[verified: primary-author-hosted text, fetched directly, López de Prado's own site]** Easley, López de Prado & O'Hara, *"Flow Toxicity and Liquidity in a High-Frequency World,"* *Review of Financial Studies* 25(5):1457–1493 (2012); methodology precursor in *"The Volume Clock: Insights into the High-Frequency Paradigm,"* *Journal of Portfolio Management* 37(2) (2011). Construction:

1. **Volume clock, not time clock.** Partition the trade stream into buckets each containing the same traded volume `V` (not equal time). This "subordinates" sampling to activity rather than the clock.
2. **Classify volume as buy/sell within each bucket.** The paper's own method, Bulk Volume Classification (BVC), estimates the buy fraction from the *price change over the bucket* without needing individual trade signs:
   $$f^{\text{buy}}_\tau = \Phi\!\left(\frac{\Delta P_\tau}{\sigma_{\Delta P}}\right), \qquad V^{\text{buy}}_\tau = f^{\text{buy}}_\tau \cdot V, \quad V^{\text{sell}}_\tau = (1-f^{\text{buy}}_\tau)\cdot V$$
   where $\Phi$ is the standard normal CDF and $\sigma_{\Delta P}$ is the (rolling) standard deviation of bucket-level price changes. **You should skip this step entirely** — your `side` field already gives exact $V^{\text{buy}}_\tau, V^{\text{sell}}_\tau$ with zero classification error (§0.3).
3. **VPIN is the trailing mean of per-bucket imbalance:**
   $$\text{VPIN} = \frac{1}{n}\sum_{\tau=1}^{n}\frac{|V^{\text{buy}}_\tau - V^{\text{sell}}_\tau|}{V}$$
   typically averaged over $n=50$ buckets.

**What the mechanism claims, and why it matters for Q2:** VPIN was built to explain why market makers *withdraw* under toxic flow — the paper's own framing (confirmed in the hosted text): *"market makers have incentives to be extremely conservative and liquidate their inventory as soon as they perceive the presence of informed traders... this situation is detrimental to the market, and can derive in serious liquidity crises."* VPIN registered its highest multi-year reading roughly one hour before the May 6, 2010 Flash Crash, which the authors interpret as market makers reading the same signal and pulling back, draining liquidity, which worsened the move (a feedback loop). This is the literature's clearest statement that the "textbook" answer to Q2 is **widen/retreat**, not lean in — but see the critique immediately below before trusting it uncritically.

**[verified via Kellogg/CREATES abstracts, cross-confirmed across 3 independent sources] The Andersen–Bondarenko critique — important, and your own venue's low trade-count makes it more rather than less relevant.** Andersen & Bondarenko, *"VPIN and the Flash Crash,"* *Journal of Financial Markets* 17 (2014), and a related, broader paper (reportedly *Review of Finance* 19(1):1–54, 2015, "Assessing Measures of Order Flow Toxicity and Early Warning Indicators," **secondary-sourced, not independently fetched**) find: (a) in their tick-level reconstruction, VPIN did *not* reach its historical high until *after* the Flash Crash began, not an hour before; (b) VPIN's apparent predictive power for short-horizon volatility is largely **mechanical** — it correlates with contemporaneous volume/volatility and loses most of its incremental signal once you control for those directly; (c) VPIN's behavior is **highly sensitive to the trade-classification method**, with BVC-based and tick-rule-based VPIN sometimes moving in *opposite* directions. Point (c) is exactly why §0.3 matters so much for you: your version of VPIN uses neither BVC nor the tick rule, it uses ground truth, so you sidestep the specific flaw A&B diagnose — but point (b) is a general warning against over-interpreting *any* imbalance-based toxicity metric as having unique informational content beyond "volume was high and one-sided," which is a much more modest (and more honestly stated) claim. **Use VPIN-style imbalance as a volume/one-sidedness screen, not as a validated crash predictor.**

### 1.2 PIN — Probability of Informed Trading

**[established]** Easley, Kiefer, O'Hara & Paperman, *"Liquidity, Information, and Infrequently Traded Stocks,"* *Journal of Finance* 51(4):1405–1436 (1996). Sequential-trade model: with probability $\alpha$ an information event occurs; conditional on an event, informed traders arrive at Poisson rate $\mu$ on the revealed-direction side; uninformed (noise) traders arrive at rate $\varepsilon$ on **each** side independently (so $2\varepsilon$ total noise flow). The standard result:
$$\text{PIN} = \frac{\alpha\mu}{\alpha\mu + 2\varepsilon}$$
— the fraction of all order flow that is informed. **Practical caveat for you:** estimating $(\alpha,\delta,\mu,\varepsilon)$ requires maximum likelihood on a mixture of three Poisson processes fit to *daily buy/sell trade counts*, and is known even in liquid single-name equities to need weeks of reasonably active daily trading to identify four parameters stably. With 80 niche binary markets generating a highly uneven, often thin trade count per market per day, a true structural PIN fit is likely to be numerically unstable or require pooling assumptions you can't justify market-by-market. **VPIN-style imbalance (§1.1, using your native `side`) is the practical substitute** — it was explicitly designed by the same authors as a high-frequency-feasible proxy for PIN for exactly this reason, and Easley-Engle-O'Hara-Wu (2008, *Journal of Financial Econometrics*) show VPIN converges to PIN under the same model's assumptions.

### 1.3 Kyle's λ — price impact per unit signed volume

**[established]** Kyle, *"Continuous Auctions and Insider Trading,"* *Econometrica* 53(6):1315–1335 (1985). Linear price-impact model $P = P_0 + \lambda Q$ where $Q$ is cumulative signed order flow; in the model's equilibrium, $\lambda = \sigma_v / (2\sigma_u)$ (asset-value volatility over twice noise-trader-volume volatility), but the empirically useful form for you is the **reduced-form regression** $\Delta P_t = \lambda \cdot Q_t + \text{noise}$, which is exactly what `sigbot/microstructure.py::kyle_lambda` already implements (OLS slope of mid-price change on signed volume). Higher $\lambda$ = thinner book = same volume moves price further = passive quotes need to sit deeper. You already have this; what's missing is a *rolling, per-market, regime-conditioned* driver (§4.3) rather than a single global estimate.

### 1.4 Trade-size clustering — "stealth trading," and why capitulation looks like its opposite

**[established]** Barclay & Warner, *"Stealth Trading and Volatility: Which Trades Move Prices?"* *Journal of Financial Economics* 34(3):281–305 (1993): on NYSE tender-offer data, medium-size trades (their sample: roughly 500–9,900 shares, far from either the smallest retail clips or the largest block trades) accounted for a disproportionate 92.8% of cumulative pre-announcement price drift — the stealth-trading hypothesis is that informed traders deliberately split orders into medium clips to avoid detection, since very small trades move price too slowly and very large trades are too conspicuous. (A related extension, Chakravarty (2001), *J. Financial Economics* 61(2):289–307, reclassifies by inferred trader type rather than pure size and finds a similar pattern driven specifically by institutional, not retail, flow.)

**This result does not transfer directly to capitulation detection, and the reason matters.** Stealth trading is a signature of someone trying to *hide* informed activity; capitulation/forced-liquidation is, by construction, the opposite — a trader who no longer has the luxury of disguising size because they are racing a hard deadline. The theoretically expected signature of genuine capitulation is closer to: **large (not medium), repeatedly one-directional, spread-crossing trades, print size increasing rather than staying disguised, with decreasing inter-trade time** — i.e., a sweep, not a stealth clip. **[my own synthesis, flagged as reasoned inference, not a direct citation — no paper tests this specific contrast]** This gives you a concrete, venue-calibrated threshold rather than importing 1993 NYSE share counts, which are meaningless at your scale: your own trade-size distribution (1.64M trades, `research/data/tape.db`) has median 92 shares, p90=1,000, p95=1,726, p99=8,894, p99.9=32,568. A reasonable "large/sweep-scale" cutoff for your markets is therefore **p95–p99 of your own trailing distribution (≈1,700–8,900 shares)**, recomputed periodically since 80 markets span very different liquidity regimes and a single global threshold will misfire on both your thinnest and thickest books.

### 1.5 Quote-stuffing and cancel-to-trade ratios — confirmed not computable, and why

**[established definitions]** Order-to-trade ratio (OTR) is formally `(new + modify + cancel order messages) / (executed trades)`, monitored by exchanges (Eurex publishes a public OTR policy) and studied academically as a quote-stuffing proxy (e.g., Egginton, Van Ness & Van Ness, *"Quote Stuffing,"* *Financial Management* 45(3):583–608, 2016, find episodes of extreme quoting activity are associated with reduced liquidity and higher trading costs for other participants). **All of these require visibility into individual order messages** — specifically cancels and modifies that never result in a trade and never even necessarily change the *best* bid/ask (e.g., queue churn two levels back). A public feed that only reports resulting top-of-book price/size (and you don't even have size) or a trade tape cannot reconstruct this even in principle, because a cancel-and-immediately-replace at the same price is invisible to both feeds. This is a clean, honest negative result: **do not attempt a cancel-ratio or quote-stuffing metric on this venue** — not because it's hard, but because the necessary data does not reach you, confirmed by what the API exposes (§0) rather than assumed.

---

## 2. Optimal market-maker response to toxic flow: widen, shrink, or lean in? [Q2]

The honest literature answer is conditional, not universal, and the condition is identifiable in principle from your own data.

### 2.1 The "widen/retreat" case — Glosten-Milgrom and the VPIN mechanism

**[ESTABLISHED, and already derived for your exact contract type in `research/MARKET_MAKING_THEORY.md` §3.1]** Glosten & Milgrom, *"Bid, Ask and Transaction Prices in a Specialist Market with Heterogeneously Informed Traders,"* *Journal of Financial Economics* 14(1):71–100 (1985): a zero-profit dealer facing a fraction $\pi$ of informed flow sets $a = E[V \mid \text{buy}]$, $b = E[V\mid\text{sell}]$. Your own prior session already specialized this exactly to a binary $\{0,1\}$ payoff with prior $p$:
$$\text{spread}(p,\pi) = \frac{4\pi\,p(1-p)}{1-\pi^2(2p-1)^2}$$
— which **vanishes as $p\to 0$ or $p\to1$** (your longshot tails) regardless of $\pi$, and is **increasing in $\pi$** everywhere else: the formal statement that as perceived informedness rises, the *correct* response is a wider spread, approaching full non-quoting ($\text{spread}\to1$) as $\pi\to1$. VPIN's whole applied purpose (§1.1) is giving you a real-time estimate of something like $\pi$ so you can move along this curve dynamically rather than using a single static spread.

### 2.2 The "lean in" case — compensated liquidity provision into transient imbalance

**[ESTABLISHED]** Grossman & Miller, *"Liquidity and Market Structure,"* *Journal of Finance* 43(3):617–633 (1988): when an imbalance is driven by liquidity need rather than information, the liquidity provider who absorbs it is compensated by a subsequent price *reversal* back toward their execution price — genuinely positive realized spread by construction, not a measurement artifact. Nagel, *"Evaporating Liquidity,"* *Review of Financial Studies* 25(7):2005–2039 (2012): short-term reversal strategies (the standard empirical proxy for the returns to liquidity provision) earn **predictably higher** returns precisely when liquidity is scarce — the compensation scales *with* the apparent stress, not against it, because the mechanism is bearing short-horizon inventory risk against a transient imbalance, not informational edge. Both already cited in your own `MARKET_MAKING_THEORY.md` §3.2, alongside the directly relevant counter-intuitive finding from **Ochedzan & Antulov-Fantulin (2026), arXiv:2606.05882** (an RL/agent-based study, treat as suggestive not a closed-form theorem): market-maker profitability can *rise* with aggregate informedness specifically when price discovery is fast enough that market makers re-quote before damage compounds — consistent with your own measured pattern of markout peaking at 5–30 minutes before decaying (informed flow operating on an hours timescale here, not milliseconds).

### 2.3 The deciding variable: permanent vs. transient impact — and this is already measurable with your own tools

The two regimes above are not actually contradictory theories competing for the same facts; they are different answers conditional on whether the price move a sweep causes **persists** (informational, §2.1 applies) or **partially reverts** (liquidity-driven, §2.2 applies). This is precisely what Huang-Stoll decomposition and your markout-decay curve already measure (`sigbot/microstructure.py::decompose_fill`, `SpreadDecomposition.retention`) — what's missing is conditioning that measurement specifically on *fills that occur during a flagged high-imbalance window* versus your unconditional baseline. Concretely (implementation in §4.5): if markout conditional on "this fill followed a VPIN-flagged sweep" is **more positive and better-retained** at 5–30 minutes than your unconditional baseline, that's direct evidence you're in the Grossman-Miller/Nagel regime for that flow and should lean in; if it's **more negative and decays faster/flips sign sooner**, you're in the Glosten-Milgrom/VPIN-mechanism regime and should widen. This also directly answers the user's underlying theoretical question about tournament-driven risk-shifting: a participant dumping a losing position because they are statistically out of prize contention is informed about *their own standing*, not about the election outcome — this kind of flow has, in principle, **zero correlation with the contract's true terminal value**, which places it structurally in the transient/liquidity-driven bucket almost by construction. **The caveat that matters operationally: tournament-panic flow and genuine late-breaking political information can look identical in aggregate order-flow statistics in real time** — same one-sidedness, same size, same urgency. You cannot reliably tell them apart from flow shape alone; you can only tell them apart after the fact, from whether the move reverted — which is exactly why the conditional-markout test, not a theoretical prior, should govern the live decision rule, and why the default while that test is underpowered should stay on the conservative (widen) side (§4.6).

### 2.4 Prediction-market-specific evidence (already in your own research, worth restating as the most directly relevant citations you have)

Per your own `MARKET_EDGES.md` §3: **Bartlett & O'Hara (2026)**, Stanford Rock Center WP, SSRN 6615739 — 41.6M Kalshi trades, single-name markets show *greater* informed price impact (Kyle's λ) yet market makers earn ~2x more per contract there, resolved by a behavioral overpricing effect that cross-subsidizes adverse selection; **Whelan (2025/26)**, Betfair — "longshot bets lose an increasing amount of money as the game nears its end, even for Makers," the cleanest direct evidence that your exact risk (longshot + late + still market-making) is real and documented, though in a sports (not election) clock; **Dubach (2026)**, arXiv:2604.24366 — public-feed aggressor-side inference on Polymarket is only ~59% accurate vs. on-chain ground truth, which is precisely why §0.3's empirical verification of your own venue's `side` field mattered rather than assuming it transfers; **Mitts & Ofir**, SSRN 6426778 — systematic evidence of informed trading concentrated around genuine information events on Polymarket (not deadline-panic specifically).

### 2.5 The legitimacy boundary, made concrete

**[ESTABLISHED]** Brunnermeier & Pedersen, *"Predatory Trading,"* *Journal of Finance* 60(4):1825–1863 (2005), give the formal distinction you're implicitly asking for. **Predatory trading** requires (a) identifying a *specific* distressed trader's forced-liquidation need and (b) actively trading in the *same* direction to accelerate their losses, planning to reverse later at the depressed price — this is what regulators and the literature treat as illegitimate. **Liquidity provision** is standing passively ready to absorb imbalance from *whichever* counterparty arrives, priced by statistical properties of aggregate flow, with no targeting of any identifiable account and no attempt to accelerate anyone's loss. A resting ladder that reads aggregate VPIN/λ statistics across 80 markets and adjusts its own posted spread/size in response is squarely the second category by construction: you cannot identify individual counterparties from a public trade tape, you are not trading to *induce* further selling, and you never cross the spread to chase anyone. This is a real, citable line, not just a framing choice — keep both halves of this design (never cross the spread; react only to aggregate statistics, never to inferred-individual behavior) and you stay on the liquidity-provision side of it.

---

## 3. Binary/prediction-market capitulation detection specifically [Q3]

**Confirmed, consistent with your own `FINAL_DAYS_LIT.md` finding: no paper directly studies forced/capitulation selling in binary prediction contracts near a hard deadline.** This is a genuine, repeatedly-confirmed gap across your own prior research passes, not something this session's search uncovered that earlier ones missed. The closest grounding, assembled from both your own prior files and this session's additions:

- **Barberis & Xiong, *"Realization Utility,"* *Journal of Financial Economics* 104(2):251–271 (2012)**: investors derive utility directly from the *act* of realizing a gain or loss, not just from wealth changes — this is the formal mechanism behind the disposition effect (reluctance to realize losses). Critically: **a hard deadline removes the discretion the disposition effect depends on.** Under voluntary trading, losers are held; when realization becomes forced (margin call, deadline, contest cutoff), the same trader who would never voluntarily sell now must, which is precisely the "capitulation" mechanism — it is the disposition effect's reservoir being emptied all at once rather than gradually.
- **Coval & Stafford, *"Asset Fire Sales (and Purchases) in Equity Markets,"* *Journal of Financial Economics* 86:479–512 (2007)**, and **Barber, Huang, Odean & Schwarz, *"Attention-Induced Trading and Returns: Evidence from Robinhood Users,"* *Journal of Finance* 77(6):3141–3190 (2022)** — both already in your `FINAL_DAYS_LIT.md` §Q4 — are the strongest *quantified* analogs: forced/herding-driven selling reliably reverses over subsequent days-to-months, and a disciplined counterparty providing liquidity against it earns a real, repeatable premium (Coval-Stafford: long-short strategy +0.41–0.97%/month; Barber et al.: fading extreme Robinhood herding earns +3.5–6.4%, profitable in 63% of 4,884 events). Neither is a prediction-market study, but both are precisely "does fading forced/herding-driven one-sided flow pay," which is your operational question.
- **Your own §2.4 citations** (Bartlett-O'Hara, Whelan, Dubach, Mitts-Ofir) are the only genuinely binary/prediction-market-specific evidence, and none isolates deadline-driven capitulation from ordinary late-cycle informed trading.

**Would resting passive liquidity just ahead of such flow capture favorable fills?** Conditional on the Coval-Stafford/Barber-et-al. mechanism applying (price pressure that reverts), yes, by the same Grossman-Miller logic as §2.2 — a ladder resting below a one-directional sell-walk captures fills at the depressed/panicked prices and benefits if/when the pressure passes. The operational risk is exactly the confound named in §2.3: you cannot distinguish "contest-standing panic" from "genuine late information" from flow shape alone, and only the conditional-markout test, not the theory, should be trusted to decide in real time.

---

## 4. Practical implementation against your real schema [Q4]

All code below assumes the real tables in `research/data/tape.db`: `quote(ts, exchange_id, last, bid, ask, spread)` and `trade(trade_id, exchange_id, created_at, price, size, side)`, with `side ∈ {"YES","NO"}` as ground-truth direction (§0.3).

### 4.1 Signed trade flow from the native `side` field (replaces Lee-Ready/tick-rule/BVC entirely)

```python
import sqlite3
import pandas as pd
import numpy as np

def load_signed_trades(con: sqlite3.Connection, exchange_id: str) -> pd.DataFrame:
    """
    Signed YES-direction trade flow, using the venue's own ground-truth `side`
    label instead of inferring direction (Lee-Ready/tick-rule/BVC are all
    unnecessary here -- verified empirically, see research/TOXICITY_LIT.md S0.3).
    """
    df = pd.read_sql_query(
        "SELECT created_at, price, size, side FROM trade "
        "WHERE exchange_id = ? ORDER BY created_at",
        con, params=(exchange_id,), parse_dates=["created_at"])
    df["signed_size"] = np.where(df["side"] == "YES", df["size"], -df["size"])
    return df
```

### 4.2 "SideVPIN": a VPIN analog using ground-truth side instead of BVC

```python
def side_vpin(trades: pd.DataFrame, bucket_volume: float, n_buckets: int = 20) -> pd.Series:
    """
    Volume-bucketed order-flow toxicity, Easley-Lopez de Prado-O'Hara (2012)
    construction, but skipping Bulk Volume Classification entirely because
    `side` already gives exact per-trade direction (no Phi(.) estimation
    needed -- this removes exactly the trade-classification sensitivity
    Andersen & Bondarenko (2014) show BVC-based VPIN is vulnerable to).

    bucket_volume: size of each volume bucket, e.g. ~1/50th of this market's
    trailing daily volume. Thin markets need a much smaller bucket_volume
    than liquid ones -- do not use one global constant across all 80 markets.
    """
    cum_vol = trades["size"].cumsum()
    bucket_id = (cum_vol // bucket_volume).astype(int)
    g = trades.groupby(bucket_id)["signed_size"].agg(buy=lambda s: s[s > 0].sum(),
                                                       sell=lambda s: -s[s < 0].sum())
    imbalance = (g["buy"] - g["sell"]).abs() / bucket_volume
    return imbalance.rolling(n_buckets, min_periods=max(5, n_buckets // 4)).mean()
```

### 4.3 Rolling, per-regime Kyle's λ (reusing your existing function)

```python
from sigbot.microstructure import kyle_lambda

def rolling_lambda(quotes: pd.DataFrame, trades: pd.DataFrame, window: str = "30min") -> pd.Series:
    """
    Realized price impact per signed share, over rolling windows, driving
    your already-implemented kyle_lambda(). mid is built from (bid+ask)/2
    at each quote snapshot; signed volume is summed from the native `side`
    field over the same window (S4.1) -- no size-at-depth needed for this one,
    only top-of-book price + the trade tape, both of which you have.
    """
    mid = (quotes["bid"] + quotes["ask"]) / 2.0
    mid.index = pd.to_datetime(quotes["ts"])
    mid = mid.resample("2min").last().ffill()       # match your ~2-min cadence
    dP = mid.diff()

    flow = trades.set_index("created_at")["signed_size"].resample("2min").sum()
    flow = flow.reindex(mid.index, fill_value=0.0)

    out = {}
    idx = mid.index
    win = pd.Timedelta(window)
    for t in idx:
        mask = (idx > t - win) & (idx <= t)
        if mask.sum() >= 5:
            out[t] = kyle_lambda(flow[mask].values, dP[mask].values)
    return pd.Series(out)
```

### 4.4 Degraded, price-only confirmation signal (no size needed) + the adaptive-depth trigger

Because the bulk feed has no size (§0.1), build a cheap, always-on **sweep flag** from price alone, and reserve the expensive per-exchange depth call (§0.2) for markets it flags:

```python
def sweep_flag(quotes: pd.DataFrame, trades: pd.DataFrame) -> pd.Series:
    """
    Flags intervals where trades printed through the PRIOR snapshot's touch,
    i.e. the resting size at the touch was fully consumed and the taker
    walked the book -- inferable from price alone, no depth feed required.
    """
    q = quotes.set_index(pd.to_datetime(quotes["ts"])).sort_index()
    flags = []
    for _, row in trades.iterrows():
        prior = q.loc[:row["created_at"]].iloc[-1:] if not q.loc[:row["created_at"]].empty else None
        if prior is None:
            continue
        crossed = (row["side"] == "YES" and row["price"] > prior["ask"].iloc[0]) or \
                  (row["side"] == "NO" and (1 - row["price"]) < prior["bid"].iloc[0])
        flags.append(crossed)
    return pd.Series(flags, index=trades.index)
```

When `side_vpin` crosses its own market's trailing-quantile threshold **and** `sweep_flag` is firing repeatedly in one direction, that market is the one worth spending a `CombinedOrderbookExchange` call on to get real depth/OFI (§1, Cont-Kukanov-Stoikov) — this is the two-tier architecture the rate limit actually allows: cheap, native-side VPIN + price-only sweep detection always-on across all 80 markets; expensive true-depth OFI only on the few flagged at any time.

### 4.5 The conditional-markout test that actually answers "widen or lean in" (§2.3)

```python
from sigbot.microstructure import decompose, decompose_fill

def conditional_markout_split(fills_with_flags):
    """
    fills_with_flags: iterable of (fill_price, mid_at_fill, mid_later, side,
    action, was_flagged: bool), `was_flagged` = True if this fill occurred
    during a side_vpin/sweep-flagged window (S4.2/4.4).

    Compare retention (realized/effective half-spread) between the two
    regimes using your EXISTING decompose(). Higher retention when flagged
    => Grossman-Miller/Nagel regime => lean in. Lower/negative retention
    when flagged => Glosten-Milgrom/VPIN regime => widen.
    """
    flagged = [f[:5] for f in fills_with_flags if f[5]]
    normal = [f[:5] for f in fills_with_flags if not f[5]]
    return {"flagged": decompose(flagged), "normal": decompose(normal)}
    # Feed each regime's markouts into evaluate.confidence_sequence() /
    # evaluate.required_n_unknown_variance() before trusting the split --
    # exactly the discipline already applied to the 91-fill retention numbers.
```

### 4.6 Decision rule (default conservative until the split in §4.5 is powered)

```python
def quote_adjustment(side_vpin_pctile: float, sweep_one_sided: bool,
                      flagged_retention: float | None, normal_retention: float,
                      n_flagged_fills: int, n_required: int) -> str:
    """
    side_vpin_pctile: this market's current SideVPIN vs its OWN trailing
    history (self-normalized -- 80 markets span very different liquidity
    regimes, a single global VPIN threshold will misfire).
    """
    elevated = side_vpin_pctile > 0.90 and sweep_one_sided
    if not elevated:
        return "normal"
    if n_flagged_fills < n_required or flagged_retention is None:
        return "widen"   # conservative default per S2.1/S2.3 until proven otherwise
    return "lean_in" if flagged_retention > normal_retention else "widen"
```

---

## 5. Honest gaps and confidence ledger

- **No paper studies deadline-driven capitulation in binary prediction markets specifically** — confirmed across two independent research passes now (this one and `FINAL_DAYS_LIT.md`). Everything in §3 is analogy, clearly flagged as such.
- **Andersen & Bondarenko's critique (§1.1) means VPIN-style imbalance should be read as "volume was high and one-sided," not as a validated early-warning system** — your native-`side` version sidesteps their classification-sensitivity finding specifically, but not their mechanical-correlation-with-volume finding generally.
- **The permanent-vs-transient distinction (§2.3) is the load-bearing claim in this whole report, and it is testable but not yet tested** — §4.5's conditional split needs enough flagged fills to be powered (use `evaluate.required_n_unknown_variance`, matching how you validated the 91-fill retention numbers) before it should override the conservative default.
- **The second Andersen-Bondarenko paper (Review of Finance, 19(1):1-54, 2015) is secondary-sourced, not independently fetched this session** — treat its specific numbers as approximate.
- **No depth-feed cost/benefit analysis was run** — §4.4's "spend the expensive call only on flagged markets" is a sound architecture on paper but its actual rate-limit economics (how many markets can realistically be flagged at once, how fast the per-exchange orderbook endpoint responds under your existing ~38 req/min budget) was not measured this session.

## References

Easley, López de Prado & O'Hara (2012, *Review of Financial Studies* 25(5)); Easley, López de Prado & O'Hara (2011, *Journal of Portfolio Management* 37(2)); Easley, Engle, O'Hara & Wu (2008, *Journal of Financial Econometrics*); Easley, Kiefer, O'Hara & Paperman (1996, *Journal of Finance* 51(4)); Andersen & Bondarenko (2014, *Journal of Financial Markets* 17; 2015, *Review of Finance* 19(1), secondary-sourced); Kyle (1985, *Econometrica* 53(6)); Cont, Kukanov & Stoikov (2014, *Journal of Financial Econometrics* 12(1), arXiv:1011.6402 — OFI formula verified against primary PDF text this session); Glosten & Milgrom (1985, *Journal of Financial Economics* 14(1)); Grossman & Miller (1988, *Journal of Finance* 43(3)); Nagel (2012, *Review of Financial Studies* 25(7)); Barclay & Warner (1993, *Journal of Financial Economics* 34(3)); Chakravarty (2001, *Journal of Financial Economics* 61(2)); Egginton, Van Ness & Van Ness (2016, *Financial Management* 45(3)); Brunnermeier & Pedersen (2005, *Journal of Finance* 60(4)); Barberis & Xiong (2012, *Journal of Financial Economics* 104(2)); Coval & Stafford (2007, *Journal of Financial Economics* 86); Barber, Huang, Odean & Schwarz (2022, *Journal of Finance* 77(6)); Ochedzan & Antulov-Fantulin (2026, arXiv:2606.05882); Bartlett & O'Hara (2026, SSRN 6615739); Whelan (2025/26, Betfair); Dubach (2026, arXiv:2604.24366); Mitts & Ofir (SSRN 6426778) — the last five cross-referenced from this project's own prior `MARKET_EDGES.md`/`MARKET_MAKING_THEORY.md` rather than re-verified this session.

*Compiled this session via direct primary-source fetches (quantresearch.org/VPIN.pdf extracted with `pdftotext`; arXiv:1011.6402 PDF extracted and the exact $e_n$ formula quoted verbatim from the source text) plus empirical verification against this project's own `research/data/tape.db` (schema, trade-price symmetry check across 15 markets, trade-size quantiles) and `sig_openapi.json`; secondary-sourced claims are flagged inline.*

---

## VALIDATION RESULT (2026-10-27) — tested against 4,539 real fills, NOT actionable

Built the §4.1/4.5 signal (10-min pre-fill signed-volume imbalance from the real
`tape.db` trade side field) and ran the conditional-markout split this report
called for before trusting anything.

**Naive imbalance alone (any fill during a one-sided window): no significant
effect.** Across thresholds 0.7-1.0 and min-trade-count filters 5-30, the
flagged-vs-normal markout difference was small (-0.0002 to -0.0007/share) and
never significant (p=0.08-0.67, all 95% CIs include zero). A crude "was there
recent one-sided flow" signal does not discriminate good fills from bad ones.

**Direction-aware (was OUR fill caused by a sweep moving price against us,
specifically): real, large, stable effect.** Aligned fills markout
-0.00159/share vs +0.00183/share otherwise (diff -0.00342, p=0.0000, n=750 vs
1,678). Confirmed stable: present in both halves of the dataset by date
(p=0.0000 each) and in just the last 5 days alone (p=0.0002, n=57 vs 228). This
is a real, not spurious, adverse-selection effect -- getting run over by a
sweep is genuinely bad, confirming the Glosten-Milgrom/"widen" regime from
section 2, not Grossman-Miller/"lean in."

**But segmented by strategy, it is not actionable for us:**

| strategy   | aligned n | aligned markout | other markout | p      |
|------------|-----------|-----------------|---------------|--------|
| exit       | 606       | -0.00172        | -0.00035      | 0.0001 |
| settlement | 122       | -0.00186        | -0.00095      | 0.0294 |
| **ladder** | **22**    | **+0.00341**    | **+0.00454**  | **0.49** |

Ladder -- the passive market-making strategy this whole investigation was
motivated by -- shows no significant effect, and only 22 aligned fills in ~25
days of data. Consistent with its own docstring: quoting 3-6 ticks below mid
with queue decay measured at "revert median 2 minutes" already keeps it mostly
out of the way of a sweep by construction. There is very little exposure left
to fix.

The effect that IS real sits in Exit and (weakly) Settlement:
  * Exit's job is cutting a position whose edge has already decayed. A fill
    coinciding with continued adverse momentum is close to tautological --
    the position was already going wrong, which is why Exit fired. "Widen the
    exit price" here means holding a decaying position longer during adverse
    momentum, which is the averaging-down mistake Exit exists to prevent, not
    a safe fix.
  * Settlement's effect is statistically real but economically tiny
    (-0.0009/share) next to its actual edge driver (8-15% return on
    collateral, i.e. ~0.08-0.15/share) -- not worth new live logic for a
    rounding error relative to what actually moves this book's P&L.

**Conclusion: no code change.** Real signal, correctly validated, does not
clear the bar for a safe, net-positive intervention with 8 days left. Filed
here so this exact analysis isn't redone without knowing it was already tried.
