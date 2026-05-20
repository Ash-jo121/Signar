import os
import sqlite3

from database import SCORE_METADATA_COLUMNS

DB_PATH = os.path.join(os.path.dirname(__file__), "threadradar.db")

# Keep derived scoring/explanation fields out of the core daily/performance tables.
# The app can join score_metadata by (date, ticker), while backtests can join it
# with performance_tracking using flagged_date = date.


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
    """Create the normalized daily score metadata table if it is missing."""
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
    backfill_score_metadata_from_daily_sentiment(conn)
    conn.commit()

    print(f"score_metadata columns: {get_columns(conn, 'score_metadata')}")
    print("Migration complete.")
    conn.close()


if __name__ == "__main__":
    migrate()
