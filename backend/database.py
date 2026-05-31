import json
import sqlite3
import time
from datetime import datetime

from runtime_paths import data_path

# Uses Railway's persistent /data volume in production and backend/ locally.
DB_PATH = str(data_path("threadradar.db"))

# Wait for locks instead of failing immediately (SQLite default is short).
_SQLITE_TIMEOUT_S = 30.0
_BUSY_TIMEOUT_MS = 30_000

SCORE_METADATA_COLUMNS = [
    ("radar_score", "REAL DEFAULT 0.0"),
    ("trade_score", "REAL DEFAULT 0.0"),
    ("risk_score", "REAL DEFAULT 0.0"),
    ("signal_score", "REAL DEFAULT 0.0"),
    ("risk_level", "TEXT"),
    ("setup_type", "TEXT"),
    ("catalyst_confidence", "REAL DEFAULT 0.0"),
    ("catalyst_multiplier_eligible", "INTEGER DEFAULT 0"),
    ("catalyst_has_concrete_event", "INTEGER DEFAULT 0"),
    ("catalyst_gate_reason", "TEXT"),
    ("promotion_risk_score", "REAL DEFAULT 0.0"),
    ("promotion_terms_count", "INTEGER DEFAULT 0"),
    ("unrealistic_target_count", "INTEGER DEFAULT 0"),
    ("setup_trade_multiplier", "REAL DEFAULT 1.0"),
    ("risk_score_multiplier", "REAL DEFAULT 1.0"),
    ("freshness_multiplier", "REAL DEFAULT 1.0"),
    ("promotion_trade_multiplier", "REAL DEFAULT 1.0"),
    ("author_concentration_multiplier", "REAL DEFAULT 1.0"),
    ("unique_authors", "INTEGER DEFAULT 0"),
    ("top_author_mentions", "INTEGER DEFAULT 0"),
    ("top_author_share", "REAL DEFAULT 0.0"),
    ("first_seen_date", "TEXT"),
    ("first_seen_datetime", "TEXT"),
    ("days_since_first_seen", "INTEGER DEFAULT 0"),
    ("days_trending", "INTEGER DEFAULT 1"),
    ("previous_day_mentions", "REAL"),
    ("mention_change_pct", "REAL"),
    ("earlyness_multiplier", "REAL DEFAULT 1.0"),
    ("mentions_today", "REAL DEFAULT 0.0"),
    ("mentions_yesterday", "REAL"),
    ("mentions_3d_avg", "REAL"),
    ("mention_acceleration", "REAL DEFAULT 0.0"),
    ("mention_velocity_label", "TEXT"),
    ("mention_declining_2d", "INTEGER DEFAULT 0"),
    ("price_change_1d", "REAL"),
    ("price_change_3d", "REAL"),
    ("price_change_7d", "REAL"),
    ("previous_close", "REAL"),
    ("open_price", "REAL"),
    ("high_price", "REAL"),
    ("low_price", "REAL"),
    ("close_price", "REAL"),
    ("adjusted_close", "REAL"),
    ("average_volume", "REAL"),
    ("avg_volume_10d", "REAL"),
    ("avg_volume_30d", "REAL"),
    ("relative_volume", "REAL"),
    ("relative_volume_10d", "REAL"),
    ("relative_volume_30d", "REAL"),
    ("dollar_volume", "REAL"),
    ("volume_change_vs_avg", "REAL"),
    ("gap_pct", "REAL"),
    ("intraday_range_pct", "REAL"),
    ("distance_from_20dma_pct", "REAL"),
    ("market_data_as_of", "TEXT"),
    ("market_data_source", "TEXT"),
    ("market_data_timestamp", "TEXT"),
    ("liquidity_multiplier", "REAL DEFAULT 1.0"),
    ("volume_confirmation_multiplier", "REAL DEFAULT 1.0"),
    ("anti_chase_multiplier", "REAL DEFAULT 1.0"),
    ("market_confirmation_status", "TEXT"),
    ("threadradar_signal", "TEXT"),
    ("threadradar_recommendation", "TEXT"),
    ("threadradar_trade_status", "TEXT"),
    ("threadradar_risk_action", "TEXT"),
    ("trade_action", "TEXT"),
    ("trade_reason", "TEXT"),
    ("cohort", "TEXT"),
    ("trade_gate_passed", "INTEGER DEFAULT 0"),
    ("ranking_bucket", "TEXT"),
    ("failed_reasons", "TEXT"),
    ("is_near_miss", "INTEGER DEFAULT 0"),
    ("near_miss_rank", "INTEGER"),
    ("entry_decision", "TEXT"),
    ("no_trade_day", "INTEGER DEFAULT 0"),
]

