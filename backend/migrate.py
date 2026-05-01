# Migration: adds engagement_ratio column to performance_tracking table
# Safe to run multiple times (checks if column exists first)

import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), "threadradar.db")


def migrate():
    conn = sqlite3.connect(DB_PATH)

    # Check if column already exists
    columns = [
        row[1]
        for row in conn.execute("PRAGMA table_info(performance_tracking)").fetchall()
    ]

    if "engagement_ratio" in columns:
        print("Column 'engagement_ratio' already exists — skipping migration.")
        conn.close()
        return

    print("Adding 'engagement_ratio' column to performance_tracking table...")
    conn.execute("ALTER TABLE performance_tracking ADD COLUMN engagement_ratio REAL")
    conn.commit()

    # Verify
    columns_after = [
        row[1]
        for row in conn.execute("PRAGMA table_info(performance_tracking)").fetchall()
    ]
    print(f"performance_tracking table columns: {columns_after}")
    print("Migration complete.")
    conn.close()


if __name__ == "__main__":
    migrate()
