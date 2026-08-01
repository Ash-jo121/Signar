import sqlite3
import os

conn = sqlite3.connect("backend/threadradar.db")
tables = [
    "daily_sentiment",
    "daily_contexts",
    "posts",
    "bearish_stocks",
    "performance_tracking",
    "author_mentions",
    "author_track_record",
]

for t in tables:
    try:
        count = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t}: {count} rows")
    except Exception as e:
        print(f"  {t}: ERROR - {e}")

today = os.environ.get("TODAY", "")
if today:
    for t in [
        "daily_sentiment",
        "daily_contexts",
        "performance_tracking",
        "author_mentions",
    ]:
        try:
            col = {
                "performance_tracking": "flagged_date",
                "author_mentions": "mention_date",
            }.get(t, "date")
            count = conn.execute(
                f"SELECT COUNT(*) FROM {t} WHERE {col} = ?", (today,)
            ).fetchone()[0]
            print(f"  {t} today ({today}): {count} rows")
        except Exception as e:
            print(f"  {t} today: ERROR - {e}")

conn.close()