RUN_METADATA_COLUMNS = [
    ("market_session", "TEXT NOT NULL DEFAULT 'open'"),
    ("market_closed_reason", "TEXT"),
    ("price_update_status", "TEXT NOT NULL DEFAULT 'eligible'"),
    ("eligible_for_backtest", "INTEGER DEFAULT 1"),
    ("next_trading_session_signal", "INTEGER DEFAULT 0"),
]


def ensure_column(conn, table, column, definition):
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def score_metadata_values(result):
    return (
        result.get("radar_score", 0),
        result.get("trade_score", result.get("final_score", 0)),
        result.get("risk_score", 0),
        result.get("signal_score", result.get("final_score", 0)),
        result.get("risk_level"),
        result.get("setup_type"),
        result.get("catalyst_confidence", 0),
        1 if result.get("catalyst_multiplier_eligible") else 0,
        1 if result.get("catalyst_has_concrete_event") else 0,
        result.get("catalyst_gate_reason"),
        result.get("promotion_risk_score", 0),
        result.get("promotion_terms_count", 0),
        result.get("unrealistic_target_count", 0),
        result.get("setup_trade_multiplier", 1.0),
        result.get("risk_score_multiplier", 1.0),
        result.get("freshness_multiplier", 1.0),
        result.get("promotion_trade_multiplier", 1.0),
        result.get("author_concentration_multiplier", 1.0),
        result.get("unique_authors", 0),
        result.get("top_author_mentions", 0),
        result.get("top_author_share", 0),
        result.get("first_seen_date"),
        result.get("first_seen_datetime"),
        result.get("days_since_first_seen", 0),
        result.get("days_trending", 1),
        result.get("previous_day_mentions"),
        result.get("mention_change_pct"),
        result.get("earlyness_multiplier", 1.0),
        result.get("mentions_today", result.get("mentions", 0)),
        result.get("mentions_yesterday"),
        result.get("mentions_3d_avg"),
        result.get("mention_acceleration", 0),
        result.get("mention_velocity_label"),
        1 if result.get("mention_declining_2d") else 0,
        result.get("price_change_1d"),
        result.get("price_change_3d"),
        result.get("price_change_7d"),
        result.get("previous_close"),
        result.get("open_price"),
        result.get("high_price"),
        result.get("low_price"),
        result.get("close_price"),
        result.get("adjusted_close"),
        result.get("average_volume"),
        result.get("avg_volume_10d"),
        result.get("avg_volume_30d"),
        result.get("relative_volume"),
        result.get("relative_volume_10d"),
        result.get("relative_volume_30d"),
        result.get("dollar_volume"),
        result.get("volume_change_vs_avg"),
        result.get("gap_pct"),
        result.get("intraday_range_pct"),
        result.get("distance_from_20dma_pct"),
        result.get("market_data_as_of"),
        result.get("market_data_source"),
        result.get("market_data_timestamp"),
        result.get("liquidity_multiplier", 1.0),
        result.get("volume_confirmation_multiplier", 1.0),
        result.get("anti_chase_multiplier", 1.0),
        result.get("market_confirmation_status"),
        result.get("threadradar_signal"),
        result.get("threadradar_recommendation"),
        result.get("threadradar_trade_status"),
        result.get("threadradar_risk_action"),
        result.get("trade_action"),
        result.get("trade_reason"),
        result.get("cohort"),
        1 if result.get("trade_gate_passed") else 0,
        result.get("ranking_bucket"),
        json.dumps(result.get("failed_reasons", [])),
        1 if result.get("is_near_miss") else 0,
        result.get("near_miss_rank"),
        result.get("entry_decision"),
        1 if result.get("no_trade_day") else 0,
    )


def save_score_metadata(conn, result, date):
    columns = [column for column, _ in SCORE_METADATA_COLUMNS]
    assignments = ", ".join(f"{column} = excluded.{column}" for column in columns)
    placeholders = ", ".join("?" for _ in columns)
    conn.execute(
        f"""
        INSERT INTO score_metadata
        (date, ticker, {", ".join(columns)})
        VALUES (?, ?, {placeholders})
        ON CONFLICT(date, ticker) DO UPDATE SET {assignments}
        """,
        (date, result["ticker"]) + score_metadata_values(result),
    )


