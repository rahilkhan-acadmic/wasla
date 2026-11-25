# Event Breakout: trading momentum after scheduled macro events

*Research note, 2026-11-25. A new section of the project, separate from the
distress model. Research and strategy design only: nothing here has been
backtested yet, and none of it is investment advice. SEBI's own study found
93% of individual F&O traders lost money over FY22-FY24 ([Outlook Business][sebi-loss]).*

## 1. The idea

Scheduled events (RBI policy, US Fed (FOMC) meetings, the Union Budget)
reliably move markets, but the direction is hard to call in advance. A
**post-event breakout** strategy doesn't guess. It waits for the news,
lets the first reaction set a price range, and trades only if price then
breaks out of that range, on the bet that a real repricing keeps going.

Markets in scope: **Nifty 50** (plus Bank Nifty for rate events) and
**Bitcoin**. Both went through repeated pullbacks in 2021-2026 driven by
rates, inflation, geopolitics and liquidity squeezes.

## 2. The events and when they land (IST)

| Event | How often | Release time (IST) | Second stage | Nifty open? | Bitcoin |
|---|---|---|---|---|---|
| **RBI MPC decision** | 6 a year | 10:00, Governor's statement ([Business Standard][rbi-time]) | Press conference 12:00 | Yes, intraday | 24/7 |
| **FOMC decision** | 8 a year | 23:30 IST (US summer time) or 00:30 IST (US winter time): 2:00 pm ET | Fed Chair press conference 30 min later | **No**: closed; reaction arrives as the next morning's gap | 24/7, reacts live |
| **Union Budget** | 1 a year, Feb 1 | Speech from 11:00, ~90 min | The speech itself (news arrives over 1.5 h) | Yes; special session if Feb 1 is a weekend (Sat 2025, **Sun 2026**) ([NSE circular][nse-budget]) | 24/7, little reaction |

The RBI schedule is published a year ahead ([Business Standard][rbi-sched]): FY26 was
Apr 9, Jun 6, Aug 6, Oct 1, Dec 5 and Feb 6. The Fed publishes its own.

## 3. What the evidence says

**Size of the move depends on surprise, not the event itself.**
- RBI: a 2024 RBI working paper finds the *unanticipated* part of policy
  (measured from overnight swap rates) moves Indian equities, with both
  the rate surprise and the guidance surprise raising volatility
  ([RBI WP 03/2024][rbi-wp]).
- Earlier Indian work (Patra & Kapur, 2012, as summarised in later
  papers; not checked against the original) finds predictable decisions
  move the NSE far less than unexpected ones.
- Feb 2025 is an example: the rate cut was expected, but Nifty fell
  because RBI cut its growth forecast. **The guidance moved the market,
  not the rate** ([GoodReturns][rbi-feb25]).

**The first move is not always the real one.**
- Fed: a study of S&P 500 futures finds that on FOMC days *with a press
  conference*, the first move after the statement is followed by a
  **reversal of about 60 bp lasting several hours**; days without a press
  conference show no reversal ([Martineau][martineau]).
- Under Powell, stocks and bonds have often reversed their statement
  reaction during the press conference ([CEPR/VoxEU][cepr]).
- Other work finds the two reactions mostly point the same way
  ([Gómez-Cram & Grotteria][gcg]). **The evidence is split; treat the
  first move as unconfirmed.**

**Budget day: big swings, small close.**
- Since 2010 the average Nifty close-to-close move on Budget day is about
  **0.19%** ([Business Today][bt-budget]). The average intraday range is
  about **2.65%** ([Research360][r360]).
- The direction of the close has no consistent pattern ([SAMCO][samco]).
- Moves are often sharp in the first hours and then fade
  ([Business Today 2021][bt-2021]).
- Some analysts find the real trend shows up in the week *after* the
  Budget (average +1.36% in one study) ([Research360][r360]).

**Implied volatility collapses after the event.**
- India VIX typically rises into the Budget and RBI policy, then drops
  once the news is out ([BloombergQuint][vix-2017], [Business Standard][vix-2019]).
- So buying options *after* an event means paying for volatility that is
  about to disappear.

**Momentum after news is real, at least in the US.**
- On the S&P 500, the first half hour's return predicts the last half
  hour's, and this effect is **stronger on major macro-news days**
  ([Gao, Han, Li & Zhou, JFE 2018][gao]).
