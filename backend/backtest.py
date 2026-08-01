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
import json
import math
import random
import sys
from statistics import median
from datetime import datetime

from database import (
    PERFORMANCE_TRACKING_COLUMNS,
    RUN_METADATA_COLUMNS,
    SCORE_METADATA_COLUMNS,
)

BACKUP_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "db-backup",
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


import os


def latest_backup_db():
    if not os.path.isdir(BACKUP_DIR):
        return None

    backups = [
        os.path.join(BACKUP_DIR, name)
        for name in os.listdir(BACKUP_DIR)
        if (
            name.startswith("threadradar")
            and name.endswith(".db")
            and os.path.isfile(os.path.join(BACKUP_DIR, name))
        )
    ]

    if not backups:
        return None

    return max(backups, key=os.path.getmtime)


DB_PATH = latest_backup_db()
START_DATE = "2026-06-10"
V2_FREEZE_DATE = "2026-08-02"
V2_SCORING_VERSION = "2026-08-02-simplified-v2"

# Catalyst data is only reliable from this date onwards
CLEAN_CATALYST_DATE = "2026-04-27"
RETURN_HORIZONS = [
    ("T+1", "return_1d", "updated_1d"),
    ("T+3", "return_3d", "updated_3d"),
    ("T+7", "return_7d", "updated_7d"),
    ("T+14", "return_t14", "updated_t14"),
    ("T+30", "return_t30", "updated_t30"),
]


def date_clause(column="flagged_date", prefix="WHERE"):
    if not START_DATE:
        return ""
    return f"{prefix} {column} >= :start_date"


def params(**extra):
    values = dict(extra)
    if START_DATE:
        values["start_date"] = START_DATE
    return values


def get_columns(conn, table):
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def ensure_column(conn, table, column, definition):
    if column not in get_columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def ensure_score_metadata_table(conn):
    score_column_defs = ",\n            ".join(
        f"{column} {definition}" for column, definition in SCORE_METADATA_COLUMNS
    )
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS score_metadata (
            date TEXT NOT NULL,
            ticker TEXT NOT NULL,
            {score_column_defs},
            PRIMARY KEY(date, ticker)
        )
        """
    )
    for column, definition in SCORE_METADATA_COLUMNS:
        ensure_column(conn, "score_metadata", column, definition)


def ensure_run_metadata_table(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS run_metadata (
            run_date TEXT PRIMARY KEY,
            market_session TEXT NOT NULL DEFAULT 'open',
            market_closed_reason TEXT,
            price_update_status TEXT NOT NULL DEFAULT 'eligible',
            eligible_for_backtest INTEGER DEFAULT 1,
            next_trading_session_signal INTEGER DEFAULT 0
        )
        """
    )
    for column, definition in RUN_METADATA_COLUMNS:
        ensure_column(conn, "run_metadata", column, definition)


