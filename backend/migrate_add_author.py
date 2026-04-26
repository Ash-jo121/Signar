# Migration: adds author column to posts table
# Safe to run multiple times (checks if column exists first)

import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), "threadradar.db")


def migrate():
    conn = sqlite3.connect(DB_PATH)

    # Check if column already exists
    columns = [
        row[1] for row in conn.execute("PRAGMA table_info(daily_sentiment)").fetchall()
    ]

    if "raw_final_score" in columns:
        print("Column 'raw_final_score' already exists — skipping migration.")
        conn.close()
        return

    print("Adding 'raw_final_score' column to daily_sentiment table...")
    conn.execute("ALTER TABLE daily_sentiment ADD COLUMN raw_final_score REAL")
    conn.commit()

    # Verify
    columns_after = [
        row[1] for row in conn.execute("PRAGMA table_info(daily_sentiment)").fetchall()
    ]
    print(f"daily_sentiment table columns: {columns_after}")
    print("Migration complete.")
    conn.close()


if __name__ == "__main__":
    migrate()