- A 1-minute SPY study finds a post-announcement trend lasting about 49
  minutes ([Fordham thesis][fordham]).
- These results support the breakout idea. India-specific intraday
  evidence is thin: one RBI study even notes *slow* price adjustment in
  Indian markets ([RBI WP][rbi-wp]), which could help a breakout approach
  if the slowness is real.

**Bitcoin: volatility reliably, direction not.**
- BTC volatility is higher in the hour before and the hour of FOMC
  announcements, but the direction is inconsistent ([Interdax][interdax]).
- Academic results are mixed: FOMC decisions don't affect crypto
  uniformly ([Vaasa thesis][vaasa]), while rate hikes hurt BTC in hourly
  data ([arXiv 2311.10739][arxiv]).
- 7-day BTC returns after each meeting ranged from +6.9% to −8%
  ([Cointelegraph][ct-fomc]).
- Leverage builds into events, so moves are amplified and **whipsaws
  clear out both sides**: over $500M was liquidated in one post-CPI
  reversal ([Decrypt][decrypt]).

**Before the Fed, US stocks drift up.** US equities have earned large
excess returns in the 24 hours *before* scheduled FOMC announcements
([Lucca & Moench, JF 2015][lucca]). That is a separate, pre-event effect,
noted here because it inflates "event day" statistics.

## 4. Gaps: what a simple "trade the post-event breakout" misses

| # | Gap | Why it matters | How the strategy handles it |
|---|---|---|---|
| G1 | **Time zones** | The Fed decides while NSE is closed. There's no intraday breakout to trade in Nifty, only an opening gap at 9:15. | Separate "gap" rule for Nifty after FOMC; Bitcoin is traded live. |
| G2 | **Two-stage releases** | RBI 10:00 + 12:00, FOMC statement + press conference. The first move is often revised, sometimes reversed (~60 bp in the S&P 500 study). | Build the range across *both* stages; don't trade the first reaction. |
| G3 | **Budget is a 90-minute release** | News arrives gradually; mid-speech breakouts whipsaw. The day's net move is tiny compared with its range. | No trades during the speech; higher breakout bar and half size; test the post-Budget-week trend separately. |
| G4 | **No surprise measure** | Expected events barely move the market. Trading every event unconditionally means many false breakouts on non-events. | Record a surprise flag per event (decision vs consensus, rate *and* guidance); require an actual breakout, not just "event day". |
| G5 | **Implied volatility collapse** | Options bought after the event lose value as volatility falls. | Prefer futures (or BTC spot/perps at low leverage); options only as defined-risk spreads. |
| G6 | **Liquidity and slippage** | Spreads widen right after releases; BTC wicks trigger stops through liquidations. | Enter on a candle *close* beyond the range plus a buffer, not on a touch; stops beyond the range plus a buffer; assume slippage in the backtest. |
| G7 | **Overlapping and unscheduled shocks** | RBI week near US CPI; Budget week; wars and oil shocks (2022, 2026) swamp scheduled events. | Skip if another top-tier event falls within ±1 day; record unscheduled shocks and exclude or flag them. |
| G8 | **Rules and costs (India)** | Since Nov 2024: one weekly index expiry per exchange, minimum contract value ₹15 lakh ([Zerodha][zerodha-fo], [Outlook][sebi-loss]); STT and brokerage. | Size in whole contracts at the real minimum; include costs in every backtest; note expiry-day overlap. |
| G9 | **Too few events** | ~6 RBI + 8 FOMC + 1 Budget a year is **~75 events in 5 years**, and only 5 Budgets. Easy to overfit. | Few parameters, fixed in advance; compare with the same rules on random non-event days; out-of-sample period; paper trade before any money. |
| G10 | **Data** | Nifty 1-5 minute history for 5 years isn't freely available (Yahoo intraday only goes back ~60 days); BTC minute data is easier to get (exchange APIs). | Phase 1 uses daily data (gaps, ranges, next-day follow-through); intraday Nifty rules need a data-source decision (see §7). |
| G11 | **Evidence base** | Most strong studies are US equities; Indian evidence is mostly broker blogs. | Treat Indian figures as hypotheses to test, not facts. |

## 5. The strategy: Event Breakout v1

### Common rules (all events)
1. **Stand aside before the event:** no new position from 30 min before
   the release until the range is set.