def ensure_performance_tracking_columns(conn):
    for column, definition in PERFORMANCE_TRACKING_COLUMNS:
        ensure_column(conn, "performance_tracking", column, definition)
    ensure_column(conn, "performance_tracking", "split_adjusted", "INTEGER DEFAULT 0")


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
    ensure_score_metadata_table(conn)
    ensure_run_metadata_table(conn)
    ensure_performance_tracking_columns(conn)
    if START_DATE:
        conn.execute(
            "DELETE FROM performance_tracking WHERE flagged_date < ?",
            (START_DATE,),
        )
        conn.execute("DELETE FROM daily_sentiment WHERE date < ?", (START_DATE,))
        conn.execute("DELETE FROM daily_contexts WHERE date < ?", (START_DATE,))
    for return_col in (
        "return_1d",
        "return_3d",
        "return_7d",
        "return_t14",
        "return_t30",
    ):
        conn.execute(
            f"""
            UPDATE performance_tracking
            SET {return_col} = NULL
            WHERE {return_col} <= -100
            """
        )
    # Sub-penny resolved prices are structural events (reverse splits, delistings,
    # dilution death spirals), not tradeable returns. Null them so GDC/SNBR-type
    # collapses cannot dominate cohort averages.
    for price_col, return_col in (
        ("price_1d", "return_1d"),
        ("price_3d", "return_3d"),
        ("price_7d", "return_7d"),
        ("price_t14", "return_t14"),
        ("price_t30", "return_t30"),
    ):
        conn.execute(
            f"""
            UPDATE performance_tracking
            SET {return_col} = NULL
            WHERE {price_col} IS NOT NULL AND {price_col} < 0.01
            """
        )
    conn.execute(
        """
        DELETE FROM performance_tracking
        WHERE flagged_date IN (
            SELECT run_date
            FROM run_metadata
            WHERE eligible_for_backtest = 0
        )
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


def safe_avg(values):
    values = [value for value in values if value is not None]
    if not values:
        return None
    return sum(values) / len(values)


def safe_median(values):
    values = [value for value in values if value is not None]
    if not values:
        return None
    return median(values)


def profit_factor(values):
    values = [value for value in values if value is not None]
    gains = sum(value for value in values if value > 0)
    losses = abs(sum(value for value in values if value < 0))
    if gains == 0 and losses == 0:
        return None
    if losses == 0:
        return float("inf")
    return gains / losses


def fmt_profit_factor(value):
    if value is None:
        return "  N/A"
    if value == float("inf"):
        return "  inf"
    return f"{value:>5.2f}"


def value_stats(values):
    values = [value for value in values if value is not None]
    if not values:
        return {
            "n": 0,
            "avg": None,
            "median": None,
            "win_rate": None,
            "profit_factor": None,
            "worst": None,
            "best": None,
        }

    return {
        "n": len(values),
        "avg": safe_avg(values),
        "median": safe_median(values),
        "win_rate": 100.0 * sum(1 for value in values if value > 0) / len(values),
        "profit_factor": profit_factor(values),
        "worst": min(values),
        "best": max(values),
    }


def robust_return_stats(rows, return_col, updated_col):
    values = [
        row[return_col]
        for row in rows
        if row.get(updated_col) == 1 and row.get(return_col) is not None
    ]
    return value_stats(values)


def print_robust_group_table(title, note, groups):
    section(title, note)
    print(
        f"  {'Group':<24} {'Hor':<4} {'N':>5}  {'Avg':>9}  {'Median':>9}"
        f"  {'Win%':>6}  {'PF':>5}  {'Worst':>9}  {'Best':>9}"
    )
    divider()

    horizons = RETURN_HORIZONS
    for group_name in sorted(groups):
        rows = groups[group_name]
        for horizon, return_col, updated_col in horizons:
            stats = robust_return_stats(rows, return_col, updated_col)
            print(
                f"  {group_name:<24} {horizon:<4} {stats['n']:>5}"
                f"  {fmt(stats['avg']):>9}  {fmt(stats['median']):>9}"
                f"  {pct(stats['win_rate']):>6}"
                f"  {fmt_profit_factor(stats['profit_factor']):>5}"
                f"  {fmt(stats['worst']):>9}  {fmt(stats['best']):>9}"
            )


def fetch_backtest_rows(conn):
    metadata_select = ",\n            ".join(
        f"sm.{column} AS meta_{column}" for column, _ in SCORE_METADATA_COLUMNS
    )
    rows = conn.execute(
        f"""
        SELECT
            pt.*,
            rm.scoring_version,
            ds.change_percent,
            ds.avg_sentiment AS daily_avg_sentiment,
            ds.mentions AS daily_mentions,
            ds.final_score AS daily_final_score,
            ds.volume AS daily_volume,
            {metadata_select}
        FROM performance_tracking pt
        LEFT JOIN daily_sentiment ds
          ON ds.ticker = pt.ticker
         AND ds.date = pt.flagged_date
        LEFT JOIN score_metadata sm
          ON sm.ticker = pt.ticker
         AND sm.date = pt.flagged_date
        LEFT JOIN run_metadata rm
          ON rm.run_date = pt.flagged_date
        {date_clause("pt.flagged_date")}
        ORDER BY pt.flagged_date, pt.ticker
    """,
        params(),
    ).fetchall()
    hydrated_rows = []
    for row in rows:
        item = dict(row)
        for column, _ in SCORE_METADATA_COLUMNS:
            metadata_value = item.pop(f"meta_{column}", None)
            if metadata_value is not None:
                item[column] = metadata_value
        hydrated_rows.append(item)
    return hydrated_rows


def bucketize(rows, bucket_func):
    groups = {}
    for row in rows:
        bucket = bucket_func(row)
        groups.setdefault(bucket, []).append(row)
    return groups


def clamp(value, low, high):
    return max(low, min(value, high))


def normalize_catalyst_type(catalyst_type):
    normalized = (catalyst_type or "none").strip().lower()
    aliases = {
        "approval": "regulatory",
        "contract/partnership": "partnership",
        "licensing": "contract",
        "offering": "capital raise",
        "atm": "capital raise",
        "dilution": "capital raise",
        "product launch": "production",
    }
    return aliases.get(normalized, normalized)


def catalyst_bucket_name(catalyst_type):
    normalized = normalize_catalyst_type(catalyst_type)
    known_types = {
        "none",
        "merger",
        "regulatory",
        "clinical",
        "fda",
        "contract",
        "capital raise",
        "production",
        "earnings",
        "partnership",
        "patent",
        "short squeeze",
        "sec filing",
        "government contract",
    }
    if normalized in known_types:
        return normalized
    return "other"


def calculate_mention_sweet_spot_multiplier(mentions):
    if mentions < 5:
        return 0.85
    if mentions < 10:
        return 1.0
    if mentions <= 20:
        return 1.18
    if mentions <= 35:
        return 0.95
    return 0.8


def calculate_sentiment_timing_multiplier(sentiment):
    if sentiment < -0.2:
        return 0.75
    if sentiment < 0:
        return 0.95
    if sentiment <= 0.2:
        return 1.15
    if sentiment <= 0.4:
        return 1.0
    return 0.85


def calculate_anti_chase_multiplier(change_1d, change_3d=None, change_7d=None):
    penalty = 1.0
    if change_1d is not None:
        if change_1d > 75:
            penalty *= 0.45
        elif change_1d > 50:
            penalty *= 0.55
        elif change_1d > 30:
            penalty *= 0.70
        elif change_1d > 15:
            penalty *= 0.85

    if change_3d is not None:
        if change_3d > 120:
            penalty *= 0.55
        elif change_3d > 75:
            penalty *= 0.70
        elif change_3d > 40:
            penalty *= 0.85

    if change_7d is not None:
        if change_7d > 200:
            penalty *= 0.55
        elif change_7d > 100:
            penalty *= 0.75

    return max(penalty, 0.25)


def calculate_volume_confirmation_multiplier(relative_volume, price_change_1d):
    if relative_volume is None:
        return 1.0
    if relative_volume < 0.8:
        return 0.85
    if 2 <= relative_volume <= 5 and (price_change_1d or 0) < 15:
        return 1.10
    if 5 < relative_volume <= 12 and (price_change_1d or 0) < 20:
        return 1.15
    if relative_volume > 15 and (price_change_1d or 0) > 30:
        return 0.75
    return 1.0


def calculate_liquidity_multiplier(dollar_volume):
    if dollar_volume is None:
        return 0.90
    if dollar_volume < 100_000:
        return 0.40
    if dollar_volume < 500_000:
        return 0.65
    if dollar_volume < 1_000_000:
        return 0.80
    if dollar_volume < 5_000_000:
        return 1.00
    return 1.05


MARKET_CONFIRMATION_MULTIPLIERS = {
    "confirmed_early": 1.10,
    "neutral": 1.0,
    "pre_market_pending": 1.0,
    "unknown": 0.95,
    "volume_without_price": 0.95,
    "pre_market_prior_move": 0.90,
    "no_confirmation": 0.85,
    "price_without_volume": 0.75,
    "confirmed_but_extended": 0.75,
    "illiquid": 0.60,
    "post_spike_reversal": 0.60,
}


def calculate_backtest_catalyst_multiplier(catalyst_type):
    multipliers = {
        "none": 1.05,
        "merger": 1.08,
        "regulatory": 1.05,
        "clinical": 1.0,
        "fda": 0.9,
        "contract": 0.88,
        "capital raise": 0.75,
        "production": 0.95,
        "earnings": 0.98,
        "partnership": 0.95,
        "patent": 1.0,
        "short squeeze": 0.9,
        "sec filing": 0.95,
        "government contract": 0.92,
    }
    return multipliers.get(normalize_catalyst_type(catalyst_type), 0.95)


def calculate_persistence_multiplier(days_seen):
    if days_seen <= 1:
        return 1.0
    if days_seen <= 4:
        return 1.15
    if days_seen <= 7:
        return 0.95
    return 0.75


def add_shadow_scores(rows):
    seen_counts = {}
    scored_rows = []

    for row in sorted(rows, key=lambda item: (item["flagged_date"], item["ticker"])):
        ticker = row["ticker"]
        seen_counts[ticker] = seen_counts.get(ticker, 0) + 1

        mentions = row.get("flagged_mentions")
        if mentions is None:
            mentions = row.get("daily_mentions") or 0
        sentiment = row.get("flagged_sentiment")
        if sentiment is None:
            sentiment = row.get("daily_avg_sentiment") or 0
        engagement_ratio = row.get("engagement_ratio") or 0

        social_score = (
            math.log1p(max(mentions, 0))
            * calculate_mention_sweet_spot_multiplier(mentions)
            * (0.9 + clamp(engagement_ratio, 0, 1) * 0.15)
        )
        timing_score = (
            calculate_sentiment_timing_multiplier(sentiment)
            * calculate_anti_chase_multiplier(
                row.get("price_change_1d") or row.get("change_percent"),
                row.get("price_change_3d"),
                row.get("price_change_7d"),
            )
            * calculate_persistence_multiplier(seen_counts[ticker])
        )
        catalyst_score = calculate_backtest_catalyst_multiplier(
            row.get("catalyst_type")
        )
        vampire_multiplier = 0.15 if row.get("vampire_flagged") == 1 else 1.0

        # Decompose so pre-specified alternative curves score the SAME rows.
        log_mentions = math.log1p(max(mentions, 0))
        engagement_part = 0.9 + clamp(engagement_ratio, 0, 1) * 0.15
        sweet_multiplier = calculate_mention_sweet_spot_multiplier(mentions)
        sentiment_multiplier = calculate_sentiment_timing_multiplier(sentiment)
        chase_persist = calculate_anti_chase_multiplier(
            row.get("price_change_1d") or row.get("change_percent"),
            row.get("price_change_3d"),
            row.get("price_change_7d"),
        ) * calculate_persistence_multiplier(seen_counts[ticker])
        base = log_mentions * engagement_part * chase_persist * catalyst_score * vampire_multiplier

        enriched = dict(row)
        enriched["shadow_days_seen"] = seen_counts[ticker]
        enriched["shadow_score"] = base * sweet_multiplier * sentiment_multiplier
        enriched["shadow_flat_mentions"] = base * 1.0 * sentiment_multiplier
        enriched["shadow_flat_sentiment"] = base * sweet_multiplier * 1.0
        enriched["shadow_flat_both"] = base
        scored_rows.append(enriched)

    return scored_rows


def calculate_baseline_score(row):
    mentions = row.get("flagged_mentions")
    if mentions is None:
        mentions = row.get("daily_mentions") or 0
    sentiment = row.get("flagged_sentiment")
    if sentiment is None:
        sentiment = row.get("daily_avg_sentiment") or 0
    engagement_ratio = row.get("engagement_ratio") or 0

    attention_score = math.log1p(max(mentions, 0))
    engagement_multiplier = 1 + clamp(engagement_ratio, 0, 1) * 0.1
    sentiment_anchor = 1 + clamp(sentiment, -0.5, 0.5)
    return attention_score * sentiment_anchor * engagement_multiplier


def add_ablation_scores(rows):
    scored_rows = []
    for row in add_shadow_scores(rows):
        mentions = row.get("flagged_mentions")
        if mentions is None:
            mentions = row.get("daily_mentions") or 0

        baseline = calculate_baseline_score(row)
        mention_sweet = baseline * calculate_mention_sweet_spot_multiplier(mentions)
        vampire_adjusted = mention_sweet * (
            0.15 if row.get("vampire_flagged") == 1 else 1.0
        )
        catalyst_adjusted = vampire_adjusted * calculate_backtest_catalyst_multiplier(
            row.get("catalyst_type")
        )
        concentration_adjusted = catalyst_adjusted * (
            row.get("author_concentration_multiplier") or 1.0
        )
        promotion_adjusted = concentration_adjusted * (
            0.75 if (row.get("promotion_risk_score") or 0) > 0.5 else 1.0
        )
        anti_chase_adjusted = promotion_adjusted * calculate_anti_chase_multiplier(
            row.get("price_change_1d") or row.get("change_percent"),
            row.get("price_change_3d"),
            row.get("price_change_7d"),
        )
        volume_adjusted = anti_chase_adjusted * calculate_volume_confirmation_multiplier(
            row.get("relative_volume"),
            row.get("price_change_1d") or row.get("change_percent"),
        )
        liquidity_adjusted = volume_adjusted * calculate_liquidity_multiplier(
            row.get("dollar_volume")
        )
        market_confirmation_adjusted = (
            liquidity_adjusted
            * MARKET_CONFIRMATION_MULTIPLIERS.get(
                (row.get("market_confirmation_status") or "unknown"), 1.0
            )
        )

        enriched = dict(row)
        enriched["ablation_baseline"] = baseline
        enriched["ablation_mention_sweet_spot"] = mention_sweet
        enriched["ablation_vampire_penalty"] = vampire_adjusted
        enriched["ablation_catalyst"] = catalyst_adjusted
        enriched["ablation_author_concentration"] = concentration_adjusted
        enriched["ablation_promotion_risk"] = promotion_adjusted
        enriched["ablation_anti_chase"] = anti_chase_adjusted
        enriched["ablation_rvol"] = volume_adjusted
        enriched["ablation_liquidity"] = liquidity_adjusted
        enriched["ablation_market_confirmation"] = market_confirmation_adjusted
        enriched["ablation_full_model"] = row.get("trade_score")
        if enriched["ablation_full_model"] is None:
            enriched["ablation_full_model"] = row.get("final_score")
        scored_rows.append(enriched)

    return scored_rows


def daily_basket_returns(rows, score_col, basket_size, return_col, updated_col):
    rows_by_date = {}
    for row in rows:
        rows_by_date.setdefault(row["flagged_date"], []).append(row)

    returns = []
    for day_rows in rows_by_date.values():
        universe = [
            row
            for row in day_rows
            if row.get(updated_col) == 1
            and row.get(return_col) is not None
            and row.get(score_col) is not None
        ]
        if len(universe) < basket_size:
            continue
        top_rows = sorted(universe, key=lambda row: row[score_col], reverse=True)[
            :basket_size
        ]
        returns.append(safe_avg([row[return_col] for row in top_rows]))
    return returns


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


# ── Robust backtest sections ──────────────────────────────────────────────────
def robust_bucket_analysis(conn):
    rows = add_shadow_scores(fetch_backtest_rows(conn))

    print_robust_group_table(
        "ROBUST SCORE BUCKETS",
        "Avg, median, win rate, profit factor, and worst return by horizon",
        bucketize(
            rows,
            lambda row: (
                "1. High (>=0.8)"
                if (row.get("final_score") or 0) >= 0.8
                else "2. Mid (0.5-0.8)"
                if (row.get("final_score") or 0) >= 0.5
                else "3. Low (0.3-0.5)"
                if (row.get("final_score") or 0) >= 0.3
                else "4. Poor (<0.3)"
            ),
        ),
    )

    print_robust_group_table(
        "ROBUST MENTION BUCKETS",
        "Validates the 10-20 mention sweet spot against higher viral mention counts",
        bucketize(
            rows,
            lambda row: (
                "1. Viral (>20)"
                if (row.get("flagged_mentions") or 0) > 20
                else "2. Sweet (10-20)"
                if (row.get("flagged_mentions") or 0) >= 10
                else "3. Low (5-10)"
                if (row.get("flagged_mentions") or 0) >= 5
                else "4. Minimal (<5)"
            ),
        ),
    )

    print_robust_group_table(
        "ROBUST SENTIMENT BUCKETS",
        "Checks whether neutral discussion keeps outperforming euphoric discussion",
        bucketize(
            rows,
            lambda row: (
                "1. Strong (>=0.4)"
                if (row.get("flagged_sentiment") or 0) >= 0.4
                else "2. Mild (0.2-0.4)"
                if (row.get("flagged_sentiment") or 0) >= 0.2
                else "3. Neutral (0-0.2)"
                if (row.get("flagged_sentiment") or 0) >= 0
                else "4. Negative (<0)"
            ),
        ),
    )

    print_robust_group_table(
        "ROBUST CATALYST TYPE BUCKETS",
        "Catalyst buckets use the hydrated catalyst type captured for each flag",
        bucketize(
            rows,
            lambda row: catalyst_bucket_name(row.get("catalyst_type")),
        ),
    )


def anti_chase_validation(conn):
    rows = fetch_backtest_rows(conn)
    print_robust_group_table(
        "ANTI-CHASE VALIDATION",
        "Buckets by same-day price move when the ticker was flagged",
        bucketize(
            rows,
            lambda row: (
                "0. Unknown"
                if row.get("change_percent") is None
                else "1. Down/flat (<0%)"
                if row["change_percent"] < 0
                else "2. Up 0-5%"
                if row["change_percent"] < 5
                else "3. Up 5-10%"
                if row["change_percent"] < 10
                else "4. Up 10-20%"
                if row["change_percent"] < 20
                else "5. Up >20%"
            ),
        ),
    )


def mention_velocity_validation(conn):
    rows = fetch_backtest_rows(conn)
    print_robust_group_table(
        "MENTION VELOCITY VALIDATION",
        "Emerging/stale labels based on today's mentions versus recent history",
        bucketize(
            rows,
            lambda row: (
                f"1. {row['mention_velocity_label']}"
                if row.get("mention_velocity_label") == "emerging"
                else f"3. {row['mention_velocity_label']}"
                if row.get("mention_velocity_label") == "stale"
                else "2. steady/unknown"
            ),
        ),
    )


def volume_confirmation_validation(conn):
    rows = fetch_backtest_rows(conn)
    print_robust_group_table(
        "VOLUME CONFIRMATION VALIDATION",
        "Checks whether relative volume confirms social signal without overextension",
        bucketize(
            rows,
            lambda row: (
                "0. Unknown"
                if row.get("relative_volume") is None
                else "1. Confirmed RVOL >=3"
                if row["relative_volume"] >= 3
                and (row.get("price_change_1d") or row.get("change_percent") or 0)
                < 20
                else "2. Thin RVOL <0.8"
                if row["relative_volume"] < 0.8
                else "3. Normal volume"
            ),
        ),
    )


def top_n_portfolio_backtest(conn, score_col, label):
    rows = add_shadow_scores(fetch_backtest_rows(conn))
    rows_by_date = {}
    for row in rows:
        rows_by_date.setdefault(row["flagged_date"], []).append(row)

    section(
        f"TOP-N PORTFOLIO BACKTEST - {label}",
        "Daily equal-weight top baskets compared with same-day random candidates",
    )
    print(
        f"  {'N':>3} {'Hor':<4} {'Days':>5}  {'Avg':>9}  {'Median':>9}"
        f"  {'Win%':>6}  {'PF':>5}  {'Worst':>9}  {'RandAvg':>9}  {'Edge':>9}"
    )
    divider()

    rng = random.Random(42)
    horizons = RETURN_HORIZONS

    for basket_size in (3, 5, 10):
        for horizon, return_col, updated_col in horizons:
            top_basket_returns = []
            random_basket_returns = []

            for day_rows in rows_by_date.values():
                universe = [
                    row
                    for row in day_rows
                    if row.get(updated_col) == 1
                    and row.get(return_col) is not None
                    and row.get(score_col) is not None
                ]
                if len(universe) < basket_size:
                    continue

                top_rows = sorted(
                    universe,
                    key=lambda row: row[score_col],
                    reverse=True,
                )[:basket_size]
                top_basket_returns.append(
                    safe_avg([row[return_col] for row in top_rows])
                )

                daily_random_returns = []
                for _ in range(200):
                    sample = rng.sample(universe, basket_size)
                    daily_random_returns.append(
                        safe_avg([row[return_col] for row in sample])
                    )
                random_basket_returns.append(safe_avg(daily_random_returns))

            stats = value_stats(top_basket_returns)
            random_avg = safe_avg(random_basket_returns)
            edge = None
            if stats["avg"] is not None and random_avg is not None:
                edge = stats["avg"] - random_avg

            print(
                f"  {basket_size:>3} {horizon:<4} {stats['n']:>5}"
                f"  {fmt(stats['avg']):>9}  {fmt(stats['median']):>9}"
                f"  {pct(stats['win_rate']):>6}"
                f"  {fmt_profit_factor(stats['profit_factor']):>5}"
                f"  {fmt(stats['worst']):>9}"
                f"  {fmt(random_avg):>9}  {fmt(edge):>9}"
            )


def model_ablation_comparison(conn):
    rows = add_ablation_scores(fetch_backtest_rows(conn))
    models = [
        ("baseline_score", "ablation_baseline"),
        ("+ mention_sweet_spot", "ablation_mention_sweet_spot"),
        ("+ vampire penalty", "ablation_vampire_penalty"),
        ("+ catalyst", "ablation_catalyst"),
        ("+ author concentration", "ablation_author_concentration"),
        ("+ promotion risk", "ablation_promotion_risk"),
        ("+ anti-chase", "ablation_anti_chase"),
        ("+ RVOL", "ablation_rvol"),
        ("+ liquidity", "ablation_liquidity"),
        ("+ market confirmation", "ablation_market_confirmation"),
        ("full model", "ablation_full_model"),
    ]
    horizons = RETURN_HORIZONS

    section(
        "MODEL ABLATION COMPARISON",
        "Each row adds one feature block so weak multipliers cannot hide inside the full score",
    )
    print(
        f"  {'Model':<24} {'N':>3} {'Hor':<4} {'Days':>5}"
        f"  {'Avg':>9}  {'Median':>9}  {'Win%':>6}  {'PF':>5}  {'Worst':>9}"
    )
    divider()

    for label, score_col in models:
        for basket_size in (3, 5, 10):
            for horizon, return_col, updated_col in horizons:
                returns = daily_basket_returns(
                    rows,
                    score_col,
                    basket_size,
                    return_col,
                    updated_col,
                )
                stats = value_stats(returns)
                print(
                    f"  {label:<24} {basket_size:>3} {horizon:<4}"
                    f" {stats['n']:>5}  {fmt(stats['avg']):>9}"
                    f"  {fmt(stats['median']):>9}  {pct(stats['win_rate']):>6}"
                    f"  {fmt_profit_factor(stats['profit_factor']):>5}"
                    f"  {fmt(stats['worst']):>9}"
                )


def random_baseline_comparison(
    conn,
    score_col="final_score",
    label="Stored final_score",
):
    rows = add_ablation_scores(fetch_backtest_rows(conn))
    rows_by_date = {}
    for row in rows:
        rows_by_date.setdefault(row["flagged_date"], []).append(row)

    rng = random.Random(42)
    basket_size = 5
    samples = 500
    horizons = RETURN_HORIZONS

    section(
        f"RANDOM BASELINE COMPARISON - {label}",
        f"Top 5 by score versus {samples} random same-day baskets",
    )
    print(
        f"  {'Hor':<4} {'Days':>5}  {'TopAvg':>9}  {'TopMed':>9}"
        f"  {'Win%':>6}  {'PF':>5}  {'Worst':>9}  {'RandAvg':>9}  {'Pctile':>7}"
    )
    divider()

    for horizon, return_col, updated_col in horizons:
        top_returns = []
        random_day_avgs = []
        percentiles = []

        for day_rows in rows_by_date.values():
            universe = [
                row
                for row in day_rows
                if row.get(updated_col) == 1
                and row.get(return_col) is not None
                and row.get(score_col) is not None
            ]
            if len(universe) < basket_size:
                continue

            top_rows = sorted(universe, key=lambda row: row[score_col], reverse=True)[
                :basket_size
            ]
            top_return = safe_avg([row[return_col] for row in top_rows])
            random_returns = []
            for _ in range(samples):
                sample = rng.sample(universe, basket_size)
                random_returns.append(safe_avg([row[return_col] for row in sample]))

            top_returns.append(top_return)
            random_day_avgs.append(safe_avg(random_returns))
            percentiles.append(
                100.0
                * sum(
                    1 for random_return in random_returns if random_return <= top_return
                )
                / len(random_returns)
            )

        stats = value_stats(top_returns)
        print(
            f"  {horizon:<4} {stats['n']:>5}  {fmt(stats['avg']):>9}"
            f"  {fmt(stats['median']):>9}  {pct(stats['win_rate']):>6}"
            f"  {fmt_profit_factor(stats['profit_factor']):>5}"
            f"  {fmt(stats['worst']):>9}"
            f"  {fmt(safe_avg(random_day_avgs)):>9}"
            f"  {pct(safe_avg(percentiles)):>7}"
        )


def shadow_score_bucket_analysis(conn):
    rows = add_shadow_scores(fetch_backtest_rows(conn))
    scores = [
        row["shadow_score"] for row in rows if row.get("shadow_score") is not None
    ]
    if not scores:
        return

    sorted_scores = sorted(scores)
    q25 = sorted_scores[int(len(sorted_scores) * 0.25)]
    q50 = sorted_scores[int(len(sorted_scores) * 0.50)]
    q75 = sorted_scores[int(len(sorted_scores) * 0.75)]

    def shadow_bucket(row):
        score = row["shadow_score"]
        if score >= q75:
            return "1. Top quartile"
        if score >= q50:
            return "2. Upper-middle"
        if score >= q25:
            return "3. Lower-middle"
        return "4. Bottom quartile"

    print_robust_group_table(
        "SHADOW ATTENTION SCORE BUCKETS",
        "Tests attention/timing/quality/catalyst components without changing production score",
        bucketize(rows, shadow_bucket),
    )


def resolution_quality(conn):
    """Delisting/unresolvable/anomalous rates as first-class output, per horizon."""
    section(
        "RESOLUTION QUALITY / DELISTING RATE",
        "Unresolvable + anomalous + sub-penny rows are excluded from return stats above",
    )
    horizons = [
        ("T+1", "resolution_status_t1"),
        ("T+3", "resolution_status_t3"),
        ("T+7", "resolution_status_t7"),
        ("T+14", "resolution_status_t14"),
        ("T+30", "resolution_status_t30"),
    ]
    print(f"  {'Hor':<5} {'resolved':>9} {'unresolv.':>9} {'anomalous':>9} {'excluded':>9} {'open':>7} {'unres%':>7}")
    divider()
    for label, col in horizons:
        rows = conn.execute(
            f"""
            SELECT COALESCE({col}, 'open') AS status, COUNT(*) AS n
            FROM performance_tracking
            {date_clause()}
            GROUP BY status
            """,
            params(),
        ).fetchall()
        counts = {row["status"]: row["n"] for row in rows}
        resolved = counts.get("resolved", 0)
        unresolvable = counts.get("unresolvable", 0)
        anomalous = counts.get("anomalous", 0)
        excluded = counts.get("excluded", 0)
        open_rows = counts.get("open", 0)
        closed = resolved + unresolvable + anomalous
        unres_pct = (100.0 * unresolvable / closed) if closed else 0.0
        print(
            f"  {label:<5} {resolved:>9} {unresolvable:>9} {anomalous:>9}"
            f" {excluded:>9} {open_rows:>7} {unres_pct:>6.1f}%"
        )


def continuation_vs_exhaustion(conn):
    """
    The mid-move entry question: among names that had ALREADY moved >=20% over 3d
    at flag time, do quality signals separate continuers from reversers?
    """
    rows = fetch_backtest_rows(conn)

    def moved_amount(row):
        change_3d = row.get("price_change_3d")
        if change_3d is None:
            change_3d = row.get("change_percent")
        return change_3d or 0

    moved = [row for row in rows if moved_amount(row) >= 20]

    def bucket(row):
        has_catalyst = row.get("catalyst_multiplier_eligible") == 1
        broad = (
            (row.get("unique_authors") or 0) >= 5
            and (row.get("top_author_share") if row.get("top_author_share") is not None else 1.0) <= 0.4
        )
        cat = "1.catalyst" if has_catalyst else "2.no_catalyst"
        breadth = "broad" if broad else "narrow"
        return f"{cat}+{breadth}"

    print_robust_group_table(
        "CONTINUATION vs EXHAUSTION (flagged after >=20% 3-day move)",
        "Tests whether catalyst + author breadth separate continuation from reversal at mid-move entries",
        bucketize(moved, bucket),
    )


# ── Cohort backtesting ────────────────────────────────────────────────────────
def parse_failed_reasons(row):
    raw_reasons = row.get("failed_reasons")
    if not raw_reasons:
        return []
    if isinstance(raw_reasons, list):
        return raw_reasons
    try:
        parsed = json.loads(raw_reasons)
    except (TypeError, json.JSONDecodeError):
        return [
            reason.strip()
            for reason in str(raw_reasons).split(",")
            if reason.strip()
        ]
    if isinstance(parsed, list):
        return [str(reason) for reason in parsed if reason]
    return []


def normalized_cohort(row):
    cohort = row.get("cohort")
    if cohort:
        return cohort
    if (
        row.get("trade_gate_passed") == 1
        or row.get("threadradar_signal") == "trade_candidate"
    ):
        return "best_trade_candidate"
    if (
        row.get("threadradar_signal") == "avoid"
        or row.get("threadradar_risk_action") == "avoid_or_watch"
    ):
        return "avoid_high_risk"
    if row.get("is_near_miss") == 1:
        return "near_miss_candidate"
    if row.get("radar_score") is not None:
        return "radar_watchlist"
    return "scored_not_selected"


def cohort_performance(conn):
    rows = fetch_backtest_rows(conn)
    print_robust_group_table(
        "COHORT PERFORMANCE",
        "Compares best trades, radar names, avoided names, near misses, and other scored rows",
        bucketize(rows, normalized_cohort),
    )


def avoid_side_test(conn):
    """Compare avoid/vampire warnings with the rest of each same-day universe."""
    rows_by_date = {}
    rows = [
        row
        for row in fetch_backtest_rows(conn)
        if row["flagged_date"] >= V2_FREEZE_DATE
        and row.get("scoring_version") == V2_SCORING_VERSION
    ]
    for row in rows:
        rows_by_date.setdefault(row["flagged_date"], []).append(row)

    section(
        "AVOID-SIDE TEST (MEASUREMENT ONLY — NOT A SHORT STRATEGY)",
        "V2-only daily avoid/vampire mean return minus all other same-day flags",
    )
    print(
        f"  {'Date':<12} {'Hor':<5} {'AvoidN':>6} {'AvoidAvg':>10}"
        f" {'RestN':>6} {'RestAvg':>10} {'Spread':>10}"
    )
    divider()

    spreads_by_horizon = {"T+7": [], "T+14": []}
    horizons = (
        ("T+7", "return_7d", "updated_7d"),
        ("T+14", "return_t14", "updated_t14"),
    )
    for flagged_date in sorted(rows_by_date):
        day_rows = rows_by_date[flagged_date]
        for horizon, return_col, updated_col in horizons:
            resolved = [
                row
                for row in day_rows
                if row.get(updated_col) == 1 and row.get(return_col) is not None
            ]
            avoid_rows = [
                row
                for row in resolved
                if normalized_cohort(row) == "avoid_high_risk"
                or row.get("vampire_flagged") == 1
            ]
            rest_rows = [
                row
                for row in resolved
                if not (
                    normalized_cohort(row) == "avoid_high_risk"
                    or row.get("vampire_flagged") == 1
                )
            ]
            if not avoid_rows or not rest_rows:
                continue

            avoid_avg = safe_avg([row[return_col] for row in avoid_rows])
            rest_avg = safe_avg([row[return_col] for row in rest_rows])
            spread = avoid_avg - rest_avg
            spreads_by_horizon[horizon].append(spread)
            print(
                f"  {flagged_date:<12} {horizon:<5} {len(avoid_rows):>6}"
                f" {fmt(avoid_avg):>10} {len(rest_rows):>6}"
                f" {fmt(rest_avg):>10} {fmt(spread):>10}"
            )

    print()
    print(
        f"  {'Horizon':<8} {'Days':>5} {'Median spread':>15}"
        f" {'Avoid underperformed':>21}"
    )
    divider()
    for horizon in ("T+7", "T+14"):
        spreads = spreads_by_horizon[horizon]
        underperformed = (
            100.0 * sum(1 for spread in spreads if spread < 0) / len(spreads)
            if spreads
            else None
        )
        print(
            f"  {horizon:<8} {len(spreads):>5} {fmt(safe_median(spreads)):>15}"
            f" {pct(underperformed):>21}"
        )


def gate_outcome_performance(conn):
    rows = fetch_backtest_rows(conn)
    print_robust_group_table(
        "GATE OUTCOME PERFORMANCE",
        "Tests whether the final trade gate is adding value versus rejected candidates",
        bucketize(
            rows,
            lambda row: (
                "1. gate_passed"
                if normalized_cohort(row) == "best_trade_candidate"
                or row.get("trade_gate_passed") == 1
                else "2. gate_failed"
            ),
        ),
    )
    print_robust_group_table(
        "ENTRY DECISION PERFORMANCE",
        "Breaks outcomes down by the stored trade/watch/avoid/no-trade decision",
        bucketize(rows, lambda row: row.get("entry_decision") or normalized_cohort(row)),
    )


def near_miss_performance(conn):
    rows = fetch_backtest_rows(conn)
    near_miss_rows = [
        row
        for row in rows
        if row.get("is_near_miss") == 1
        or normalized_cohort(row) == "near_miss_candidate"
    ]
    if not near_miss_rows:
        section(
            "NEAR-MISS PERFORMANCE",
            "No near-miss cohort rows yet. Future runs will populate is_near_miss.",
        )
        return
    print_robust_group_table(
        "NEAR-MISS PERFORMANCE",
        "Checks whether rejected high trade_score names later became hidden winners",
        bucketize(
            [
                row
                for row in rows
                if normalized_cohort(row)
                in {"best_trade_candidate", "radar_watchlist", "avoid_high_risk"}
                or row in near_miss_rows
            ],
            lambda row: (
                "near_miss_candidate"
                if row.get("is_near_miss") == 1
                else normalized_cohort(row)
            ),
        ),
    )


def reason_groups(rows, fallback_for_missing=False):
    groups = {}
    for row in rows:
        reasons = parse_failed_reasons(row)
        if fallback_for_missing and not reasons:
            if row.get("setup_type"):
                reasons.append(f"setup_type:{row['setup_type']}")
            if row.get("market_confirmation_status"):
                reasons.append(f"market_status:{row['market_confirmation_status']}")
            if row.get("risk_score") is not None and row.get("risk_score", 0) > 35:
                reasons.append("risk_score_too_high")
            if (
                row.get("promotion_risk_score") is not None
                and row.get("promotion_risk_score", 0) >= 0.25
            ):
                reasons.append("promotion_risk")
        for reason in reasons:
            groups.setdefault(reason, []).append(row)
    return groups


def avoid_reason_performance(conn):
    rows = [
        row
        for row in fetch_backtest_rows(conn)
        if normalized_cohort(row) == "avoid_high_risk"
    ]
    groups = reason_groups(rows, fallback_for_missing=True)
    if not groups:
        section(
            "AVOID REASON PERFORMANCE",
            "No avoid reason metadata yet. Future runs will populate failed_reasons.",
        )
        return
    print_robust_group_table(
        "AVOID REASON PERFORMANCE",
        "If an avoid reason performs well, it may belong in watchlist sizing instead of hard avoid",
        groups,
    )


def failed_reason_performance(conn):
    rows = fetch_backtest_rows(conn)
    groups = reason_groups(rows, fallback_for_missing=False)
    if not groups:
        section(
            "FAILED REASON PERFORMANCE",
            "No failed_reasons metadata yet. Future runs will populate this section.",
        )
        return
    print_robust_group_table(
        "FAILED REASON PERFORMANCE",
        "Explodes each failed gate reason so we can see which filters help or hurt",
        groups,
    )


def no_trade_day_analysis(conn):
    rows = fetch_backtest_rows(conn)
    rows_by_date = {}
    for row in rows:
        rows_by_date.setdefault(row["flagged_date"], []).append(row)

    horizons = RETURN_HORIZONS
    groups = {
        "top_radar_no_trade_day": {horizon: [] for horizon, _, _ in horizons},
        "near_miss_no_trade_day": {horizon: [] for horizon, _, _ in horizons},
        "avoid_no_trade_day": {horizon: [] for horizon, _, _ in horizons},
    }

    no_trade_days = 0
    for day_rows in rows_by_date.values():
        has_trade = any(
            normalized_cohort(row) == "best_trade_candidate"
            or row.get("trade_gate_passed") == 1
            for row in day_rows
        )
        if has_trade:
            continue
        no_trade_days += 1

        for horizon, return_col, updated_col in horizons:
            resolved = [
                row
                for row in day_rows
                if row.get(updated_col) == 1 and row.get(return_col) is not None
            ]
            if not resolved:
                continue

            top_radar = sorted(
                [row for row in resolved if row.get("radar_score") is not None],
                key=lambda row: row.get("radar_score") or 0,
                reverse=True,
            )[:5]
            near_miss = sorted(
                [
                    row
                    for row in resolved
                    if row.get("is_near_miss") == 1
                    or normalized_cohort(row) == "near_miss_candidate"
                ],
                key=lambda row: row.get("near_miss_rank") or 999,
            )[:5]
            avoid = [
                row for row in resolved if normalized_cohort(row) == "avoid_high_risk"
            ]

            if top_radar:
                groups["top_radar_no_trade_day"][horizon].append(
                    safe_avg([row[return_col] for row in top_radar])
                )
            if near_miss:
                groups["near_miss_no_trade_day"][horizon].append(
                    safe_avg([row[return_col] for row in near_miss])
                )
            if avoid:
                groups["avoid_no_trade_day"][horizon].append(
                    safe_avg([row[return_col] for row in avoid])
                )

    section(
        "NO-TRADE DAY ANALYSIS",
        f"Checks whether days with zero trade candidates were correctly skipped ({no_trade_days} days)",
    )
    print(
        f"  {'Basket':<26} {'Hor':<4} {'Days':>5}  {'Avg':>9}  {'Median':>9}"
        f"  {'Win%':>6}  {'PF':>5}  {'Worst':>9}  {'Best':>9}"
    )
    divider()
    for basket_name, horizon_values in groups.items():
        for horizon, _, _ in horizons:
            stats = value_stats(horizon_values[horizon])
            print(
                f"  {basket_name:<26} {horizon:<4} {stats['n']:>5}"
                f"  {fmt(stats['avg']):>9}  {fmt(stats['median']):>9}"
                f"  {pct(stats['win_rate']):>6}"
                f"  {fmt_profit_factor(stats['profit_factor']):>5}"
                f"  {fmt(stats['worst']):>9}  {fmt(stats['best']):>9}"
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
        default=START_DATE,
        help="Only include rows on or after this YYYY-MM-DD date (default: 2026-06-10)",
    )
    args = parser.parse_args()
    DB_PATH = args.db
    START_DATE = args.start_date

    VERSION_CUTOFF = "2026-06-10"  # float-aware-v1 freeze date
    if not START_DATE or START_DATE < VERSION_CUTOFF:
        print()
        print("  " + "!" * 66)
        print("  !  START_DATE precedes the 2026-06-10 scoring freeze.")
        print("  !  Rows are scored under MIXED formula versions in this run:")
        print("  !    VALID   : return/feature sections (hit rate, anti-chase,")
        print("  !              mention/sentiment buckets, continuation, random baseline)")
        print("  !    INVALID : cohort, gate, near-miss, failed-reason, no-trade-day,")
        print("  !              and score-bucket sections (labels from replaced formulas)")
        print("  !  Run again with --start-date 2026-06-10 for cohort/gate reads.")
        print("  " + "!" * 66)

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
    resolution_quality(conn)
    hit_rate(conn)
    robust_bucket_analysis(conn)
    cohort_performance(conn)
    avoid_side_test(conn)
    gate_outcome_performance(conn)
    no_trade_day_analysis(conn)
    near_miss_performance(conn)
    avoid_reason_performance(conn)
    failed_reason_performance(conn)
    anti_chase_validation(conn)
    continuation_vs_exhaustion(conn)
    mention_velocity_validation(conn)
    volume_confirmation_validation(conn)
    top_n_portfolio_backtest(conn, "final_score", "Stored final_score")
    model_ablation_comparison(conn)
    random_baseline_comparison(conn, "ablation_full_model", "Full model")
    shadow_score_bucket_analysis(conn)
    top_n_portfolio_backtest(conn, "shadow_score", "Shadow attention score")
    top_n_portfolio_backtest(conn, "shadow_flat_mentions", "Shadow variant: FLAT mention curve")
    top_n_portfolio_backtest(conn, "shadow_flat_sentiment", "Shadow variant: FLAT sentiment curve")
    top_n_portfolio_backtest(conn, "shadow_flat_both", "Shadow variant: FLAT both curves")
    mod_impact(conn)
    vampire_impact(conn)
    catalyst_split(conn)
    catalyst_types(conn)
    consistency_signal(conn)
    extremes(conn)

    conn.close()

    print()
    divider("═")
    print("  Note: catalyst sections use Apr 27+ data only.")
    print("  Re-run in 4 weeks for statistically meaningful catalyst results.")
    divider("═")
    print()
