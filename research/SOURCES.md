# Information Sources & Compliance

## Recommended stack (ranked)

1. **Polymarket CLOB WebSocket** — free, public, no auth, sub-second push.
   Reflects informed-trader reaction *before* headlines post. Cleanest compliance
   posture of any fast source (only *trading* is US-geoblocked, not *reading*).
2. **State Clarity/ENR JSON feeds** for **IA, NJ, SC, NE** — one client, reused.
   Free, live, no ToS prohibition found. On election night this is the closest
   thing to a primary numeric feed.
3. **AP Elections API** (or **Decision Desk HQ**, cheaper) — needed for actual
   *race calls*; raw vote counts don't tell you "called". Paid.
4. **VoteHub + Silver Bulletin + Strength In Numbers**, polled every few minutes —
   catches "new poll moves the average". Aggregator-lagged.
5. **Individual pollster press-release pages** (Quinnipiac/Siena/Marist/Emerson)
   **+ Google News RSS** — catches a poll at embargo release, and qualitative
   catalysts (withdrawals, scandals) that never appear in structured feeds.

## 🚩 DO NOT USE — compliance blacklist

| Source | Reason |
|---|---|
| **Kalshi API** | Dev Agreement §3.1: API use *"expressly limited to facilitating a member's own trading on the Exchange"*. Using it to signal trades on our venue is exactly what this targets. Binding on mere access. **No automated client.** |
| **Colorado SOS** | ToS verbatim: *"Use of computerized 'robots' or 'data mining'... is prohibited."* Runs the same Clarity platform as Iowa — exclude anyway. |
| **Virginia Dept. of Elections** | robots.txt disallows `*.json`/`*.csv`/`*.xls` site-wide. |
| **NYT results JSON** | robots.txt prohibits automated scraping without written permission. |
| **Edison Research / NEP** | Consortium-members only. Privileged/embargoed = exactly what Rules §7 bars. |
| **civicAPI** | Zero disclosed provenance — likely a re-scrape of a licensed source. |
| **`silver-bulletin-api` PyPI** | Unaffiliated individual's package, not official Silver Bulletin. |
| **AP internal feed endpoints** | `apnews.com/robots.txt` disallows `/api/v2/feed/`. Use the licensed route. |
| Ballotpedia / Cook | AWS WAF blocked 8/8 attempts; scraping infeasible and against ToS. |

⚠️ If we ever subscribe to the contest's **named resolution source**, confirm their
terms grant no preview/embargo window ahead of public release — that would create
a self-dealing MNPI problem under Rules §7.

## Event calendar (Oct 2 – Nov 4, 2026)

| Date | Event |
|---|---|
| Throughout Oct | ~41 Nexstar-hosted Senate/Gov/House debates across 30 states, through Nov 3 |
| Sep 18 – Oct 31 | Early/absentee voting opens state-by-state (MN/VA earliest; TX Oct 19; NY Oct 25; NJ Oct 26) |
| **Oct 15** | FEC Q3 report deadline — fundraising moves race ratings |
| **Oct 22** | FEC Pre-General report deadline |
| **Nov 3** | Election Day — 435 House, 35 Senate, 36 Governor |
| **Nov 4, 12:00 ET** | **Trading closes** |

## ⚠️ The settlement tail — matters for scoring

Our score is final only after **all** markets settle:
- **California**: county canvass up to 30 days, certification ~**Dec 3** (38 days)
- **Washington**: certification ~21 days (~Nov 24)
- **Arizona**: signature verification historically runs weeks
- **ME-02**: ranked-choice tabulation rounds delay any final call
- **GA / LA**: runoff rules (Dec 1 / Dec 12) if no majority
- 4 chamber-control markets settle manually, after individual races

So positions in CA/WA/AZ/ME and any runoff-bound race are **locked and unresolvable
for weeks after trading closes**. Variance in that bucket is irreversible — size it
deliberately before the Nov 4 freeze.

**Gap:** no authoritative consolidated "expected poll releases" calendar exists;
pollster timing is discretionary.
