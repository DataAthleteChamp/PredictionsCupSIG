Agent is idle (waiting for messages). agent_id: 9212ede5-a5ea-432a-9415-78bc8ad020d3, agent_type: research, status: idle, description: 2026 midterm political data, elapsed: 1903s, total_turns: 1

[Turn 0]
# 2026 Midterm Election Data Sources: Research Report
**Compiled 2026-10-02 (~31 days pre-election).** Methodology: 6 parallel research passes (live `web_fetch`/`curl` against primary sources, not training-data recall) plus direct independent verification of the highest-stakes claims (FEC deadlines, robots.txt files, RSS feeds). All dates are "accessed/fetched 2026-10-02" unless stated otherwise. **This is a fast-moving live cycle — treat anything not marked "directly verified" with appropriate caution**, and re-check before production use.

---

## Master Summary Table

| # | Source | Covers | Machine-readable? | Update freq. | Automated access ToS |
|---|---|---|---|---|---|
| 1 | **FEC API** (api.open.fec.gov) | Campaign finance | ✅ REST/JSON, documented | Rolling; next quarterly 10/15/26 | ✅ Built for this; robots.txt oddly says `Disallow:/v1/*` but this targets HTML crawlers, not the keyed API |
| 2 | **Wikipedia (MediaWiki API)** | Polls, retirements, redistricting | ✅ JSON-wrapped wikitext/HTML | Volunteer-edit cadence (near-daily on hot races) | ✅ No restriction; official sanctioned method |
| 3 | **Election Law Blog** RSS | Election-law/court rulings | ✅ RSS (`/feed/`) | Multiple/day | ✅ No restriction found |
| 4 | **Democracy Docket** news-alerts RSS | Redistricting litigation | ✅ RSS (`/news-alerts/feed/` — NOT `/feed/`) | Minutes | ⚠️ No written restriction found, but Cloudflare challenges rapid repeat requests |
| 5 | **Decision Desk HQ** forecast | Sen/House/Gov probabilities | ⚠️ HTML/JS only; `/api/` explicitly disallowed | Intraday | ✅ Content pages allowed; API is a paid product |
| 6 | **Race to the WH** | Sen/House/Gov probabilities + polls | ⚠️ HTML; JSON shortcut exists but is robots.txt-disallowed | Daily | ✅ Content pages allowed, don't hit `?format=json` |
| 7 | **StateNavigate** (ex-CNalysis) | State legis. + Gov + finance | ✅ Documented API, CSV/JSON/GeoJSON | Varies by dataset | ✅ No restriction found; API is key/origin-gated |
| 8 | **VoteHub** | Polls, generic ballot, approval | ✅ Live unauthenticated JSON API | Continuous | ❌ **robots.txt explicitly forbids scraping without written permission** |
| 9 | **Silver Bulletin** (natesilver.net) | Generic ballot, approval, FLIPR model | ⚠️ Google-Sheets-hosted CSVs exist | Daily | ❌ **robots.txt names ClaudeBot/GPTBot/etc. `Disallow: /`**; model paywalled |
| 10 | **The Hill / Nexstar properties** | DDHQ forecast embed | HTML | — | ❌ **ToU explicitly bans bots, scraping, and AI-training use** |
| 11 | **Cook Political / Sabato's Crystal Ball** | Qualitative ratings | ❌ Cloudflare-blocked at infra level | Days–weeks | ⚠️ Could not retrieve ToS directly (blocked); CPR confirmed paywalled at race-level |
| 12 | **RealClearPolitics/Polling** | Generic ballot, approval, polls | ❌ No API found; DataDome bot-blocked | Near-daily | ⚠️ 403 on every attempt; ToS text itself unreachable |
| 13 | **AP/Reuters wire RSS** | Breaking political news | ❌ All tested feed URLs 403/401/404 | — | ❌ Reuters robots.txt explicitly bars automated collection |
| 14 | **Politico / Axios RSS** | Breaking political news | ✅ Confirmed working RSS | Hourly-ish | ✅ No restriction found |
| 15 | **AP Elections API** | Pre-election race/candidate refs + results | ✅ JSON, documented | Continuous | ⚠️ Enterprise "contact sales," pricing/eligibility for non-media firms unconfirmed |

---

## 1. Quantitative Forecast Sources

