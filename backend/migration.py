# run_migration.py — run once then delete
import sqlite3

conn = sqlite3.connect("threadradar.db")
migrations = [
    "ALTER TABLE daily_sentiment ADD COLUMN mod_flagged INTEGER DEFAULT 0",
    "ALTER TABLE daily_sentiment ADD COLUMN mod_flag_type TEXT",
    "ALTER TABLE daily_sentiment ADD COLUMN has_catalyst INTEGER DEFAULT 0",
    "ALTER TABLE daily_sentiment ADD COLUMN catalyst_type TEXT",
]
for sql in migrations:
    try:
        conn.execute(sql)
        print(f"✓ {sql}")
    except sqlite3.OperationalError as e:
        print(f"  Already exists: {e}")
conn.commit()
conn.close()
print("Migration complete")
# ```

# ---

# **What you'll see in tomorrow's logs:**
# ```
# ASTC: MOD INTERVENTION detected → score 0.428 × 0.2   (if flagged)
# BFRG: community pump warning (upvotes=15) → score 0.511 × 0.4

# Step 5: Catalyst assessment for filtered results...
#   BFRG: has_catalyst=True type=contract confidence=0.95 | Commercial agreement with top-5 pharma announced
#   POLA: has_catalyst=False type=none confidence=0.85 | Only technical analysis and float discussion
#   ASTC: has_catalyst=True type=contract confidence=0.9 | DHS $1B screening upgrade contract mentioned
# ```

# And in `output.txt`:
# ```
# $BFRG [CATALYST: CONTRACT]
#   Mentions: 33.0 | Sentiment: +0.258 | Score: +0.511

# $POLA [NO CATALYST]
#   Mentions: 32.2 | Sentiment: +0.405 | Score: +0.498
