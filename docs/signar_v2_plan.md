# Signar v2 — Backtest Findings & Code Changes

Handoff doc for implementing v2 changes after the 2026-08-01 backtest
(cycle one: frozen scoring `2026-06-10-float-aware-v1`, forward holdout
2026-06-10 → 2026-07-31, 1,541 flags, 370 tickers).

---

## 1. What the backtests showed

**The score carries no information.** Top-5-by-score vs 500 random same-day
baskets: percentile 44–52 at every horizon (T+1 → T+30). Score buckets are
flat at T+30 (~−20% avg regardless of bucket). `best_trade_candidate` cohort
underperformed `radar_watchlist` and even `avoid_high_risk` at most horizons.

**The tuned multipliers were harmful.** Shadow variants scored on identical
rows: FLAT-both curves beat the production curves at T+14 (−12.15% vs −15.34%).
The 10–20 mention "sweet spot" (1.18x) and neutral-sentiment (1.15x)
multipliers were noise fitted on early data. Mention buckets: Low (5–10)
beat Sweet (10–20) at every horizon; Viral (>20) worst (−31.9% T+30).

**Anti-chase is the one validated component.** Monotonic gradient at T+14:
down/flat entries −11.5% vs Up>20% entries −25.2%. Chasing is genuinely
punished. Keep it.

**Winners are indistinguishable from losers.** Within-cohort discrimination
(17 numeric + 4 categorical features, winners ≥+20% vs losers ≤−20%, both
T+14 and T+30): no feature separates. Same distributions on mentions,
authors, risk, price action, float, everything. Re-weighting existing
features cannot work — there is nothing to re-weight toward.

**Two open leads (untested, not findings):**
- *Repeat appearance:* tickers that eventually ran averaged 3.26 flag-days vs
  2.58 for the rest. Winners recur (SKYQ ×3, COSM, MGRX, OTLK, RGNT).
  Cross-day dynamics (mention velocity, author-set evolution) are the largest
  unexplored region. Note: static `days_trending` did NOT separate.
- *Horizon shape:* big winners peak at T+3/T+7 and decay (SDOT +718%→+172%,
  CAST +535%→+80%). Nothing has tested short-horizon pop prediction yet.

**Universe context:** the whole corpus drifts ~−6% T+7 / −13% T+14 / −21%
T+30. Sub-penny structural collapses (reverse splits, delistings) must stay
excluded from all return stats.

---

## 2. Code changes for v2

### 2.1 Scoring simplification (main.py) — REQUIRED
- **Remove** the mention sweet-spot multiplier (the 10–20 → 1.18x curve).
  Replace with flat 1.0 (i.e., delete the multiplier from the score path).
- **Remove** the neutral-sentiment timing multiplier (1.15x band). Flat 1.0.
- **Keep** anti-chase multipliers unchanged (validated).
- **Keep** risk gates, avoid/cohort routing, dilution/promotion detection
  unchanged (the avoid layer is the product's working discipline function).
- **Bump** `scoring_version` to a new string, e.g.
  `2026-08-XX-simplified-v2`, and freeze again. No other scorer edits.

### 2.2 Cross-day feature instrumentation — REQUIRED (measurement only)
Log these into tracking tables so they accumulate for the next evaluation.
Do NOT wire them into scoring yet.
- `mention_velocity_num`: today's mentions ÷ yesterday's mentions for the
  same ticker (NULL if not seen yesterday).
- `author_overlap`: Jaccard overlap between today's author set and the
  ticker's previous flag-day author set (NULL if first appearance).
- `flag_sequence`: integer — how many times this ticker has been flagged
  (1 = first appearance, 2 = second, ...).
- Store all three per row in `performance_tracking` (or a joined table) at
  record time.

### 2.3 Pre-registered v2 hypotheses (write into repo, evaluate ~mid-Sept)
Evaluate ONLY on data collected after the v2 freeze; never on cycle-one data:
1. Does `flag_sequence >= 3` predict better T+14 outcomes than
   `flag_sequence == 1`?
2. Does rising `mention_velocity_num` with rising `author_overlap`-diversity
   (new authors joining) predict T+3/T+7 pops ≥ +20% at better than base
   rate (~10–15%)?
3. Do the simplified-v2 cohorts beat random same-day baskets (percentile
   > 60) at T+7?
4. Does the combined `avoid_high_risk` + `vampire_flagged=1` cohort
   underperform the rest of the same-day flagged universe by at least 3
   percentage points in median daily T+14 spread?
5. Do flags with `author_hist_avg_t7 > 0` and
   `author_hist_coverage >= 0.5` outperform flags with
   `author_hist_avg_t7 <= 0` at T+7?

Hypotheses 4 and 5 are measurement-only. Avoid/vampire names remain warnings,
not trade recommendations. Even if hypothesis 4 passes, only a separately
logged Alpaca paper-short cohort may be considered; real short trades and UI
short recommendations are out of scope.

### 2.4 Infra hardening (fetch pipeline)
- Remove the 90-minute duplicate-run guard in the GitHub Actions workflow;
  add automatic retry (1 retry, ~30 min later) when the fetch job fails.
- Raise hard-block retry budget for the listing stage (currently 3 fresh-IP
  retries via `HARD_BLOCK_BACKOFFS`) to ~6 attempts for listings only.
- Optionally test `X-Oxylabs-Geo-Location: United States` header to reduce
  Reddit "Welcome" interstitial rate. Do NOT enable rendering (breaks JSON).
- Add retry-with-backoff around yfinance calls in price enrichment
  (`enrich_with_price`) — a rate-limit day silently dropped ~85% of
  recordings once (2026-07-01).
- Persist run summaries to a file on the Railway `/data` volume (Railway
  deletes logs after ~7 days).

### 2.5 Backtest/analysis (already done, keep)
`backtest.py` already contains: sub-penny return exclusion, `scoring_version`
join + version-mixing banner, fixed `ablation_market_confirmation`, shadow
flat-curve variants, resolution-quality section, continuation-vs-exhaustion
section. `t30_analysis.py` and `cohort_discrimination.py` exist for winner
analysis. Only addition: filter the −999 sentinel from intermediate horizon
columns (`return_t14` etc.) in `t30_analysis.py` display.

### 2.6 Explicitly do NOT do
- Do not re-tune or add scoring multipliers to improve the cycle-one
  backtest (overfitting; the features don't separate winners from losers).
- Do not add ML models (gradient boosting etc.) until some feature shows
  predictive life.
- Do not change subreddit list, universe filters, or horizons mid-window.
- Do not evaluate v2 hypotheses on pre-freeze data.

---

## 3. Cadence
Freeze v2 → collect ~6–8 weeks (doubles resolved N; winners per cohort are
currently only 4–11, the binding statistical constraint) → run the same
backtest + discrimination scripts on the fresh window only → adjudicate the
three pre-registered hypotheses → cycle three.