2. **Reference range:** high and low over a fixed window that covers
   *every* stage of the release (see the per-event table).
3. **Entry:** a candle **closes** beyond the range by a buffer of
   `k × ATR` (ATR on the same timeframe, k = 0.25 to start). One trade per
   event per instrument, in the breakout's direction.
4. **Skip filters:**
   - range < 0.5 × ATR(daily), a non-event;
   - range > 2.5 × ATR(daily), the move already happened and chasing it
     is poor value;
   - another top-tier event within ±1 day.
5. **Stop:** the opposite side of the range (or the range midpoint if the
   range is wide), plus the buffer.
6. **Target and exit:** take half off at 1.5R, trail the rest by the
   range midpoint. **Time stop:** Nifty flat by 15:15 the same day;
   Bitcoin within 24 h.
7. **Size:** risk a fixed 0.5% of capital per trade (stop distance ×
   size). Never add to a losing trade.

### Per-event rules

| Event | Instrument | Range window | Entry window | Notes |
|---|---|---|---|---|
| **RBI MPC** | Nifty fut, Bank Nifty fut (more rate-sensitive) | 10:00 to 12:30 (decision **and** press conference) | 12:30 to 14:30, 15-min close | If the decision is a real surprise (rate or stance vs consensus), allow an early range of 10:00-10:30 with half size. |
| **FOMC → Nifty** | Nifty fut | Next day's opening range, 9:15 to 9:45 | 9:45 to 11:00, 15-min close | Trade only if the opening gap is > 0.5% **and** the breakout is in the gap's direction ("gap and go"); otherwise no trade. |
| **FOMC → Bitcoin** | BTC spot / low-leverage perp | 2:00 to 3:15 pm ET (statement + press conference) | 3:15 pm to 9:00 pm ET, 15-min close | Require **two** consecutive closes beyond the range (liquidation wicks); skip if funding is extreme in either direction. |
| **Union Budget** | Nifty fut | Speech start to end (~11:00 to 12:30) | Speech end to 14:30, 15-min close | Half size, k = 0.5 (the day tends to revert). **Separate test:** hold in the direction of Budget day's close for the next 5 sessions. |

### What would make us drop it
Compared with the same rules on random non-event days, if after costs the
event version doesn't show a **positive average R and a better hit rate**
over the 2021-2024 events, and then hold up on 2025-2026, the edge isn't
there and the strategy is shelved.

## 6. Validation plan
1. **Event calendar** 2021-2026. **Done:** `data/events/macro_events.json`
   lists 92 events (37 RBI, 48 FOMC, 7 Budgets), each with its time in IST
   (DST-aware for the Fed), decision, rate after the decision and a source;
   validated by `tests/test_macro_events.py`. Still open: a sourced
   **consensus/surprise** per event. Only two RBI surprises are flagged so
   far, and `null` means "not assessed", not "no surprise". All 36 past RBI
   decisions were checked against RBI's own Governor's Statements
   (2026-11-25): dates and rates match, and each entry now links its
   statement.
2. **Daily-data study (no new data source needed):** for each event,
   Nifty, Bank Nifty and BTC open/close gap, intraday range, and
   close-to-close moves for 1 and 5 days, against non-event days.
   Answers the questions for G1, G3, G4 and G9.
3. **Intraday backtest:** BTC first (minute data obtainable), Nifty once
   G10 is solved. Costs and slippage included. Split 2021-2024 to build,
   2025-2026 to test.
4. **Paper trade** at least one quarter (2 RBI, 2-3 FOMC, maybe the
   Budget) before any real money.

## 6a. Daily-data study: results (2026-11-25)

Data: NSE's own daily index files, 2020-12-01 to 2026-11-23 (1,478 trading
days; Nifty 50, Nifty Bank, India VIX; `data/events/index_daily.csv`,
cross-checked against NSE's bhavcopy MCP). 90 past events. Code:
`src/event_study.py`; numbers: `data/events/event_study_results.json`.
Each event is compared with ordinary days (event days ±1 excluded); "p"
is how often random ordinary days look as extreme (bootstrap).

**Q1 size: only the Budget moves the market more than an ordinary day.**

| Nifty 50 | events | avg move | vs ordinary | avg range | vs ordinary |
|---|---|---|---|---|---|
| FOMC (next session) | 47 | 0.70% | ×1.08 (p 0.27) | 1.05% | ×1.03 |
| RBI | 36 | 0.72% | ×1.11 (p 0.23) | 1.05% | ×1.03 |
| **Budget** | 7 | **1.24%** | **×1.91 (p 0.02)** | **2.61%** | **×2.57 (p<0.001)** |