| Source | 2026 URL (verified) | Coverage | Frequency | Machine-readable | ToS/robots.txt |
|---|---|---|---|---|---|
| **Decision Desk HQ / The Hill** | `votes.decisiondeskhq.com/forecast/2026/{senate,house,governor}` | All 3, full chamber ("Democrats favored in 20 of 36 governor's races") | Intraday — page showed "Last updated Oct 2, 10:12 AM" at fetch time | Probabilistic (1,000,000-sim Monte Carlo). `/api/` exists but `votes.decisiondeskhq.com/robots.txt` (directly verified by me): `Disallow: /api/`, `/admin/`, `/broadcast/`, `/onboarding/`; content pages allowed | If accessed via **thehill.com**, Nexstar's ToU (`nexstar.tv/terms-of-use/`) explicitly bans "robot, spider... data gathering," and use "to create, train... AI product." DDHQ's own domain carries no located ToS; a tiered Free/Pro/Enterprise product (`decisiondeskhq.com/pricing`) implies bulk access is commercial |
| **Race to the WH** | `racetothewh.com/{senate,house,governor}/26` | All 3; House claims "all 435 races" | Explicitly "updates daily" | Probabilistic (10,000 sims). Separate poll DB at `/allpolls`. Squarespace `?format=json` trick returns 200 but is **robots.txt-disallowed** for `*` and ~25 named AI bots | No ToS page found; robots.txt blocks only `/config`, `/search`, `/api/`, format-tricks — **not** ordinary content pages |
| **Split Ticket** | `split-ticket.org` | Historically Sen/House/Gov | — | **Stale**: `/senate`, `/house` still show 2024-cycle content. Aug 2025 post confirms partnership: *"we've agreed on an exclusive partnership with The Argument... Split Ticket co-founder Lakshya Jain will also be the new Director of Political Data at The Argument."* Current 2026 ratings now syndicated via `270towin.com/2026-senate-election/split-ticket-2026-senate-ratings` | RSS feed exists (`/feed/`); robots.txt permissive (WordPress default) |
| **Sabato's Crystal Ball** | `centerforpolitics.org/crystalball/2026-{senate,house,governor}/` | All 3 | Senate updated "Aug. 19, 2026" per Wayback snapshot — **could not confirm more recent update**; live site 403s | Qualitative (Safe/Likely/Lean/Toss-up map graphics) | **Live site returns a Cloudflare JS challenge on `/robots.txt` and `/feed/` (403)** — infra-level bot block, ToS unreachable |
| **Cook Political Report** | `cookpolitical.com/ratings` | House/Senate/Gov named | Unknown (blocked) | Qualitative, 7-point scale | **Cloudflare-blocked (403)** on robots.txt/feed. Via Wayback (snapshot 2026-09-29): *"Our subscribers have first access to individual race pages for each House, Senate and Governors race, which will include race ratings... and a narrative analysis."* → **race-level ratings are subscriber-gated**; exact free/paid boundary for top-line content not confirmable while site is blocked |
| **Inside Elections** | `insideelections.com/ratings/{house,senate,governor}` | All 3, **confirmed free**, no paywall hit | Unstated | Qualitative, seat-range framing (e.g., "Democrats +7-15 seats" House) | `robots.txt`: `Disallow: /wp-admin/` only. RSS live at `/feed/` (general blog feed, not a ratings-specific feed) |
| **CNalysis** | **Rebranded → `statenavigate.org`** (`cnalysis.com` 301-redirects there — confirmed independently by me) | Congress + **state legislative chambers** + Gov + campaign finance + demographics | Per-dataset, varies | **Strongest technical find of the 11**: documented REST API at `api.statenavigate.com/api/` (returns structured JSON auth-error, confirmed live), plus CSV/JSON/GeoJSON bulk downloads (`projects.statenavigate.com/downloads/data.html`) | `robots.txt` permissive (WordPress default); API itself is key/origin-gated (technical, not legal, restriction) |
| **JHK Forecasts** | `jhkforecasts.com` | **Exists**, but free-tier 2026 content **not found** — all 2026 path guesses 404; homepage links only to 2022 cycle | — | Paid tier `jhk-forecasts-plus.ghost.io` returned **402 Payment Required** | N/A — inaccessible |
| **Silver Bulletin** | `natesilver.net` | FLIPR model: Sen/House/Gov (per third-party summaries — see ToS note) | "Daily to several times/week" (third-party) | Paywalled model (~$15/mo or ~$95/yr, third-party estimate, **not primary-confirmed**) | **`natesilver.net/robots.txt` explicitly lists `Disallow: /` for ClaudeBot, GPTBot, anthropic-ai, Claude-Web, CCBot, Bytespider, Amazonbot, and others by name**, plus `Content-Signal: ai-train=no`. This is the single clearest "do-not-scrape-with-AI" signal found in this entire research pass |
| **The Economist** | — | **Not found.** Zero Wayback snapshots for any `projects.economist.com/us-2026-midterms*` path; `site:economist.com 2026 midterms forecast` search returned no results | — | — | No dedicated 2026 midterm model appears to exist (reasonably high confidence negative, not provable with certainty since economist.com blanket-403s automated requests) |
| **Academic models** (PollyVote, Gelman/Columbia, Linzer) | — | **None found active for 2026 US midterms.** PollyVote's homepage is currently about the German 2025 election; no Gelman/Columbia or Linzer-branded 2026 midterm forecast located | — | — | N/A |

