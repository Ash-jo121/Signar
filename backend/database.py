import sqlite3
import os
from datetime import datetime

DB_PATH = "threadradar.db"


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
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
            fetched_utc REAL
        ); """
    )
    conn.commit()
    conn.close()
    print("Database initialized successfully")


if __name__ == "__main__":
    init_db()


def save_daily_results(results, date=None):
    """Save today's top picks to database"""
    if date is None:
        date = datetime.now().strftime("%d-%m-%Y")

    conn = get_connection()
    saved = 0
    skipped = 0

    for result in results:
        try:
            # Insert or ignore if already exists for this date
            conn.execute(
                """
                INSERT OR IGNORE INTO daily_sentiment 
                (date, ticker, company_name, mentions, avg_sentiment, 
                 final_score, price, change_percent, market_cap, volume, sector)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                ),
            )

            # Save top contexts for this ticker
            for ctx in result.get("top_contexts", []):
                conn.execute(
                    """
                    INSERT INTO daily_contexts
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
             status, created_utc, fetched_utc)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                post["id"],
                post["subreddit"],
                post["title"],
                post.get("body", "")[:1000],
                post.get("score", 0),
                len(post.get("comments", [])),
                "active",
                post.get("created_utc", 0),
                __import__("time").time(),
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
        date = datetime.now().strftime("%d-%m-%Y")

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
        date = datetime.now().strftime("%d-%m-%Y")
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