def save_run_metadata(conn, metadata):
    conn.execute(
        """
        INSERT INTO run_metadata
        (run_date, market_session, market_closed_reason, price_update_status,
         eligible_for_backtest, next_trading_session_signal)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(run_date) DO UPDATE SET
            market_session = excluded.market_session,
            market_closed_reason = excluded.market_closed_reason,
            price_update_status = excluded.price_update_status,
            eligible_for_backtest = excluded.eligible_for_backtest,
            next_trading_session_signal = excluded.next_trading_session_signal
        """,
        (
            metadata["run_date"],
            metadata["market_session"],
            metadata.get("market_closed_reason"),
            metadata["price_update_status"],
            1 if metadata["eligible_for_backtest"] else 0,
            1 if metadata["next_trading_session_signal"] else 0,
        ),
    )


def save_market_data_snapshot(conn, result):
    market_date = result.get("market_data_as_of")
    if not market_date:
        return

    conn.execute(
        """
        INSERT INTO ticker_daily_market_data
        (ticker, date, open_price, high_price, low_price, close_price,
         adjusted_close, volume, source, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(ticker, date) DO UPDATE SET
            open_price = excluded.open_price,
            high_price = excluded.high_price,
            low_price = excluded.low_price,
            close_price = excluded.close_price,
            adjusted_close = excluded.adjusted_close,
            volume = excluded.volume,
            source = excluded.source,
            fetched_at = excluded.fetched_at
        """,
        (
            result["ticker"],
            market_date,
            result.get("open_price"),
            result.get("high_price"),
            result.get("low_price"),
            result.get("close_price", result.get("price")),
            result.get("adjusted_close"),
            result.get("volume"),
            result.get("market_data_source", "yfinance"),
            result.get("market_data_timestamp"),
        ),
    )


def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=_SQLITE_TIMEOUT_S)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
    return conn


