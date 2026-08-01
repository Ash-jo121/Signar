#!/usr/bin/env python3
"""
T+30 winners and losers, with the score/cohort context that matters for
diagnosis cycle two.

Run from backend/:
    python3 t30_analysis.py
    python3 t30_analysis.py --db db-backup/threadradar_2026-08-01.db --top 20

Applies the same hygiene as backtest.py:
  - sub-penny resolved prices (<$0.01) excluded (structural events, not returns)
  - <= -100% returns excluded
  - post-freeze rows only by default (cohort/score labels are version-locked)
"""

import argparse
import os
import sqlite3
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BACKUP_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "db-backup",
)


def latest_backup_db():
    backups = [
        os.path.join(BACKUP_DIR, name)
        for name in os.listdir(BACKUP_DIR)
        if name.startswith("threadradar") and name.endswith(".db")
    ]
    if not backups:
        raise SystemExit(f"No threadradar.db found in {BACKUP_DIR}")
    return max(backups, key=os.path.getmtime)


QUERY = """
    SELECT
        pt.ticker,
        pt.flagged_date,
        pt.flagged_price,
        pt.price_t30,
        pt.return_t30,
        pt.excess_return_t30,
        NULLIF(pt.return_7d, -999) AS return_7d,
        NULLIF(pt.return_t14, -999) AS return_t14,
        pt.flagged_mentions,
        pt.final_score,
        pt.catalyst_type,
        pt.has_catalyst,
        sm.cohort,
        sm.setup_type,
        sm.trade_score,
        sm.radar_score,
        sm.risk_score,
        sm.unique_authors,
        sm.confirmation_state_placeholder
    FROM performance_tracking pt
    LEFT JOIN score_metadata sm
      ON sm.ticker = pt.ticker AND sm.date = pt.flagged_date
    WHERE pt.updated_t30 = 1
      AND pt.return_t30 IS NOT NULL
      AND pt.return_t30 > -100
      AND (pt.price_t30 IS NULL OR pt.price_t30 >= 0.01)
      AND pt.flagged_date >= :start_date
    ORDER BY pt.return_t30 {direction}
    LIMIT :limit
"""


def has_column(conn, table, column):
    return any(
        row[1] == column for row in conn.execute(f"PRAGMA table_info({table})")
    )


def build_query(conn, direction):
    # confirmation_state lives in thesis_confirmation, not score_metadata; drop the
    # placeholder if it isn't present so the query works across schema versions.
    query = QUERY.replace(",\n        sm.confirmation_state_placeholder", "")
    return query.format(direction=direction)


def fmt_pct(value):
    return "    N/A" if value is None else f"{value:+7.1f}%"


def fmt_num(value, width=6, places=2):
    if value is None:
        return " " * (width - 3) + "N/A"
    return f"{value:>{width}.{places}f}"


def print_table(title, note, rows):
    print()
    print("=" * 118)
    print(f"  {title}")
    print(f"  {note}")
    print("=" * 118)
    header = (
        f"  {'Ticker':<7}{'Flagged':<12}{'Price':>7}{'->T+30':>8}"
        f"{'T+30':>9}{'Excess':>9}{'T+14':>9}{'T+7':>9}"
        f"{'Ment':>6}{'Score':>7}{'Trade':>7}{'Risk':>6}{'Auth':>5}  "
        f"{'Cohort':<22}{'Setup':<20}{'Catalyst'}"
    )
    print(header)
    print("-" * 118)
    if not rows:
        print("  (no rows)")
        return
    for r in rows:
        print(
            f"  {r['ticker']:<7}{r['flagged_date']:<12}"
            f"{fmt_num(r['flagged_price'], 7, 2)}{fmt_num(r['price_t30'], 8, 2)}"
            f"{fmt_pct(r['return_t30'])}{fmt_pct(r['excess_return_t30'])}"
            f"{fmt_pct(r['return_t14'])}{fmt_pct(r['return_7d'])}"
            f"{fmt_num(r['flagged_mentions'], 6, 0)}{fmt_num(r['final_score'], 7, 3)}"
            f"{fmt_num(r['trade_score'], 7, 3)}{fmt_num(r['risk_score'], 6, 1)}"
            f"{fmt_num(r['unique_authors'], 5, 0)}  "
            f"{(r['cohort'] or 'n/a'):<22}{(r['setup_type'] or 'n/a'):<20}"
            f"{r['catalyst_type'] or 'none'}"
        )