Bank Nifty is the same picture (Budget range ×2.8; RBI range ×1.15, p 0.05).
RBI and FOMC days are, on daily data, ordinary days.

**Q3: after the Fed, Nifty's opening gap mostly faded, not followed.** Of
47 FOMC mornings, 24 gapped by more than 0.5%; the rest of the day went
*against* the gap 16 times and with it 8 (ordinary days: about 50/50). But
the fade is almost all 2021-2023 (12 of 17); 2024-2026 is 3 fade / 4 go of
7. **Not a reliable edge either way**, and picking "fade" after seeing it
would be fitting noise.

**Q4 Budget: big range, small close.** Average range 2.61% against a 1.24%
close; 4 of the last 5 Budgets closed within ±0.3% after ranges of
0.8-3.5%. The exception is 2021 (+4.7%, then +5.8% more over 5 days).

**Q5 India VIX: the volatility crush is real.** On the reaction day VIX
falls on average −1.5% (FOMC, p 0.004), −2.1% (RBI, p 0.003) and **−6.8%
(Budget, p<0.001)**, against +0.4% on ordinary days. Before the Budget VIX
rises ~5% over 3 days (p 0.07). Options bought into or right after an
event pay for volatility that then drops.

**Strategy trade outcomes (daily proxies, after 5 bp costs):**

| Rule (daily proxy) | Nifty 50 | Bank Nifty | Ordinary days |
|---|---|---|---|
| FOMC gap-and-go | **8 W / 16 L**, avg −0.30% | **5 W / 20 L**, avg −0.61% | ~50% win, ~0% avg |
| RBI follow-through (next day) | 17 W / 19 L, avg −0.11% | 15 W / 21 L, avg −0.27% | ~52% win |
| Budget follow-through (next day) | 4 W / 3 L, avg +0.34% | 4 W / 3 L, avg +0.81% (p 0.03) | ~52% win |

**What this means for v1:**
1. **Drop "FOMC → Nifty gap and go".** It lost on daily data in both
   indices. Its fade looks tempting but isn't stable across periods.
2. **RBI: no daily edge.** Any edge would have to be intraday (around the
   10:00 and 12:00 releases), which needs intraday data, or come from
   *surprise* decisions only (step 3, FBIL).
3. **Budget is the one event with an unusual daily footprint**: a wide
   range and a tendency to give back the move by the close. Only 7 events:
   promising, not proven.
4. **Volatility selling, not buying, is what the data favours around
   events** (VIX crush). That's a different, riskier strategy; noted, not
   adopted.
5. Bitcoin and intraday Nifty are still untested (steps 4-5).

## 7. In the project: proposed "Event Watch" page
A fifth dashboard page, separate from the distress model:
- **Upcoming events:** RBI, FOMC, Budget, with countdown and IST time.
- **Event history:** per event, how Nifty / Bank Nifty / BTC moved: gap,
  range, 1-day and 5-day follow-through, the surprise flag.
- **Strategy results:** the backtest summary from §6, kept honest
  (number of events, hit rate, average R, worst drawdown, comparison with
  random days).

**Data:** daily prices for `^NSEI`, `^NSEBANK` and `BTC-USD` through the
same yfinance path the market snapshot already uses; the event calendar as
a curated JSON. **Open decision:** a source for 5 years of Nifty
intraday data. Options: a paid vendor, broker historical APIs, or the
daily-data study only.

