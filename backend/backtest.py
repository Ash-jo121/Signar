#!/usr/bin/env python3
"""
ThreadRadar Backtesting Analysis — Week 1-4
Run from backend/ directory: python3 backtest_analysis.py

Data notes:
  - Full dataset (end of March → present): score, return, mod, vampire data
  - Clean catalyst data: Apr 27 onwards only (Step 5.5 fix applied from that date)
  - Catalyst sections are clearly labelled with their date scope
"""

import os
import sqlite3
import argparse
from datetime import datetime

BACKUP_DIR = os.path.join(os.path.dirname(__file__), "db-backup")


def latest_backup_db():
    backups = [
        os.path.join(BACKUP_DIR, name)
        for name in os.listdir(BACKUP_DIR)
        if name.startswith("threadradar_") and name.endswith(".db")
    ]
    return max(backups, key=os.path.getmtime)


DB_PATH = latest_backup_db()
START_DATE = None

# Catalyst data is only reliable from this date onwards
CLEAN_CATALYST_DATE = "2026-04-27"


def date_clause(column="flagged_date", prefix="WHERE"):
    if not START_DATE:
        return ""
    return f"{prefix} {column} >= :start_date"


def params(**extra):
    values = dict(extra)
    if START_DATE:
        values["start_date"] = START_DATE
    return values


def catalyst_start_date():
    if START_DATE and START_DATE > CLEAN_CATALYST_DATE:
        return START_DATE
    return CLEAN_CATALYST_DATE


def get_conn():
    source = sqlite3.connect(DB_PATH)
    conn = sqlite3.connect(":memory:")
    source.backup(conn)
    source.close()
    conn.row_factory = sqlite3.Row
    if START_DATE:
        conn.execute(
            "DELETE FROM performance_tracking WHERE flagged_date < ?",
            (START_DATE,),
        )
        conn.execute("DELETE FROM daily_sentiment WHERE date < ?", (START_DATE,))
        conn.execute("DELETE FROM daily_contexts WHERE date < ?", (START_DATE,))
    conn.execute(
        """
        DELETE FROM performance_tracking
        WHERE return_1d <= -100
           OR return_3d <= -100
           OR return_7d <= -100
        """
    )
    conn.execute(
        """
        UPDATE performance_tracking
        SET has_catalyst = COALESCE((
                SELECT ds.has_catalyst
                FROM daily_sentiment ds
                WHERE ds.ticker = performance_tracking.ticker
                  AND ds.date = performance_tracking.flagged_date
            ), has_catalyst),
            catalyst_type = COALESCE((
                SELECT ds.catalyst_type
                FROM daily_sentiment ds
                WHERE ds.ticker = performance_tracking.ticker
                  AND ds.date = performance_tracking.flagged_date
                  AND ds.catalyst_type IS NOT NULL
            ), catalyst_type)
        """
    )
    return conn


def fmt(val):
    if val is None:
        return "   N/A  "
    return f"{val:+.2f}%"


def pct(val):
    if val is None:
        return "  N/A"
    return f"{val:>5.1f}%"


def divider(char="─", width=68):
    print(char * width)


def section(title, note=None):
    print()
    divider("═")
    print(f"  {title}")
    if note:
        print(f"  ⚠  {note}")
    divider("═")


# ── 1. Dataset summary ────────────────────────────────────────────────────────
def summary(conn):
    section("DATASET SUMMARY")

    row = conn.execute(f"""
        SELECT
            COUNT(*)                    AS total_flags,
            COUNT(DISTINCT ticker)      AS unique_tickers,
            COUNT(DISTINCT flagged_date) AS trading_days,
            MIN(flagged_date)           AS first_date,
            MAX(flagged_date)           AS last_date,
            SUM(updated_1d)             AS resolved_1d,
            SUM(updated_3d)             AS resolved_3d,
            SUM(updated_7d)             AS resolved_7d
        FROM performance_tracking
        {date_clause()}
    """, params()).fetchone()

    clean_row = conn.execute(
        f"""
        SELECT COUNT(*) AS clean_flags
        FROM performance_tracking
        WHERE flagged_date >= :catalyst_date
        {date_clause(prefix="AND")}
    """,
        params(catalyst_date=catalyst_start_date()),
    ).fetchone()

    print(f"  Period              : {row['first_date']} → {row['last_date']}")
    print(f"  Trading days        : {row['trading_days']}")
    print(f"  Total flags         : {row['total_flags']}")
    print(f"  Unique tickers      : {row['unique_tickers']}")
    print(f"  T+1 resolved        : {row['resolved_1d']}")
    print(f"  T+3 resolved        : {row['resolved_3d']}")
    print(f"  T+7 resolved        : {row['resolved_7d']}")
    print(
        f"  Clean catalyst flags: {clean_row['clean_flags']}  (from {catalyst_start_date()})"
    )


