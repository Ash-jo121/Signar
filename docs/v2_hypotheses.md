# Signar v2 preregistered hypotheses

## Freeze and evaluation window

- Scoring version: `2026-08-02-simplified-v2`
- Freeze date: 2026-08-02
- Eligible observations: rows with `flagged_date >= 2026-08-02` and the exact v2
  scoring version.
- Earliest planned evaluation: 2026-09-15, after approximately 6–8 weeks of
  collection.
- Cycle-one and other pre-freeze data must not be used to accept, reject, tune,
  or redefine these hypotheses.
- Preserve the existing subreddit list, universe filters, return horizons, risk
  gates, and sub-penny return exclusions throughout the collection window.

## H1 — Repeat appearance

Compare T+14 outcomes for `flag_sequence >= 3` against `flag_sequence == 1`.
Report sample size, mean and median return, positive-return rate, and the rate of
returns at or above +20% for each group. The hypothesis passes only if the repeat
group has the better T+14 outcome without redefining either group after seeing
the data.

## H2 — Rising attention with new authors

The preregistered target group is `mention_velocity_num > 1.0` and
`author_overlap < 0.5`; the comparison group is every other row where both
measurements are present. Test whether the target group predicts T+3 or T+7
returns of at least +20% above the fresh-window base rate. Report sample size,
pop rate, base rate, and confidence intervals without changing these cutoffs.
The expected base-rate reference is approximately 10–15%, but the observed
fresh-window base rate is the comparison denominator.

## H3 — Same-day ranking value

For each eligible day, compare the simplified-v2 cohorts with random same-day
baskets using the existing backtest procedure. Evaluate at T+7. The hypothesis
passes only if the target cohort's basket performance is above the 60th
percentile of random same-day baskets.

## Measurement fields

The collection schema records `mention_velocity_num`, `author_overlap`, and
`flag_sequence` in `performance_tracking`. These are measurement-only fields for
this cycle and must not enter scoring before this preregistered evaluation.