## Sources
- [Lucca & Moench, The Pre-FOMC Announcement Drift (NY Fed SR 512 / JF 2015)][lucca]
- [RBI WP 03/2024, Equity Markets and Monetary Policy Surprises][rbi-wp]
- [GoodReturns, market fall after Feb 2025 rate cut][rbi-feb25]
- [Business Standard, MPC announcement 10 am, press conference noon][rbi-time]
- [Business Standard, RBI MPC schedule for FY26][rbi-sched]
- [Martineau, FOMC press conferences and price reversals (abstract)][martineau]
- [CEPR/VoxEU, market impact of the Fed press conference][cepr]
- [Gómez-Cram & Grotteria, real-time price discovery via verbal communication][gcg]
- [Gao, Han, Li & Zhou, Market Intraday Momentum, JFE 2018][gao]
- [Predicting intraday S&P 500 returns after monetary policy announcements][fordham]
- [Business Today, Budget-day returns since 2010][bt-budget]
- [Business Today, Budget-day moves over 10 years][bt-2021]
- [Research360, pre/post-Budget Nifty trends][r360]
- [SAMCO, 25 years of Budget-day volatility][samco]
- [BloombergQuint, India VIX Budget-day fall 2017][vix-2017]
- [Business Standard, India VIX after Budget 2019][vix-2019]
- [Business Standard, Sunday 1 Feb 2026 special session][nse-budget]
- [Interdax, FOMC and Bitcoin][interdax]
- [University of Vaasa thesis, FOMC and crypto][vaasa]
- [Monetary policy and the cryptocurrency market (arXiv 2311.10739)][arxiv]
- [Cointelegraph, BTC after FOMC outcomes][ct-fomc]
- [Decrypt, post-CPI whipsaw liquidations][decrypt]
- [Zerodha, SEBI weekly expiry rules][zerodha-fo]
- [Outlook Business, SEBI F&O rules and the 93% loss study][sebi-loss]

[lucca]: https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr512.pdf
[rbi-wp]: https://website.rbi.org.in/documents/87730/30842423/WPS+No.+03+2024+Equity+Markets+and+Monetary+Policy+Surprises.pdf
[rbi-feb25]: https://www.goodreturns.in/news/stock-market-crashed-after-rbis-25-bps-rate-cut-why-sensex-nifty-are-falling-on-february-7-1404759.html
[rbi-time]: https://www.business-standard.com/economy/news/october-mpc-meeting-when-and-where-to-watch-the-rate-decision-live-125093000293_1.html
[rbi-sched]: https://www.business-standard.com/economy/news/rbi-announces-mpc-schedule-for-fy26-first-rates-decision-on-april-9-125032600957_1.html
[martineau]: https://ies.keio.ac.jp/upload/20190716macro_Martineau_abstract-1.pdf
[cepr]: https://cepr.org/index%2ephp/voxeu/columns/market-impact-fed-press-conference
[gcg]: https://lbsresearch.london.edu/id/eprint/2203/1/SSRN-id3613702.pdf
[gao]: https://econpapers.repec.org/RePEc:eee:jfinec:v:129:y:2018:i:2:p:394-414
[fordham]: https://research.library.fordham.edu/gabelli_thesis/161
[bt-budget]: https://www.businesstoday.in/markets/stocks/story/nifty-bank-nifty-budget-day-stock-market-returns-since-2010-full-table-512707-2026-01-23
[bt-2021]: https://businesstoday.in/markets/market-perspective/union-budget-2021-how-sensex-nifty-moved-on-budget-day-in-last-10-years/story/429363.html
[r360]: https://www.research360.in/blogs/pre-budget-2026-market-trends
[samco]: https://www.samco.in/knowledge-center/?p=64393
[vix-2017]: https://www.bloombergquint.com/amp/charts/2017/02/02/india-vix-sees-biggest-budget-day-fall-in-9-years
[vix-2019]: https://www.business-standard.com/amp/article/markets/india-vix-retreats-despite-sharp-fall-in-market-in-the-past-few-weeks-119072800705_1.html
[nse-budget]: https://www.business-standard.com/budget/news/budget-2026-bse-nse-trading-session-sunday-february-1-time-126011601035_1.html
[interdax]: https://medium.com/interdax/how-do-fomc-announcements-affect-bitcoin-9f975de87cb3
[vaasa]: https://osuva.uwasa.fi/bitstreams/50105245-0992-4f34-b16a-b9e7888d49d7/download
[arxiv]: https://arxiv.org/pdf/2311.10739
[ct-fomc]: https://cointelegraph.com/news/short-the-dip-and-buy-the-rip-what-fomc-outcomes-reveal-about-bitcoin-price-action
[decrypt]: https://decrypt.co/352978/bitcoins-post-cpi-whipsaw-liquidates-over-500m-again
[zerodha-fo]: https://zerodha.com/z-connect/updates/sebis-new-rules-on-weekly-index-derivatives-expiry
[sebi-loss]: https://www.outlookbusiness.com/markets/how-sebis-new-rules-to-curb-fo-market-madness-will-impact-investors
