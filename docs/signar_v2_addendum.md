# Signar v2 — Addendum: Avoid-Side Measurement & Author Track Records

Supplement to `signar_v2_plan.md`. Two additions from post-backtest
brainstorming, one explicit rejection. Same rules apply: measurement only,
nothing enters the scorer until it survives a fresh forward window.

---

## A. Avoid/vampire short-side measurement

**Motivation.** Cycle one showed the long-side ranking is uninformative, but
`avoid_high_risk` fell −12.5% (T+14) / −21.5% (T+30). Untested question:
does the avoid cohort fall *more than the same-day flagged universe*, or is
it just riding the universe's −20%/month drift?

### A.1 Backtest addition (backtest.py) — REQUIRED
Add a section `avoid_side_test`:
- For each trading day, compute mean T+7 / T+14 return of
  (a) `avoid_high_risk` + `vampire_flagged=1` rows, and
  (b) all other same-day flagged rows.
- Report the per-day spread (a − b), its median across days, and the share
  of days where avoid underperformed the rest.
- Same hygiene as existing sections: sub-penny and <=−100% exclusions,
  post-freeze rows only.

### A.2 Pre-registered hypothesis #4 (add to §2.3 of main plan)
> H4: The avoid+vampire cohort underperforms the same-day flagged universe
> by ≥ 3 percentage points (median daily spread) at T+14 on the v2 window.

### A.3 Hard constraints — DO NOT VIOLATE
- **No real short trades.** Sub-$5 microcaps: borrow scarce/expensive,
  unbounded loss, and pump-and-dump names squeeze hardest before dying.
- If H4 passes on the v2 window, the ONLY permitted next step is an Alpaca
  **paper** short cohort logged separately. Real capital is out of scope.
- No UI section presenting avoid/vampire names as trade recommendations
  (long or short). They remain warnings.

---

## B. Author track-record instrumentation

**Motivation.** No same-day snapshot feature separates winners from losers.
The one surviving lead is cross-day persistence. Current author features
(karma, age, concentration) are credibility *proxies*; none separated.
Demonstrated *accuracy* — did this author's past mentions precede stocks
that rose? — is new, accumulating, cross-day information.

### B.1 Schema — REQUIRED
New table `author_track_record`:
```
author TEXT PRIMARY KEY
tickers_mentioned INTEGER
resolved_mentions INTEGER
avg_return_t7 REAL
avg_return_t14 REAL
win_rate_t7 REAL          -- share of resolved mentions with return_7d > 0
last_updated TEXT
```
New table `author_mentions` (the raw ledger the aggregates derive from):
```
author TEXT
ticker TEXT
mention_date TEXT
UNIQUE(author, ticker, mention_date)
```
Populate `author_mentions` at analysis time from post/comment authors per
ticker per day. Update `author_track_record` aggregates inside the price
updater when horizons resolve.

### B.2 Per-flag features — REQUIRED (measurement only)
At `record_flagged_stocks` time, compute and store on each
`performance_tracking` row:
- `author_hist_avg_t7`: mean historical avg_return_t7 of this flag's
  authors (NULL if no author has resolved history)
- `author_hist_coverage`: fraction of this flag's authors with >=1 resolved
  prior mention

**Point-in-time rule (critical, prevents lookahead leak):** an author's
track record used for a flag on date D may include ONLY mentions whose
horizon resolution completed BEFORE D. Never recompute retroactively with
later resolutions.

### B.3 Pre-registered hypothesis #5 (add to §2.3 of main plan)
> H5: Flags with `author_hist_avg_t7 > 0` and `author_hist_coverage >= 0.5`
> outperform flags with `author_hist_avg_t7 <= 0` at T+7 on the v2 window.

### B.4 Expectations
- Sparse for months: most authors appear once; feature will be NULL-heavy.
  This is fine — it accumulates. Do not lower thresholds to force coverage.
- Keep OUT of the scorer and OUT of any cohort/gate logic in v2.

---

## C. Rejected: T+60 / T+90 horizons

Not adding. Winners peak at T+3/T+7 and decay (SDOT +718%→+172%,
CAST +535%→+80%); universe drifts ~−20%/month, so T+90 measures ~−50% of
cumulative drift plus delistings. Longer horizons also slow every future
cycle (3 months to resolve a flag). Reconsider only if a v2 cohort shows
sustained, non-decaying T+30 strength. The unexplored horizon is the SHORT
end (T+3/T+7), already covered by hypothesis #2 in the main plan.