# ── 2. Overall hit rate — FULL DATASET ───────────────────────────────────────
def hit_rate(conn):
    section("OVERALL HIT RATE", "Full dataset — no catalyst filter applied here")

    row = conn.execute(f"""
        SELECT
            COUNT(*)                                                AS n,
            AVG(return_1d)                                          AS avg_t1,
            AVG(return_3d)                                          AS avg_t3,
            AVG(return_7d)                                          AS avg_t7,
            100.0 * SUM(CASE WHEN return_1d > 0  THEN 1 END)
                  / COUNT(*)                                        AS win_rate,
            100.0 * SUM(CASE WHEN return_1d > 5  THEN 1 END)
                  / COUNT(*)                                        AS strong_win,
            100.0 * SUM(CASE WHEN return_1d < -10 THEN 1 END)
                  / COUNT(*)                                        AS bad_loss
        FROM performance_tracking
        WHERE updated_1d = 1
        {date_clause(prefix="AND")}
    """, params()).fetchone()

    print(f"  Sample size         : {row['n']}")
    print(f"  Avg T+1 return      : {fmt(row['avg_t1'])}")
    print(f"  Avg T+3 return      : {fmt(row['avg_t3'])}")
    print(f"  Avg T+7 return      : {fmt(row['avg_t7'])}")
    print(f"  Win rate (T+1 > 0)  : {row['win_rate']:.1f}%")
    print(f"  Strong wins (> +5%) : {row['strong_win']:.1f}%")
    print(f"  Bad losses (< -10%) : {row['bad_loss']:.1f}%")


# ── 3. Score buckets — FULL DATASET ──────────────────────────────────────────
def score_buckets(conn):
    section(
        "SCORE BUCKET ANALYSIS  — does higher score predict better returns?",
        "Full dataset",
    )

    rows = conn.execute(f"""
        SELECT
            CASE
                WHEN final_score >= 0.8 THEN '1. High  (≥0.8)'
                WHEN final_score >= 0.5 THEN '2. Mid   (0.5–0.8)'
                WHEN final_score >= 0.3 THEN '3. Low   (0.3–0.5)'
                ELSE                         '4. Poor  (<0.3)'
            END                         AS bucket,
            COUNT(*)                    AS n,
            AVG(return_1d)              AS avg_t1,
            AVG(return_7d)              AS avg_t7,
            100.0 * SUM(CASE WHEN return_1d > 0 THEN 1 END)
                  / COUNT(*)            AS win_rate
        FROM performance_tracking
        WHERE updated_1d = 1
        {date_clause(prefix="AND")}
        GROUP BY bucket
        ORDER BY bucket
    """, params()).fetchall()

    print(f"  {'Bucket':<22} {'N':>4}  {'Avg T+1':>9}  {'Avg T+7':>9}  {'Win%':>6}")
    divider()
    for r in rows:
        print(
            f"  {r['bucket']:<22} {r['n']:>4}  {fmt(r['avg_t1']):>9}"
            f"  {fmt(r['avg_t7']):>9}  {pct(r['win_rate']):>6}"
        )