---

## 2. Raw Polling Aggregators

- **FiveThirtyEight: confirmed shut down.** ABC News/Disney discontinued it in March 2025 (`niemanlab.org/2025/03/fivethirtyeight-is-shutting-down...`; `en.wikipedia.org/wiki/FiveThirtyEight`). `fivethirtyeight.com` and the legacy CSV path (`projects.fivethirtyeight.com/polls/data/senate_polls.csv`) now redirect to `abcnews.com/politics`. GitHub repo `github.com/fivethirtyeight/data` is still public but **abandoned** — last commit `2025-02-25T19:40:27Z` (~19 months stale), confirmed via `api.github.com/repos/fivethirtyeight/data/commits`.
- **Successors identified:**
  - **G. Elliott Morris, "Strength In Numbers"** (`gelliottmorris.com`) + public GitHub repo `github.com/elliottmorris/Strength-In-Numbers-Polls-Public` (last commit `2025-12-26`, ~9 months stale) — GPG-signed, genuinely open, but ships topline/crosstab documents from one pollster partnership, not a full multi-pollster raw-polls CSV.
  - **FiftyPlusOne** (`fiftyplusone.news`) — Morris + Mary Radcliffe's forecast site; per-race poll pages confirmed live and cited directly in Wikipedia's polling tables.
  - **Silver Bulletin / FLIPR**: per its methodology page, *"We draw most of the election polls used in our model from the New York Times poll database... but collect generic ballot and congressional approval polls ourselves."* Public Google-Sheets CSV exports exist for generic ballot and approval specifically (see §3) — **but note the robots.txt ToS flag above.**
- **RealClearPolitics/RealClearPolling**: **No JSON/API endpoint found.** Three independent fetch attempts (plain curl, browser-UA curl, `web_fetch`) all returned **HTTP 403**. `realclearpolling.com` is protected by **DataDome** (confirmed via its challenge-page markers), i.e., commercial anti-bot infrastructure, not just a written policy. RCP's numbers are only obtainable indirectly via Wikipedia's polling tables, which cite `realclearpolling.com/polls/...` as a source.
- **VoteHub** (`votehub.com`, founded Oct 2024 per its `/about/` page, DDHQ/Yale-Youth-Poll alumni team): documents a real API at `votehub.com/polls/api/`; **independently confirmed live and working** at `https://api.votehub.com/polls?poll_type=generic-ballot` (HTTP 200, my own direct test). **However**, `votehub.com/robots.txt` contains this exact clause (verified independently by me, verbatim match to subagent finding): *"All data displayed on this site is the proprietary property of VoteHub. Any scraping, automated collection, or reproduction of our data without prior written permission is strictly prohibited. Unauthorized use may violate applicable law, and we reserve the right to pursue legal action in response."* **→ Technically open, legally prohibited without a license. Contact VoteHub before use.**
- **Wikipedia polling tables**: confirmed current and detailed, e.g. `en.wikipedia.org/wiki/2026_United_States_Senate_election_in_Georgia` has entries through Sept 25, 2026 (aggregating RCP/270toWin/DDHQ/FiftyPlusOne/Silver Bulletin). **Programmatic access via MediaWiki API, tested working**: `en.wikipedia.org/w/api.php?action=parse&page=...&format=json&prop=sections` → get section index → `...&prop=wikitext&section=N` → raw table data. No ToS restriction; this is the officially-sanctioned access method.
- **The Downballot** (correct domain: **`the-downballot.com`**, hyphenated — `thedownballot.com` without the hyphen does not resolve, confirmed independently by me, HTTP 000/DNS failure) — the 2022 successor to Daily Kos Elections' "Ultimate Data Guide." Catalogues results-by-district, special elections, fundraising, race ratings, demographics, etc. — **no raw polling dataset found**. Quoted ToS (permissive): *"We welcome (almost) any use of our data as long as you cite us and include a link to our work... we ask that you please refrain from reproducing entire spreadsheets."*
- **Polls.vote**: **does not exist** — confirmed independently by me (DNS resolution failure) and by the subagent (same failure plus a web search explicitly concluding no such site exists).
- **AP VoteCast**: **discontinued as a standalone brand after 2024.** Per AP's own page (`ap.org/elections/our-role-in-the-u-s-elections/how-we-survey-the-electorate/`): *"AP joined with ABC News, CBS News, CNN, Fox News, MS NOW and NBC News in 2025 to develop The Voter Poll, an evolution of AP VoteCast and traditional exit polling... hired SSRS Inc."* Confirmed from the vendor side (`ssrs.com/ssrs-solutions/voter-poll/`). This consortium product covered the Nov 2025 VA/NJ governor races. Commercial licensing is "contact AP Sales"; no public price list found. `apnorc.org/projects/ap-votecast-puf/` confirms the PUF (academic-use) archive runs "2017-2024" only.

