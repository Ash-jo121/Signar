#!/usr/bin/env python3
"""
Within-cohort winner vs loser discrimination.

Question: inside avoid_high_risk and near_miss_candidate, most names lost but a
few ran hard (SKYQ, CAST, MGRX, COSM, RGNT). Does ANY stored feature separate
the winners from the losers in the SAME cohort?

This is a hypothesis generator, not a finding machine. With ~6 winners per
cohort, comparing a dozen features will surface something by chance. Anything
that separates here must be re-tested on a fresh forward window before it earns
a place in the scorer.

Run from backend/:
    python3 cohort_discrimination.py
    python3 cohort_discrimination.py --horizon t14 --win 20 --loss -20
"""

import argparse
import os
import sqlite3
import sys
from statistics import median

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BACKUP_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "db-backup",
)

# (label, column, source_table_alias, higher_is_notable)
NUMERIC_FEATURES = [
    ("mentions", "pt.flagged_mentions"),
    ("unique_authors", "sm.unique_authors"),
    ("top_author_share", "sm.top_author_share"),
    ("risk_score", "sm.risk_score"),
    ("trade_score", "sm.trade_score"),
    ("radar_score", "sm.radar_score"),
    ("final_score", "pt.final_score"),
    ("flagged_price", "pt.flagged_price"),
    ("sentiment", "pt.flagged_sentiment"),
    ("promotion_risk", "sm.promotion_risk_score"),
    ("days_trending", "sm.days_trending"),
    ("price_change_1d", "sm.price_change_1d"),
    ("price_change_3d", "sm.price_change_3d"),
    ("price_change_7d", "sm.price_change_7d"),
    ("dollar_volume", "sm.dollar_volume"),
    ("relative_volume", "sm.relative_volume"),
    ("float_shares", "pt.float_shares"),
]

CATEGORICAL_FEATURES = [
    ("setup_type", "sm.setup_type"),
    ("catalyst_type", "pt.catalyst_type"),
    ("market_confirmation", "sm.market_confirmation_status"),
    ("mention_velocity", "sm.mention_velocity_label"),
]


def latest_backup_db():
    candidates = [
        os.path.join(BACKUP_DIR, name)
        for name in os.listdir(BACKUP_DIR)
        if name.startswith("threadradar") and name.endswith(".db")
    ]
    if not candidates:
        raise SystemExit(f"No threadradar*.db found in {BACKUP_DIR}")
    return max(candidates, key=os.path.getmtime)


def available(conn, table, column):
    return any(row[1] == column for row in conn.execute(f"PRAGMA table_info({table})"))


def build_select(conn):
    numeric, categorical = [], []
    for label, expr in NUMERIC_FEATURES:
        table, column = expr.split(".")
        real_table = "performance_tracking" if table == "pt" else "score_metadata"
        if available(conn, real_table, column):
            numeric.append((label, expr))
    for label, expr in CATEGORICAL_FEATURES:
        table, column = expr.split(".")
        real_table = "performance_tracking" if table == "pt" else "score_metadata"
        if available(conn, real_table, column):
            categorical.append((label, expr))
    return numeric, categorical


def fetch_rows(conn, horizon, start_date, numeric, categorical):
    return_col = f"return_{horizon}" if horizon.startswith("t") else f"return_{horizon}"
    price_col = f"price_{horizon}" if horizon.startswith("t") else f"price_{horizon}"
    selects = ",\n            ".join(
        [f"{expr} AS {label}" for label, expr in numeric + categorical]
    )
    query = f"""
        SELECT
            pt.ticker,
            pt.flagged_date,
            pt.{return_col} AS ret,
            COALESCE(sm.cohort, 'n/a') AS cohort,
            {selects}
        FROM performance_tracking pt
        LEFT JOIN score_metadata sm
          ON sm.ticker = pt.ticker AND sm.date = pt.flagged_date
        WHERE pt.updated_{horizon} = 1
          AND pt.{return_col} IS NOT NULL
          AND pt.{return_col} > -100
          AND (pt.{price_col} IS NULL OR pt.{price_col} >= 0.01)
          AND pt.flagged_date >= ?
    """
    return [dict(row) for row in conn.execute(query, (start_date,)).fetchall()]


def stats(values):
    values = [v for v in values if v is not None]
    if not values:
        return None
    return {
        "n": len(values),
        "median": median(values),
        "mean": sum(values) / len(values),
        "min": min(values),
        "max": max(values),
    }


def overlap_verdict(win, lose):
    """Crude separation check: do the medians differ by more than the spread?"""
    if not win or not lose or win["n"] < 3 or lose["n"] < 3:
        return "n/a (too few)"
    diff = win["median"] - lose["median"]
    spread = max(abs(win["max"] - win["min"]), abs(lose["max"] - lose["min"]))
    if spread == 0:
        return "flat"
    ratio = abs(diff) / spread
    if ratio >= 0.25:
        return "SEPARATES?" if diff > 0 else "SEPARATES? (lower)"
    if ratio >= 0.12:
        return "weak"
    return "no"