# ── 4. Catalyst vs no-catalyst — APR 27+ ONLY ────────────────────────────────
def catalyst_split(conn):
    section(
        "CATALYST vs NO CATALYST",
        f"Clean data only — flags from {CLEAN_CATALYST_DATE} onwards",
    )

    rows = conn.execute(
        """
        SELECT
            CASE WHEN has_catalyst = 1
                 THEN 'With catalyst'
                 ELSE 'No catalyst'
            END             AS grp,
            COUNT(*)        AS n,
            AVG(return_1d)  AS avg_t1,
            AVG(return_3d)  AS avg_t3,
            AVG(return_7d)  AS avg_t7,
            100.0 * SUM(CASE WHEN return_1d > 0 THEN 1 END)
                  / COUNT(*) AS win_rate
        FROM performance_tracking
        WHERE updated_1d = 1
          AND flagged_date >= ?
        GROUP BY has_catalyst
        ORDER BY has_catalyst DESC
    """,
        (CLEAN_CATALYST_DATE,),
    ).fetchall()

    if not rows:
        print(f"  No resolved T+1 data yet from {CLEAN_CATALYST_DATE}+")
        return

    print(
        f"  {'Group':<18} {'N':>4}  {'Avg T+1':>9}  {'Avg T+3':>9}"
        f"  {'Avg T+7':>9}  {'Win%':>6}"
    )
    divider()
    for r in rows:
        print(
            f"  {r['grp']:<18} {r['n']:>4}  {fmt(r['avg_t1']):>9}"
            f"  {fmt(r['avg_t3']):>9}  {fmt(r['avg_t7']):>9}"
            f"  {pct(r['win_rate']):>6}"
        )


# ── 5. Returns by catalyst type — APR 27+ ONLY ───────────────────────────────
def catalyst_types(conn):
    section(
        "RETURNS BY CATALYST TYPE  (min 2 samples)",
        f"Clean data only — flags from {CLEAN_CATALYST_DATE} onwards",
    )

    rows = conn.execute(
        """
        SELECT
            COALESCE(catalyst_type, 'none')  AS ctype,
            COUNT(*)                         AS n,
            AVG(return_1d)                   AS avg_t1,
            AVG(return_7d)                   AS avg_t7,
            100.0 * SUM(CASE WHEN return_1d > 0 THEN 1 END)
                  / COUNT(*)                 AS win_rate
        FROM performance_tracking
        WHERE updated_1d = 1
          AND flagged_date >= ?
        GROUP BY ctype
        HAVING n >= 2
        ORDER BY avg_t1 DESC
    """,
        (CLEAN_CATALYST_DATE,),
    ).fetchall()

    if not rows:
        print(f"  No catalyst type groups with 2+ samples from {CLEAN_CATALYST_DATE}+")
        return

    print(f"  {'Type':<22} {'N':>4}  {'Avg T+1':>9}  {'Avg T+7':>9}  {'Win%':>6}")
    divider()
    for r in rows:
        print(
            f"  {r['ctype']:<22} {r['n']:>4}  {fmt(r['avg_t1']):>9}"
            f"  {fmt(r['avg_t7']):>9}  {pct(r['win_rate']):>6}"
        )


# ── 6. Mod flag impact — FULL DATASET ────────────────────────────────────────
def mod_impact(conn):
    section(
        "MOD FLAG IMPACT", "Full dataset — mod flag does not depend on catalyst data"
    )

    rows = conn.execute("""
        SELECT
            CASE WHEN mod_flagged = 1
                 THEN 'Mod flagged'
                 ELSE 'Clean'
            END             AS grp,
            COUNT(*)        AS n,
            AVG(return_1d)  AS avg_t1,
            AVG(return_7d)  AS avg_t7,
            100.0 * SUM(CASE WHEN return_1d > 0 THEN 1 END)
                  / COUNT(*) AS win_rate
        FROM performance_tracking
        WHERE updated_1d = 1
        GROUP BY mod_flagged
        ORDER BY mod_flagged DESC
    """).fetchall()

    print(f"  {'Group':<14} {'N':>4}  {'Avg T+1':>9}  {'Avg T+7':>9}  {'Win%':>6}")
    divider()
    for r in rows:
        print(
            f"  {r['grp']:<14} {r['n']:>4}  {fmt(r['avg_t1']):>9}"
            f"  {fmt(r['avg_t7']):>9}  {pct(r['win_rate']):>6}"
        )