def init_db():
    conn = get_connection()
    score_column_defs = ",\n            ".join(
        f"{column} {definition}" for column, definition in SCORE_METADATA_COLUMNS
    )

    conn.executescript("""-- Core table: one row per stock per day
        CREATE TABLE IF NOT EXISTS daily_sentiment (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            ticker TEXT NOT NULL,
            company_name TEXT,
            mentions REAL,
            avg_sentiment REAL,
            final_score REAL,
            price REAL,
            change_percent REAL,
            market_cap REAL,
            volume REAL,
            sector TEXT,
            mod_flagged INTEGER DEFAULT 0,
            mod_flag_type TEXT,
            has_catalyst INTEGER DEFAULT 0,
            catalyst_type TEXT,
            raw_final_score REAL,
            UNIQUE(date, ticker)
        );

        -- Contexts table: top Reddit comments per stock per day
        CREATE TABLE IF NOT EXISTS daily_contexts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            ticker TEXT NOT NULL,
            comment_text TEXT,
            sentiment TEXT,
            score REAL,
            source TEXT,
            UNIQUE(date, ticker, comment_text),
            FOREIGN KEY (date, ticker)
                REFERENCES daily_sentiment(date, ticker)
                ON DELETE CASCADE
        );

        -- Posts table: track which Reddit posts were scraped
        CREATE TABLE IF NOT EXISTS posts (
            id TEXT PRIMARY KEY,
            subreddit TEXT NOT NULL,
            title TEXT,
            body TEXT,
            post_score INTEGER,
            comment_count INTEGER,
            comment_count_at_analysis INTEGER DEFAULT 0,
            status TEXT DEFAULT 'active',
            created_utc REAL,
            last_analyzed REAL,
            fetched_utc REAL,
            author TEXT
        ); 
        
         -- Performance tracking table
        CREATE TABLE IF NOT EXISTS performance_tracking (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            flagged_date TEXT NOT NULL,
            flagged_price REAL,
            flagged_score REAL,
            flagged_sentiment REAL,
            flagged_mentions REAL,
            float_shares REAL,
            price_1d REAL,
            price_3d REAL,
            price_7d REAL,
            return_1d REAL,
            return_3d REAL,
            return_7d REAL,
            updated_1d INTEGER DEFAULT 0,
            updated_3d INTEGER DEFAULT 0,
            updated_7d INTEGER DEFAULT 0,
            has_catalyst INTEGER DEFAULT 0,
            catalyst_type TEXT DEFAULT 'none',
            mod_flagged INTEGER DEFAULT 0,
            vampire_flagged INTEGER DEFAULT 0,
            final_score REAL DEFAULT 0.0,
            engagement_ratio REAL DEFAULT 0.0,
            UNIQUE(ticker, flagged_date)
        );
        
        CREATE TABLE IF NOT EXISTS bearish_stocks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            flagged_date TEXT NOT NULL,
            source_subreddit TEXT DEFAULT 'VampireStocks',
            flag_type TEXT,
            confidence REAL,
            post_title TEXT,
            post_url TEXT,
            UNIQUE(ticker, flagged_date)
        );

        CREATE TABLE IF NOT EXISTS run_metadata (
            run_date TEXT PRIMARY KEY,
            market_session TEXT NOT NULL,
            market_closed_reason TEXT,
            price_update_status TEXT NOT NULL,
            eligible_for_backtest INTEGER DEFAULT 1,
            next_trading_session_signal INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS ticker_daily_market_data (
            ticker TEXT NOT NULL,
            date TEXT NOT NULL,
            open_price REAL,
            high_price REAL,
            low_price REAL,
            close_price REAL,
            adjusted_close REAL,
            volume REAL,
            source TEXT,
            fetched_at TEXT,
            PRIMARY KEY(ticker, date)
        );
        """)
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS score_metadata (
            date TEXT NOT NULL,
            ticker TEXT NOT NULL,
            {score_column_defs},
            PRIMARY KEY(date, ticker),
            FOREIGN KEY (date, ticker)
                REFERENCES daily_sentiment(date, ticker)
                ON DELETE CASCADE
        )
        """
    )
    for column, definition in SCORE_METADATA_COLUMNS:
        ensure_column(conn, "score_metadata", column, definition)
    for column, definition in RUN_METADATA_COLUMNS:
        ensure_column(conn, "run_metadata", column, definition)
    conn.commit()
    conn.close()
    print("Database initialized successfully")


if __name__ == "__main__":
    init_db()


def save_daily_results(results, date=None, run_metadata=None):
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")

    conn = get_connection()
    saved = 0
    skipped = 0

    if run_metadata:
        save_run_metadata(conn, run_metadata)

    for result in results:
        try:
            conn.execute(
                """
                INSERT OR IGNORE INTO daily_sentiment 
                (date, ticker, company_name, mentions, avg_sentiment, 
                 final_score, price, change_percent, market_cap, volume, sector,
                 mod_flagged, mod_flag_type, has_catalyst, catalyst_type, raw_final_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    date,
                    result["ticker"],
                    result.get("name", ""),
                    result.get("mentions", 0),
                    result.get("avg_sentiment", 0),
                    result.get("final_score", 0),
                    result.get("price", 0),
                    result.get("change_percent", 0),
                    result.get("market_cap", 0),
                    result.get("volume", 0),
                    result.get("sector", ""),
                    1 if result.get("mod_flagged") else 0,
                    result.get("mod_flag_type"),
                    1 if result.get("has_catalyst") else 0,
                    result.get("catalyst_type"),
                    result.get("raw_final_score", result.get("final_score", 0)),
                ),
            )
            save_score_metadata(conn, result, date)
            save_market_data_snapshot(conn, result)

            for ctx in result.get("top_contexts", []):
                conn.execute(
                    """
                    INSERT OR IGNORE INTO daily_contexts
                    (date, ticker, comment_text, sentiment, score, source)
                    VALUES (?, ?, ?, ?, ?, ?)
                """,
                    (
                        date,
                        result["ticker"],
                        ctx.get("text", "")[:500],
                        ctx.get("sentiment", "neutral"),
                        ctx.get("score", 0),
                        ctx.get("source", "comment"),
                    ),
                )

            saved += 1

        except sqlite3.IntegrityError:
            skipped += 1
            continue

    conn.commit()
    conn.close()
    print(f"Saved {saved} stocks to database, {skipped} already existed")