def compare_cohort(rows, cohort, win_threshold, loss_threshold, numeric, categorical):
    subset = [r for r in rows if r["cohort"] == cohort]
    winners = [r for r in subset if r["ret"] >= win_threshold]
    losers = [r for r in subset if r["ret"] <= loss_threshold]

    print()
    print("=" * 100)
    print(f"  COHORT: {cohort}")
    print(
        f"  {len(subset)} resolved rows | winners (>= {win_threshold:+.0f}%): "
        f"{len(winners)} | losers (<= {loss_threshold:+.0f}%): {len(losers)}"
    )
    print("=" * 100)

    if len(winners) < 3 or len(losers) < 3:
        print("  Too few in one group for any comparison. Skipping.")
        return

    print(f"\n  {'Feature':<20}{'WinMed':>10}{'LoseMed':>10}{'WinMean':>10}"
          f"{'LoseMean':>10}{'Win n':>7}{'Lose n':>7}  Verdict")
    print("-" * 100)
    for label, _ in numeric:
        win = stats([r[label] for r in winners])
        lose = stats([r[label] for r in losers])
        if not win or not lose:
            continue
        print(
            f"  {label:<20}{win['median']:>10.2f}{lose['median']:>10.2f}"
            f"{win['mean']:>10.2f}{lose['mean']:>10.2f}"
            f"{win['n']:>7}{lose['n']:>7}  {overlap_verdict(win, lose)}"
        )

    for label, _ in categorical:
        win_counts, lose_counts = {}, {}
        for r in winners:
            key = r[label] or "none"
            win_counts[key] = win_counts.get(key, 0) + 1
        for r in losers:
            key = r[label] or "none"
            lose_counts[key] = lose_counts.get(key, 0) + 1
        keys = sorted(set(win_counts) | set(lose_counts))
        if not keys:
            continue
        print(f"\n  {label}:")
        print(f"    {'value':<26}{'win':>6}{'win%':>8}{'lose':>6}{'lose%':>8}")
        for key in keys:
            w, l = win_counts.get(key, 0), lose_counts.get(key, 0)
            wp = 100.0 * w / len(winners)
            lp = 100.0 * l / len(losers)
            flag = "  <--" if (wp - lp) >= 20 else ""
            print(f"    {key:<26}{w:>6}{wp:>7.1f}%{l:>6}{lp:>7.1f}%{flag}")

    print(f"\n  Winners: {', '.join(sorted({r['ticker'] for r in winners}))}")
    print(f"  Losers : {', '.join(sorted({r['ticker'] for r in losers}))}")


def repeat_ticker_check(rows, win_threshold):
    """Do tickers that win appear more often than tickers that don't?"""
    by_ticker = {}
    for r in rows:
        by_ticker.setdefault(r["ticker"], []).append(r["ret"])

    winners = {t: v for t, v in by_ticker.items() if max(v) >= win_threshold}
    others = {t: v for t, v in by_ticker.items() if max(v) < win_threshold}

    def appearances(group):
        counts = [len(v) for v in group.values()]
        return (
            len(counts),
            sum(counts) / len(counts) if counts else 0,
            median(counts) if counts else 0,
        )

    wn, wavg, wmed = appearances(winners)
    on, oavg, omed = appearances(others)

    print()
    print("=" * 100)
    print("  REPEAT-APPEARANCE CHECK (all cohorts)")
    print("  Does a ticker that eventually runs get flagged on more days?")
    print("=" * 100)
    print(f"  Tickers with a >= {win_threshold:+.0f}% flag : {wn:>4} | "
          f"avg appearances {wavg:.2f} | median {wmed:.0f}")
    print(f"  Tickers without                : {on:>4} | "
          f"avg appearances {oavg:.2f} | median {omed:.0f}")


def main():
    parser = argparse.ArgumentParser(description="Within-cohort winner/loser features")
    parser.add_argument("--db", default=None)
    parser.add_argument("--horizon", default="t30", choices=["7d", "t14", "t30"])
    parser.add_argument("--win", type=float, default=25.0)
    parser.add_argument("--loss", type=float, default=-25.0)
    parser.add_argument("--start-date", default="2026-06-10")
    parser.add_argument(
        "--cohorts",
        default="avoid_high_risk,near_miss_candidate,n/a,scored_not_selected",
    )
    args = parser.parse_args()

    db_path = args.db or latest_backup_db()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    numeric, categorical = build_select(conn)
    rows = fetch_rows(conn, args.horizon, args.start_date, numeric, categorical)

    print(f"\nDB: {db_path}")
    print(f"Horizon: {args.horizon} | winner >= {args.win:+.0f}% | "
          f"loser <= {args.loss:+.0f}% | from {args.start_date}")
    print(f"Resolved rows in scope: {len(rows)}")
    print(f"Features available: {len(numeric)} numeric, {len(categorical)} categorical")
    print("\n  NOTE: with small winner counts, some feature will differ by chance.")
    print("  Treat every 'SEPARATES?' as a hypothesis for the NEXT forward window.")

    for cohort in args.cohorts.split(","):
        compare_cohort(rows, cohort.strip(), args.win, args.loss, numeric, categorical)

    repeat_ticker_check(rows, args.win)
    conn.close()
    print()


if __name__ == "__main__":
    main()