# ── 7. Vampire flag impact — FULL DATASET ────────────────────────────────────
def vampire_impact(conn):
    section("VAMPIRE FLAG EFFECTIVENESS", "Full dataset")

    rows = conn.execute("""
        SELECT
            CASE WHEN vampire_flagged = 1
                 THEN 'Vampire flagged'
                 ELSE 'Clean'
            END             AS grp,
            COUNT(*)        AS n,
            AVG(return_1d)  AS avg_t1,
            AVG(return_7d)  AS avg_t7,
            100.0 * SUM(CASE WHEN return_1d > 0 THEN 1 END)
                  / COUNT(*) AS win_rate
        FROM performance_tracking
        WHERE updated_1d = 1
        GROUP BY vampire_flagged
        ORDER BY vampire_flagged DESC
    """).fetchall()

    print(f"  {'Group':<18} {'N':>4}  {'Avg T+1':>9}  {'Avg T+7':>9}  {'Win%':>6}")
    divider()
    for r in rows:
        print(
            f"  {r['grp']:<18} {r['n']:>4}  {fmt(r['avg_t1']):>9}"
            f"  {fmt(r['avg_t7']):>9}  {pct(r['win_rate']):>6}"
        )


# ── 8. Multi-day consistency — FULL DATASET ───────────────────────────────────
def consistency_signal(conn):
    section(
        "MULTI-DAY CONSISTENCY  (stocks appearing 3+ days)",
        "Full dataset — ranked by avg T+7 return",
    )

    rows = conn.execute("""
        SELECT
            ticker,
            COUNT(DISTINCT flagged_date)    AS days_flagged,
            AVG(final_score)                AS avg_score,
            AVG(return_1d)                  AS avg_t1,
            AVG(return_7d)                  AS avg_t7,
            MAX(return_7d)                  AS best_t7
        FROM performance_tracking
        WHERE updated_1d = 1
        GROUP BY ticker
        HAVING days_flagged >= 3
        ORDER BY avg_t7 DESC NULLS LAST
    """).fetchall()

    if not rows:
        print("  No tickers with 3+ appearances and T+1 resolved yet.")
        return

    print(
        f"  {'Ticker':<6} {'Days':>5}  {'AvgScore':>9}  {'Avg T+1':>9}"
        f"  {'Avg T+7':>9}  {'Best T+7':>9}"
    )
    divider()
    for r in rows:
        print(
            f"  {r['ticker']:<6} {r['days_flagged']:>5}  {r['avg_score']:>9.3f}"
            f"  {fmt(r['avg_t1']):>9}  {fmt(r['avg_t7']):>9}"
            f"  {fmt(r['best_t7']):>9}"
        )


# ── 9. Top winners and worst losses — FULL DATASET ───────────────────────────
def extremes(conn):
    section("TOP 10 WINNERS  (by T+1 return)", "Full dataset")

    rows = conn.execute("""
        SELECT ticker, flagged_date, final_score, has_catalyst,
               catalyst_type, return_1d, return_7d
        FROM performance_tracking
        WHERE updated_1d = 1
        ORDER BY return_1d DESC
        LIMIT 10
    """).fetchall()

    print(
        f"  {'Ticker':<6} {'Date':<12} {'Score':>6}  {'Cat':>3}"
        f"  {'Type':<18}  {'T+1':>9}  {'T+7':>9}"
    )
    divider()
    for r in rows:
        cat = "Y" if r["has_catalyst"] else "N"
        ctype = (r["catalyst_type"] or "none")[:18]
        print(
            f"  {r['ticker']:<6} {r['flagged_date']:<12} {r['final_score']:>6.3f}"
            f"  {cat:>3}  {ctype:<18}  {fmt(r['return_1d']):>9}"
            f"  {fmt(r['return_7d']):>9}"
        )

    section("BOTTOM 10 LOSSES  (by T+1 return)", "Full dataset")

    rows = conn.execute("""
        SELECT ticker, flagged_date, final_score, has_catalyst,
               catalyst_type, return_1d, return_7d
        FROM performance_tracking
        WHERE updated_1d = 1
        ORDER BY return_1d ASC
        LIMIT 10
    """).fetchall()

    print(
        f"  {'Ticker':<6} {'Date':<12} {'Score':>6}  {'Cat':>3}"
        f"  {'Type':<18}  {'T+1':>9}  {'T+7':>9}"
    )
    divider()
    for r in rows:
        cat = "Y" if r["has_catalyst"] else "N"
        ctype = (r["catalyst_type"] or "none")[:18]
        print(
            f"  {r['ticker']:<6} {r['flagged_date']:<12} {r['final_score']:>6.3f}"
            f"  {cat:>3}  {ctype:<18}  {fmt(r['return_1d']):>9}"
            f"  {fmt(r['return_7d']):>9}"
        )