def save_post(post):
    """Save a scraped Reddit post"""
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO posts
            (id, subreddit, title, body, post_score, comment_count,
             status, created_utc, fetched_utc, author)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                post["id"],
                post["subreddit"],
                post["title"],
                post.get("selftext", "")[:1000],
                post.get("score", 0),
                post.get("num_comments", 0),
                "active",
                post.get("created_utc", 0),
                time.time(),
                post.get("author", "unknown"),
            ),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        pass  # post already exists
    finally:
        conn.close()


def get_ticker_history(ticker, days=30):
    """Get historical data for a specific ticker"""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT date, mentions, avg_sentiment, final_score, price
        FROM daily_sentiment
        WHERE ticker = ?
        ORDER BY date DESC
        LIMIT ?
    """,
        (ticker, days),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_daily_results(date=None):
    """Get all results for a specific date"""
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")

    conn = get_connection()
    rows = conn.execute(
        """
        SELECT * FROM daily_sentiment
        WHERE date = ?
        ORDER BY final_score DESC
    """,
        (date,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_consistent_tickers(min_appearances=3, days_back=14):
    """Find stocks appearing consistently over last N days"""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT 
            ticker,
            COUNT(DISTINCT date) as appearances,
            AVG(avg_sentiment) as avg_sentiment_trend,
            AVG(final_score) as avg_score,
            MAX(final_score) as peak_score,
            MAX(date) as last_seen
        FROM daily_sentiment
        WHERE date >= date('now', ?)
        GROUP BY ticker
        HAVING appearances >= ?
        ORDER BY appearances DESC, avg_score DESC
    """,
        (f"-{days_back} days", min_appearances),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def ticker_exists_today(ticker, date=None):
    """Check if ticker already saved for today"""
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")
    conn = get_connection()
    result = conn.execute(
        """
        SELECT id FROM daily_sentiment 
        WHERE date = ? AND ticker = ?
    """,
        (date, ticker),
    ).fetchone()
    conn.close()
    return result is not None


def get_active_posts():
    """Return all posts with status='active' created within last 3 days"""
    conn = get_connection()
    rows = conn.execute("""
        SELECT id, subreddit, title, body, post_score, comment_count,
               comment_count_at_analysis, created_utc, last_analyzed, author
        FROM posts
        WHERE status = 'active'
          AND created_utc >= strftime('%s', 'now', '-3 days')
        ORDER BY created_utc DESC
        """).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def update_post_after_refresh(post_id, new_comment_count):
    """Update comment count and last_analyzed timestamp after re-fetch"""
    conn = get_connection()
    conn.execute(
        """
        UPDATE posts
        SET comment_count = ?,
            comment_count_at_analysis = ?,
            last_analyzed = ?
        WHERE id = ?
        """,
        (new_comment_count, new_comment_count, time.time(), post_id),
    )
    conn.commit()
    conn.close()


def archive_old_posts():
    """Mark posts older than 3 days as archived"""
    conn = get_connection()
    result = conn.execute("""
        UPDATE posts
        SET status = 'archived'
        WHERE status = 'active'
          AND created_utc < strftime('%s', 'now', '-3 days')
        """)
    count = result.rowcount
    conn.commit()
    conn.close()
    if count:
        print(f"  Archived {count} posts older than 3 days")


def record_flagged_stocks(results, date=None):
    """Record today's flagged stocks with their price at time of flagging"""
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")

    conn = get_connection()
    saved = 0

    for result in results:
        try:
            conn.execute(
                """
                INSERT OR IGNORE INTO performance_tracking
                (ticker, flagged_date, flagged_price, flagged_score,
                 flagged_sentiment, flagged_mentions, float_shares,
                 has_catalyst, catalyst_type, mod_flagged, vampire_flagged,
                 final_score, engagement_ratio)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result["ticker"],
                    date,
                    result.get("price", 0),
                    result.get("final_score", 0),
                    result.get("avg_sentiment", 0),
                    result.get("mentions", 0),
                    result.get("float_shares", 0),
                    1 if result.get("has_catalyst") else 0,
                    result.get("catalyst_type", "none"),
                    1 if result.get("mod_flagged") else 0,
                    1 if result.get("vampire_flagged") else 0,
                    result.get("final_score", 0),
                    result.get("engagement_ratio", 0),
                ),
            )
            saved += 1
        except sqlite3.IntegrityError:
            continue

    conn.commit()
    conn.close()
    print(f"Performance tracking: recorded {saved} flagged stocks for {date}")