---

## 3. Fundamentals Data

### Generic congressional ballot
**Best source, directly verified by me today**: Silver Bulletin's live page (fetched same-day, "Updated October 2, 2026... D +9.0") publishes a **public CSV** export:
`https://docs.google.com/spreadsheets/d/e/2PACX-1vRsvXNCZ0ubJr8D_yNcU5q6C0_HBa35K7oDK03KpO7Ca43UwdXaIdvVLWoXEmHHph0EREz5430Hm5yZ/pub?output=csv` — subagent confirmed 618 rows w/ pollster, dates, sample size, and house-effect-adjusted figures, `modeldate` = 10/2/2026. **Note**: hosted on `docs.google.com`, not `natesilver.net` — mitigates but doesn't eliminate the ToS concern flagged above (see Section 7). Decision Desk HQ also publishes its own congressional-ballot average (`decisiondeskhq.com/press/...`, dated Jul 15 2026) and — notably — **ingests Kalshi/Polymarket prediction-market data into its model**, directly relevant competitive intelligence.

### Presidential approval
Silver Bulletin's approval tracker has an equivalent public CSV (6,419 rows, broken out by issue: Cost/Immigration/Economy/Trade, most recent entry 10/1/2026). Gallup (`news.gallup.com`) and RCP maintain approval series but offer no free bulk download (Gallup: paid "Analytics" for history; RCP: 403-blocked).

