import sqlite3
import time
from datetime import datetime

DB_PATH = "threadradar.db"

# Wait for locks instead of failing immediately (SQLite default is short).
_SQLITE_TIMEOUT_S = 30.0
_BUSY_TIMEOUT_MS = 30_000


def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=_SQLITE_TIMEOUT_S)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
    return conn


def init_db():
    conn = get_connection()

    conn.executescript(
        """-- Core table: one row per stock per day
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
        """
    )
    conn.commit()
    conn.close()
    print("Database initialized successfully")


if __name__ == "__main__":
    init_db()


def save_daily_results(results, date=None):
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")

    conn = get_connection()
    saved = 0
    skipped = 0

    for result in results:
        try:
            conn.execute(
                """
                INSERT OR IGNORE INTO daily_sentiment 
                (date, ticker, company_name, mentions, avg_sentiment, 
                 final_score, price, change_percent, market_cap, volume, sector,
                 mod_flagged, mod_flag_type, has_catalyst, catalyst_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                ),
            )

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
    rows = conn.execute(
        """
        SELECT id, subreddit, title, body, post_score, comment_count,
               comment_count_at_analysis, created_utc, last_analyzed, author
        FROM posts
        WHERE status = 'active'
          AND created_utc >= strftime('%s', 'now', '-3 days')
        ORDER BY created_utc DESC
        """
    ).fetchall()
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
    result = conn.execute(
        """
        UPDATE posts
        SET status = 'archived'
        WHERE status = 'active'
          AND created_utc < strftime('%s', 'now', '-3 days')
        """
    )
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
                 final_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                ),
            )
            saved += 1
        except sqlite3.IntegrityError:
            continue

    conn.commit()
    conn.close()
    print(f"Performance tracking: recorded {saved} flagged stocks for {date}")