def cohort_breakdown(conn, start_date):
    """Where do the T+30 winners actually live? Counts by cohort, split by outcome."""
    rows = conn.execute(
        """
        SELECT
            COALESCE(sm.cohort, 'n/a') AS cohort,
            COUNT(*) AS n,
            SUM(CASE WHEN pt.return_t30 > 0 THEN 1 ELSE 0 END) AS winners,
            SUM(CASE WHEN pt.return_t30 >= 25 THEN 1 ELSE 0 END) AS big_winners,
            AVG(pt.return_t30) AS avg_t30,
            AVG(pt.final_score) AS avg_score
        FROM performance_tracking pt
        LEFT JOIN score_metadata sm
          ON sm.ticker = pt.ticker AND sm.date = pt.flagged_date
        WHERE pt.updated_t30 = 1
          AND pt.return_t30 IS NOT NULL
          AND pt.return_t30 > -100
          AND (pt.price_t30 IS NULL OR pt.price_t30 >= 0.01)
          AND pt.flagged_date >= ?
        GROUP BY cohort
        ORDER BY n DESC
        """,
        (start_date,),
    ).fetchall()

    print()
    print("=" * 118)
    print("  T+30 OUTCOMES BY COHORT")
    print("  Where the winners actually live, and what the scorer thought of them")
    print("=" * 118)
    print(
        f"  {'Cohort':<24}{'N':>6}{'Win>0':>7}{'Win%':>7}"
        f"{'>=+25%':>8}{'Big%':>7}{'AvgT+30':>10}{'AvgScore':>10}"
    )
    print("-" * 118)
    for r in rows:
        n = r["n"] or 0
        win_pct = 100.0 * (r["winners"] or 0) / n if n else 0
        big_pct = 100.0 * (r["big_winners"] or 0) / n if n else 0
        print(
            f"  {r['cohort']:<24}{n:>6}{r['winners'] or 0:>7}{win_pct:>6.1f}%"
            f"{r['big_winners'] or 0:>8}{big_pct:>6.1f}%"
            f"{(r['avg_t30'] or 0):>9.1f}%{(r['avg_score'] or 0):>10.3f}"
        )


def score_decile_check(conn, start_date):
    """Does a higher score mean a better T+30? Direct monotonicity check."""
    rows = conn.execute(
        """
        SELECT
            CASE
                WHEN pt.final_score >= 0.5  THEN '1. >=0.50'
                WHEN pt.final_score >= 0.3  THEN '2. 0.30-0.50'
                WHEN pt.final_score >= 0.1  THEN '3. 0.10-0.30'
                WHEN pt.final_score >= 0    THEN '4. 0.00-0.10'
                ELSE                             '5. negative'
            END AS bucket,
            COUNT(*) AS n,
            AVG(pt.return_t30) AS avg_t30,
            SUM(CASE WHEN pt.return_t30 > 0 THEN 1 ELSE 0 END) AS winners,
            MAX(pt.return_t30) AS best
        FROM performance_tracking pt
        WHERE pt.updated_t30 = 1
          AND pt.return_t30 IS NOT NULL
          AND pt.return_t30 > -100
          AND (pt.price_t30 IS NULL OR pt.price_t30 >= 0.01)
          AND pt.flagged_date >= ?
        GROUP BY bucket
        ORDER BY bucket
        """,
        (start_date,),
    ).fetchall()

    print()
    print("=" * 118)
    print("  T+30 BY SCORE BUCKET  — is the score monotonic at the long horizon?")
    print("=" * 118)
    print(f"  {'Bucket':<16}{'N':>6}{'AvgT+30':>10}{'Win%':>8}{'Best':>10}")
    print("-" * 118)
    for r in rows:
        n = r["n"] or 0
        win_pct = 100.0 * (r["winners"] or 0) / n if n else 0
        print(
            f"  {r['bucket']:<16}{n:>6}{(r['avg_t30'] or 0):>9.1f}%"
            f"{win_pct:>7.1f}%{(r['best'] or 0):>9.1f}%"
        )


def main():
    parser = argparse.ArgumentParser(description="T+30 winners/losers analysis")
    parser.add_argument("--db", default=None, help="Path to a threadradar db backup")
    parser.add_argument("--top", type=int, default=15, help="Rows per table")
    parser.add_argument(
        "--start-date",
        default="2026-06-10",
        help="Post-freeze cutoff; cohort/score labels are only valid from here",
    )
    args = parser.parse_args()

    db_path = args.db or latest_backup_db()
    print(f"\nDB: {db_path}")
    print(f"Post-freeze rows from: {args.start_date}")
    print("Excluded: sub-penny T+30 resolutions, returns <= -100%")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    total = conn.execute(
        """
        SELECT COUNT(*) FROM performance_tracking
        WHERE updated_t30 = 1 AND return_t30 IS NOT NULL
          AND return_t30 > -100 AND (price_t30 IS NULL OR price_t30 >= 0.01)
          AND flagged_date >= ?
        """,
        (args.start_date,),
    ).fetchone()[0]
    print(f"Resolved T+30 rows in scope: {total}")

    winners = conn.execute(
        build_query(conn, "DESC"),
        {"start_date": args.start_date, "limit": args.top},
    ).fetchall()
    print_table(
        f"TOP {args.top} T+30 WINNERS",
        "If these are all low-score / non-candidate, the penalties are pointed the wrong way",
        winners,
    )

    losers = conn.execute(
        build_query(conn, "ASC"),
        {"start_date": args.start_date, "limit": args.top},
    ).fetchall()
    print_table(
        f"BOTTOM {args.top} T+30 LOSERS",
        "What the gates let through — the first place to look for which filter to fix",
        losers,
    )

    cohort_breakdown(conn, args.start_date)
    score_decile_check(conn, args.start_date)

    conn.close()
    print()


if __name__ == "__main__":
    main()