**Why approval matters (best citations, both directly fetched):**
- **Gallup**, `news.gallup.com/poll/242093/midterm-seat-loss-averages-unpopular-presidents.aspx`: presidents **<50% approval → average House loss of 37 seats**; **>50% approval → average loss of 14 seats** (full 1946–2014 table).
- **American Presidency Project (UCSB)**, `presidency.ucsb.edu/analyses/the-2026-midterm-elections-are-historical-data-relevant` (explicitly dated 2026-09-23, i.e., this cycle): correlation of Gallup approval with House seat swing **r=0.58**; applies its regression to 2026 (Trump ~35–37% approval) to predict **~43 House / ~12 Senate seats lost** by Republicans. (This is one model's point estimate, not a consensus — treat as illustrative.)

### FEC API (api.open.fec.gov) — directly verified by me
- **Endpoints** (confirmed via live Swagger spec, 100 paths): candidates, committees, filings, `/v1/efile/*`, **Schedule A** (itemized receipts, by employer/occupation/size/state/zip), **Schedule B** (disbursements), independent expenditures, calendar-dates.
- **Rate limits — discrepancy confirmed directly**: documented policy (`api.data.gov/docs/developer-manual/`) states DEMO_KEY = 30 req/IP/hour; **my own live headers showed `x-ratelimit-limit: 10`**, decrementing fast. **Recommendation: register a free real api.data.gov key immediately rather than relying on DEMO_KEY**, and empirically re-test at expected volume.
- **Posting lag**: FEC's own pages state *"newly filed summary data may not appear for up to 48 hours."* E-filed reports (mandatory for all but the smallest committees) process close to real-time; summary aggregation lags up to 48h.
- **Q3 2026 filing status — directly verified by me via `api.open.fec.gov/v1/calendar-dates/`**:
  ```
  2026-09-20 | Monthly  | September Monthly Report Due
  2026-10-15 | Quarterly | October Quarterly Report Due   ← Q3 2026 (Jul–Sep)
  2026-10-15 | IE Periods | 24-Hour IE Report Period Begins
  2026-10-22 | Quarterly | 12-Day Pre-General Report Due
  ```
  **As of today (2026-10-02), Q3 quarterly filings are NOT yet due** (13 days out). The most recent mandatory quarterly data on file is the April–June "July Quarterly" (due Jul 15, 2026) — i.e., routine campaign-finance data is currently ~3 months stale unless a committee voluntarily files monthly. **Expect a data/volatility cluster around Oct 15 and Oct 22.**

### Candidate filing/withdrawal/retirement tracking
**Best source**: Ballotpedia, `ballotpedia.org/List_of_U.S._Congress_incumbents_who_are_not_running_for_re-election_in_2026` — continuously-edited wiki page (MediaWiki cache-report timestamp `20261002135701`, i.e. rendered same day). Running counts show frequent updates: 66 (Mar 2026) → 69 (Jun 2026) → ~74 (Oct 2026, per WBUR/NPR citing Ballotpedia: `wbur.org/npr/nx-s1-5534254/house-senate-retirement-tracker-2026`). No public Ballotpedia API found — consumable only via the wiki pages (MediaWiki API applies here too, same as Wikipedia).

### Special elections as a swing indicator
Could not verify a stable, dedicated Daily Kos/Downballot special-election tracker URL despite multiple attempts (domain/path guesses 404; `dailykos.com/elections` now redirects to a static image). **Verified working substitute**: **MultiState.us**, `multistate.us/elections/special-elections-2026` — methodology quote: *"we compare the result to the 2024 presidential margin in that same district... We use the median swing as our primary metric."* Current reading: **42 contested 2026 specials, median swing D+10.4** (unweighted) / **D+12.6** (turnout-weighted), explicitly framed by the source itself as *"a thermometer, not a forecast."* Cross-referenced against Cook Political's own caution (`cookpolitical.com/.../how-predictive-are-special-elections`) that specials can reflect hyperlocal rather than national factors.

### Historical midterm penalty
Best citations (both fetched directly, both primary):
- **Gallup**: <50% approval → **−37 House seats avg**; >50% → **−14 seats avg** (same source as above).
- **American Presidency Project (UCSB)**: unconditional average 1934–2022 = **president's party loses 27 House seats / 3 Senate seats per midterm**; of the only 3 midterms since 1936 with sub-40% approval, House losses were 56/28/30 seats.
- **Abramowitz's "Time for Change"** model (*PS: Political Science and Politics*, 1988) is widely miscited for midterms — it's actually a **presidential**-election model. Abramowitz's separate midterm (generic-ballot + seat-exposure) model exists and has been applied to 2026 via Sabato's Crystal Ball, but direct verification was blocked by a 403 — **flagged as not independently confirmed.**

---

## 4. News/Event Sources — Latency

| Service | Tested URL | Result | Verdict |
|---|---|---|---|
| AP | `apnews.com/hub/politics.rss`, `/rss`, `/apf-politics`, homepage | **403 (all)** | No working free RSS at all — blanket Cloudflare bot-block |
| Reuters | `reuters.com/rssFeed/politicsNews` | **401** | `feeds.reuters.com` dead (000); robots.txt explicitly bars "automated means" collection; **no RSS found** |
| **Politico** | `rss.politico.com/politics-news.xml`, `/playbook.xml`, `/congress.xml` | **200, confirmed fresh** (same-day pubDate) | ✅ Best free wire-adjacent source found |
| **Axios** | `api.axios.com/feed/` | **200, confirmed fresh** | ✅ Working, but firehose only (no politics-only vertical feed) |
| Bloomberg Gov't | `about.bgov.com/feed/` | 200 but it's the **corporate blog**, not the BGOV product | Core product is enterprise-only (~$6–15k/seat/yr per third-party trackers, **not BGOV-confirmed**) |
| **Election Law Blog** | `electionlawblog.org/feed/` — **directly re-verified by me**: HTTP 200, pubDate `Fri, 02 Oct 2026 13:20:07 +0000` | ✅ Fresh, on-topic | Best free legal/redistricting-news feed |
| **Democracy Docket** | `democracydocket.com/feed/` → **0 items** (decoy); `democracydocket.com/news-alerts/feed/` → **directly re-verified by me**: HTTP 200, 10 items, pubDate `Fri, 02 Oct 2026 15:28:02 +0000` | ✅ Must use the `/news-alerts/` path specifically | Fastest litigation-tracking feed found |
| Brennan Center | `/rss.xml`, `/feed`, `/feeds/issues/redistricting`, `/rss` | **404 (all 4 patterns)** | No working feed found |
| All About Redistricting | `redistricting.lls.edu/feed/` | 200, but **~3 days stale** at test time | Fine for hourly polling only |

**AP Elections API**: pricing not publicly disclosed anywhere (`developer.ap.org`, `ap.org`, `customerzone.ap.org` all lead to "contact AP Sales"); access requires an AP-issued key (unauthenticated requests return 403). **Confirmed from primary docs**: the API's first standard request returns *"reference information about each race and each candidate"* — i.e., it **does** include pre-election candidate/race metadata, not just election-night results, though a specific "race ready" pre-election milestone timing (secondary-sourced: "several weeks" to "2-3 weeks" before election day) could not be independently confirmed from a readable primary document. **Whether AP will license this to a non-media trading firm is unconfirmed either way** — genuine gap requiring a direct sales inquiry.

**X/Twitter**: Rick Hasen (`@rickhasen`/`@ElectionLawBlog`) is the most-cited canonical election-law account (existence search-confirmed; posting cadence not independently screen-verified — no authenticated browser access in this research). **Correction worth flagging**: Marc Elias reportedly left X in late 2024 per Democracy Docket's own piece "Why I Left X" and now posts primarily via `marcelias.substack.com` — don't rely on an assumption that his X account is still the fast-path source. Dave's Redistricting (`davesredistricting.org`) is a mapping SPA tool with no news feed at all.

**Webhooks**: none of the above support WebSub/PubSubHubbub push. **Polling is the realistic approach.** Zapier's free "RSS by Zapier" polls every 15 min (100 tasks/mo cap); IFTTT free tier is hourly. **Recommendation: poll Election Law Blog + Democracy Docket `/news-alerts/feed/` directly every 1–2 min with conditional `If-Modified-Since`/`ETag` requests and 403-backoff logic** (Democracy Docket intermittently Cloudflare-challenges rapid repeat requests); Politico/Axios every 2–5 min; All About Redistricting hourly; Brennan Center via a self-hosted `changedetection.io` watch (no feed exists).

---

## 5. Redistricting Status (as of 2026-10-02) — the single most important section for 2026 House pricing

**⚠️ Reliability note**: Ballotpedia and Cook Political direct-page fetches were blocked (403) throughout this research; several citations below rely on search-engine synopses of those pages rather than directly-read text, though key facts (dates, vote counts, docket numbers) were cross-checked against more verifiable sources (court opinion PDFs, SCOTUSblog, AP, ACLU, Wikipedia). A handful of lower-profile outlets used for granular figures (e.g., `electiontracker.live`, `political.org`, `hoosierpoliticsnow.wordpress.com`, `lawfold.com`) could not be independently verified as established and should be treated with extra caution.

| State | Status for Nov. 2026 | Key ruling(s) & date | Seats affected | Net effect |
|---|---|---|---|---|
| **Texas** | **FINAL** | SCOTUS stayed district-court block 6-3, *Abbott v. LULAC*, docket 25A608 (Dec 4, 2025); SCOTUS summary reversal on merits (Apr 27, 2026) | 5 (TX-09,28,32,34,35) | ~**+4 R** |
| **California** | In effect, litigation ongoing (DOJ suit + *Noyes*/*Tangipa*, hearing Aug 19 2026, no ruling yet) | 3-judge panel denied injunction (~Jan 14, 2026) | 11 ratings changed | ~**+5 D** |
| **Missouri** | **BLOCKED — 2022 map used.** New map's fate (future cycles only) decided by **Prop A, on the Nov 3 2026 ballot itself** | MO Supreme Court, *von Glahn v. Hoskins*, No. SC101805 (Sept 3, 2026); SCOTUS blocked reinstatement a 3rd time, *People Not Politicians v. Onder*, No. 26A388 (Sept 25, 2026) | 3 (KC-area) | **0 for 2026** (would be +1 R if ever enacted) |
| **Ohio** | **FINAL, no active litigation found** — only state with zero live challenge | Redistricting Commission approved map unanimously (Oct 31, 2025) | 3 (OH-01,09,13) | ~**+2 R** |
| **North Carolina** | **FINAL** | 3-judge panel upheld map (Nov 26, 2025); plaintiffs dismissed suits w/ prejudice (Jan 2026) | 1–2 (NC-01) | ~**+1 R** |
| **Indiana** | **FAILED** (legislative) — old map stands | State Senate voted 31-19 against (Dec 11, 2025) | 0 | None realized |
| **Louisiana** | In effect, remedial proceedings ongoing | SCOTUS struck old 2-majority-Black-district map, *Louisiana v. Callais*, 6-3 (Apr 29, 2026); new SB121/Act 2 enacted | 1 (LA-06) | ~**+1 R** |
| **Utah** | **FINAL** | State judge selected plaintiff map (Nov 10, 2025); Utah Supreme Court dismissed legislature's appeal (~Feb 20, 2026) | 1 | ~**+1 D** |
| **Florida** | In effect, litigation continues | FL Supreme Court declined emergency block (Jun 10, 2026) | 6 Dem-held districts targeted | ~**+4 R** |
| **New Hampshire** | **FAILED** — shelved before introduction (Oct 30, 2025) | 0 | None realized |
| **Alabama** (not on original list) | Functionally final via SCOTUS stay, merits appeal still pending | SCOTUS reinstated 2023 map, *Allen v. Caster* line, stay granted Jun 2, 2026 | 4 | ~**+1 R** |
| **Tennessee** (not on original list) | In effect, injunction denied, appeal vowed | Federal panel denied PI (Jul 23, 2026) | 3 (dismantled Memphis TN-09) | ~**+1 R** |
| **Virginia** (not on original list) | **FAILED** — VA Supreme Court voided the Dem-backed amendment 4-3, *Scott v. McDougle* (May 8, 2026) | 0 | None realized (would've been +4 D) |
| **South Carolina** (not on original list) | **FAILED** — State Senate 29-17, two votes short (May 12, 2026) | 0 | None realized |
| **New York** (not on original list) | **BLOCKED** — SCOTUS stayed state-court-ordered redraw of NY-11, *Malliotakis v. Williams*, 25A914 (Mar 2, 2026) | 0 | None realized |

**Considered, not enacted**: Wisconsin, Georgia (special session Jun 2026, no map), Nebraska, Kansas, Illinois, Maryland.

**Overall estimate**: Sabato's Crystal Ball (`centerforpolitics.org/crystalball/taking-stock-of-the-2026-house-map-an-update/`, ~Jun 10, 2026, via Wayback): **10 states (~40% of all House seats) redrew maps; competitive seats fell from 85 to 70; net Republican structural gain of roughly 5–9 seats.** Cook Political's 2026 PVI release and Axios (Jun 7, 2026) reportedly concur directionally (both direct-fetch-blocked, cited via search synopsis; Axios figure: "net GOP gain of at least 10"). A bottom-up tally from the per-state figures above (TX+4R, OH+2R, NC+1R, FL+4R, AL+1R, TN+1R, LA+1R ≈ +14R, offset by CA≈+5D, UT+1D ≈ −6D) nets to **≈+8 R** — broadly consistent. **Use +5 to +10 net Republican seats as the working consensus range**, against ~70 genuinely competitive seats of 435 total.

**Genuinely unresolved as of today**: Alabama's merits appeal, California's DOJ suit, Tennessee's appeal, Louisiana's remedial-proceeding scheduling, and — uniquely — **Missouri's Prop A is literally decided on the same ballot as the midterms**, affecting only 2028+ maps, not Nov 2026 itself.

---

## 6. Ratings-to-Probability Calibration

**No single, universally-adopted calibration standard exists** — but real, rigorous, converging empirical work does:

| Source | Category | Empirical win rate (favored party) | Scope |
|---|---|---|---|
| Campbell (2010), `acsu.buffalo.edu/~jcampbel/documents/CookAccuracySummary.pdf` | Solid | **99.8%** | Cook House ratings, 1984–2008, n=3,387 |
| " | Likely | **94.9%** | n=641 |
| " | Lean | **85.7%** | n=441 |
| " | Toss-up | **49.2–55.0%** | n=290 |
| Cook's own 40th-anniversary self-audit (2024, via Wayback) | Solid/Likely/Lean | **~100% / ~97% / ~94%** | Full 40-yr/10,374-race archive, all offices |
| **Split Ticket**, `split-ticket.org/2024/05/29/whats-in-a-rating/` | Cook "Lean" / "Likely" | **>95% / >97%** | 2016–2022 cycles |
| " | **Sabato "Lean"** | **77%** | same |
| " | **538 "Lean"** (designed for 60–75%) | **78%** | same |
| " | 538 "Likely" | 92% | same |

**Non-comparability is the central, well-documented finding**, not a suspicion: Split Ticket's direct quote: *"Given the lack of standardized definitions, different forecasters have actually adopted significantly differing interpretations for each category."* **Live 2026 illustration**: Nate Silver's Sept 20, 2026 post (`natesilver.net/p/expert-ratings-are-ignoring-signs`, mirrored at `politicalwire.com/2026/09/20/...`) defines FLIPR's own toss-up as *"all races where neither party has more than a 60 percent chance,"* then notes *"Cook Political Report... counts seven races as 'toss-ups,' including states like New Hampshire where models and prediction markets imply that Democrats are heavy favorites."* — a dated, real-money example of exactly this calibration gap.

A current but lower-reliability aggregator, **PoliAgg** (`poliagg.com`, self-described single-editor/machine-drafted site), publishes a live bucket-by-bucket table against an assumed 95/80/65/55/50% scale, confirming Cook/Sabato "Safe" and "Lean" favorites win even more often than that assumed scale implies — directionally consistent with Campbell/Cook but **not citable as an industry standard** (some cells have N as low as 1).

**If the bot needs a working default**: use Campbell/Cook's pooled figures (Solid≈99%, Likely≈95%, Lean≈85–90%, Toss-up≈50%±wide cycle variance) as the baseline for **Cook/CPR-style ratings specifically**, but **apply a materially lower probability (~77–78%) for "Lean" from Sabato or any 538-style/FiveThirtyEight-descended source** — these are not interchangeable despite identical labels. A 2025 peer-reviewed paper, Franz & Robinson, *Social Science Quarterly* 106(7) (DOI: 10.1111/ssqu.70117), extends this to 1964–2022 but is paywalled — per-category figures from it could not be verified.

---

## 7. Practical Recommendation

### Ranked top 5 (value ÷ ingestion effort), with explicit automated-access verdicts

| Rank | Source | Why | Automated access |
|---|---|---|---|
| **1** | **FEC API** (`api.open.fec.gov`) | Only free, structured, government-authoritative fundamentals feed (finance momentum, IE spending surges); event-driven value spikes around Oct 15 & 22 | ✅ **Permitted** — register a real key (free), don't rely on DEMO_KEY |
| **2** | **Wikipedia MediaWiki API** | Free meta-aggregator of polls (via RCP/270toWin/DDHQ/Silver Bulletin citations), retirements, and redistricting context for all 237 contracts' underlying races | ✅ **Permitted** — official access method, zero restriction |
| **3** | **Election Law Blog + Democracy Docket `/news-alerts/feed/`** | Lowest-latency, free, confirmed-fresh (minutes-old) feeds for exactly the redistricting/court-ruling risk that's unusually decisive in 2026 | ✅ **Permitted** — poll every 1–2 min with backoff |
| **4** | **Decision Desk HQ + Race to the WH content pages** (not their API/JSON-shortcut paths) | Only genuinely probabilistic (Monte Carlo, not qualitative) forecasts covering all 3 chamber types, intraday/daily updates — the closest direct analog to the bot's own pricing task, useful as a cross-check/consensus signal | ✅ **Permitted on HTML content**; their `/api/` paths are explicitly disallowed/commercial — don't call them without a paid agreement |
| **5** | **StateNavigate (ex-CNalysis) API** | Only source with documented state-legislative + gubernatorial + campaign-finance JSON/CSV, useful if the 237 contracts include down-ballot races | ✅ **Permitted** — requires free/paid API key registration |

### Sources to explicitly AVOID scraping (high value, but ToS-restricted or infra-blocked)

| Source | Restriction | Quoted clause / evidence |
|---|---|---|
| **VoteHub** (`votehub.com`/`api.votehub.com`) | ❌ Explicit written prohibition despite technically-open API | *"Any scraping, automated collection, or reproduction of our data without prior written permission is strictly prohibited... we reserve the right to pursue legal action."* (robots.txt, independently verified) — **get a license first** |
| **Silver Bulletin** (`natesilver.net`) | ❌ Named AI-bot block + paywall | robots.txt: `Disallow: /` for `ClaudeBot`, `GPTBot`, `anthropic-ai`, etc.; `Content-Signal: ai-train=no` | 
| **The Hill / any Nexstar property** | ❌ Explicit ToU ban | *"Scrape, data-mine or data-crawl... Use any Content to create, train... AI product"* — prohibited conduct per `nexstar.tv/terms-of-use/` |
| **RealClearPolitics/Polling** | ❌ De facto blocked (DataDome), ToS text itself unreachable | 403 on every tested access pattern, from multiple user-agents |
| **Reuters** | ❌ Explicit ToS + no RSS | robots.txt bars automated collection without consent; no working feed found at all |
| **Sabato's Crystal Ball / Cook Political Report** | ⚠️ Infra-blocked (Cloudflare), CPR confirmed subscriber-gated at race level | Could not retrieve ToS text directly; use Wayback snapshots or a licensed subscription, not live scraping |

### Key uncertainties/gaps flagged honestly
- JHK Forecasts, The Economist, PollyVote, and any Gelman/Linzer 2026 model: **no live 2026 content found** — deprioritize.
- AP Elections API and AP VoteCast successor ("The Voter Poll"/SSRS): **pricing and eligibility for a non-media commercial/trading entity is not publicly confirmed** — requires a direct sales inquiry.
- FEC DEMO_KEY rate limit: documented 30/hr vs. **directly observed 10**, window length unconfirmed — test empirically after registering a real key.
- Franz & Robinson (2025) per-category calibration numbers: paywalled, unverified.
- Several redistricting figures (Cook PVI, Axios aggregate estimate, some state-level news) came from search synopses because the primary pages 403-blocked direct fetch — dates/case-names were cross-checked against court documents and wire reporting, but treat the precise seat-count estimates as a converging range (+5 to +10 R), not a single hard number.
- X/Twitter account activity could not be screen-verified (no authenticated browser access in this research); existence only, not live posting cadence.