# ── 10. Mentions vs returns — FULL DATASET ───────────────────────────────────
def mentions_analysis(conn):
    section(
        "MENTION COUNT vs RETURNS  — does higher mention count help?", "Full dataset"
    )

    rows = conn.execute("""
        SELECT
            CASE
                WHEN flagged_mentions >= 20 THEN '1. High  (≥20)'
                WHEN flagged_mentions >= 10 THEN '2. Mid   (10–20)'
                WHEN flagged_mentions >= 5  THEN '3. Low   (5–10)'
                ELSE                             '4. Minimal (<5)'
            END                         AS bucket,
            COUNT(*)                    AS n,
            AVG(return_1d)              AS avg_t1,
            AVG(return_7d)              AS avg_t7,
            100.0 * SUM(CASE WHEN return_1d > 0 THEN 1 END)
                  / COUNT(*)            AS win_rate
        FROM performance_tracking
        WHERE updated_1d = 1
        GROUP BY bucket
        ORDER BY bucket
    """).fetchall()

    print(f"  {'Bucket':<22} {'N':>4}  {'Avg T+1':>9}  {'Avg T+7':>9}  {'Win%':>6}")
    divider()
    for r in rows:
        print(
            f"  {r['bucket']:<22} {r['n']:>4}  {fmt(r['avg_t1']):>9}"
            f"  {fmt(r['avg_t7']):>9}  {pct(r['win_rate']):>6}"
        )


def sentiment_buckets(conn):
    section("AVG SENTIMENT BUCKET ANALYSIS", "Full dataset")
    rows = conn.execute("""
        SELECT
            CASE
                WHEN flagged_sentiment >= 0.4 THEN '1. Strong  (>=0.4)'
                WHEN flagged_sentiment >= 0.2 THEN '2. Mild    (0.2-0.4)'
                WHEN flagged_sentiment >= 0.0 THEN '3. Neutral (0-0.2)'
                ELSE                               '4. Negative (<0)'
            END                         AS bucket,
            COUNT(*)                    AS n,
            AVG(return_1d)              AS avg_t1,
            AVG(return_7d)              AS avg_t7,
            100.0*SUM(CASE WHEN return_1d>0 THEN 1 END)
                 /COUNT(*)              AS win_rate
        FROM performance_tracking
        WHERE updated_1d = 1
        GROUP BY bucket
        ORDER BY bucket
    """).fetchall()

    print(f"  {'Bucket':<22} {'N':>4}  {'Avg T+1':>9}  {'Avg T+7':>9}  {'Win%':>6}")
    divider()
    for r in rows:
        print(
            f"  {r['bucket']:<22} {r['n']:>4}  {fmt(r['avg_t1']):>9}"
            f"  {fmt(r['avg_t7']):>9}  {pct(r['win_rate']):>6}"
        )


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run ThreadRadar backtest analysis")
    parser.add_argument(
        "--db",
        default=DB_PATH,
        help="SQLite database path. Defaults to the latest db-backup/threadradar_*.db",
    )
    parser.add_argument(
        "--start-date",
        default=None,
        help="Only include rows on or after this YYYY-MM-DD date",
    )
    args = parser.parse_args()
    DB_PATH = args.db
    START_DATE = args.start_date

    print()
    print("  ╔══════════════════════════════════════════════════════════════════╗")
    print("  ║           ThreadRadar — Backtesting Analysis  v1.0              ║")
    print(
        f"  ║           Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}                          ║"
    )
    print(
        f"  ║           Catalyst data clean from: {CLEAN_CATALYST_DATE}                 ║"
    )
    print("  ╚══════════════════════════════════════════════════════════════════╝")

    conn = get_conn()

    summary(conn)
    hit_rate(conn)
    score_buckets(conn)
    mentions_analysis(conn)
    mod_impact(conn)
    vampire_impact(conn)
    catalyst_split(conn)
    catalyst_types(conn)
    consistency_signal(conn)
    extremes(conn)
    sentiment_buckets(conn)

    conn.close()

    print()
    divider("═")
    print("  Note: catalyst sections use Apr 27+ data only (3 days, small sample).")
    print("  Re-run in 4 weeks for statistically meaningful catalyst results.")
    divider("═")
    print()
