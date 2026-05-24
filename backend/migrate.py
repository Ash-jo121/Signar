import os
import sqlite3

from database import RUN_METADATA_COLUMNS, SCORE_METADATA_COLUMNS

DB_PATH = os.path.join(os.path.dirname(__file__), "threadradar.db")

# Keep derived scoring/explanation fields out of the core daily/performance tables.
# The app can join score_metadata by (date, ticker), while backtests can join it
# with performance_tracking using flagged_date = date.
#
# New score metadata columns should be added to database.SCORE_METADATA_COLUMNS.
# This migration imports that list and idempotently adds any missing columns to
# score_metadata, so we do not need to duplicate the column list here.


def get_columns(conn, table):
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def ensure_column(conn, table, column, definition):
    columns = get_columns(conn, table)
    if column in columns:
        print(f"Column '{table}.{column}' already exists - skipping.")
        return

    print(f"Adding '{column}' column to {table} table...")
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def ensure_score_metadata_table(conn):
    """
    Create or update the normalized daily score metadata table.

    SCORE_METADATA_COLUMNS is the source of truth. The loop below is what
    migrates newly added columns such as setup/risk/freshness multipliers.
    """
    score_column_defs = ",\n            ".join(
        f"{column} {definition}" for column, definition in SCORE_METADATA_COLUMNS
    )

    print("Ensuring score_metadata table exists...")
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS score_metadata (
            date TEXT NOT NULL,
            ticker TEXT NOT NULL,
            {score_column_defs},
            PRIMARY KEY(date, ticker),
            FOREIGN KEY (date, ticker)
                REFERENCES daily_sentiment(date, ticker)
                ON DELETE CASCADE
        )
        """)

    for column, definition in SCORE_METADATA_COLUMNS:
        ensure_column(conn, "score_metadata", column, definition)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_score_metadata_ticker
        ON score_metadata(ticker)
        """)


def ensure_run_metadata_table(conn):
    print("Ensuring run_metadata table exists...")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS run_metadata (
            run_date TEXT PRIMARY KEY,
            market_session TEXT NOT NULL,
            market_closed_reason TEXT,
            price_update_status TEXT NOT NULL,
            eligible_for_backtest INTEGER DEFAULT 1,
            next_trading_session_signal INTEGER DEFAULT 0
        )
        """)
    for column, definition in RUN_METADATA_COLUMNS:
        ensure_column(conn, "run_metadata", column, definition)


def ensure_market_data_table(conn):
    print("Ensuring ticker_daily_market_data table exists...")
    conn.execute("""
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
        )
        """)


def backfill_score_metadata_from_daily_sentiment(conn):
    """
    Move score metadata into the normalized table if a previous run stored it wide.

    This makes the migration safe across local DBs that may have briefly used the
    earlier draft schema, while doing nothing on clean existing DBs.
    """
    daily_columns = set(get_columns(conn, "daily_sentiment"))
    metadata_columns = [column for column, _ in SCORE_METADATA_COLUMNS]
    available_columns = [
        column for column in metadata_columns if column in daily_columns
    ]

    if not available_columns:
        return

    column_list = ", ".join(available_columns)
    print("Backfilling score_metadata from existing daily_sentiment score columns...")
    conn.execute(f"""
        INSERT OR IGNORE INTO score_metadata (date, ticker, {column_list})
        SELECT date, ticker, {column_list}
        FROM daily_sentiment
        """)


def migrate():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")

    ensure_score_metadata_table(conn)
    ensure_run_metadata_table(conn)
    ensure_market_data_table(conn)
    backfill_score_metadata_from_daily_sentiment(conn)
    conn.commit()

    print(f"score_metadata columns: {get_columns(conn, 'score_metadata')}")
    print("Migration complete.")
    conn.close()


if __name__ == "__main__":
    migrate()
