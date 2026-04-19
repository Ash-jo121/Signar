# Migration: adds author column to posts table
# Safe to run multiple times (checks if column exists first)

import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), "threadradar.db")


def migrate():
    conn = sqlite3.connect(DB_PATH)

    # Check if column already exists
    columns = [row[1] for row in conn.execute("PRAGMA table_info(posts)").fetchall()]

    if "author" in columns:
        print("Column 'author' already exists — skipping migration.")
        conn.close()
        return

    print("Adding 'author' column to posts table...")
    conn.execute("ALTER TABLE posts ADD COLUMN author TEXT")
    conn.commit()

    # Verify
    columns_after = [
        row[1] for row in conn.execute("PRAGMA table_info(posts)").fetchall()
    ]
    print(f"posts table columns: {columns_after}")
    print("Migration complete.")
    conn.close()


if __name__ == "__main__":
    migrate()
