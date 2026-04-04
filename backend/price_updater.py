import sqlite3
import time
from datetime import datetime
import pandas as pd
from database import get_connection
import yfinance as yf

# Tickers to skip in performance tracking
# These are exclusions that were added after some records were already created
EXCLUDED_TICKERS = {
    "WTI",
    "WTF",
    "LNG",
    "OIL",
    "GAS",
    "ETF",
    "SPY",
    "QQQ",
    "DJT",
    "RDDT",
    "PLTR",
    "GME",
    "AMC",
    "BYND",
    "BBBY",
    "SMCI",
    "DOW",
    "PSA",
    "DD",
    "ATH",
    "NFA",
    "YOLO",
    "FOMO",
}


def fetch_current_price(ticker):
    """Fetch current price using yfinance"""
    try:
        stock = yf.Ticker(ticker)
        price = stock.info.get("currentPrice") or stock.info.get("regularMarketPrice")
        if price:
            return round(float(price), 4)
    except Exception as e:
        print(f"  Price fetch failed for {ticker}: {e}")
    return None


def had_split_since(ticker, since_date):
    """
    Check if a stock had a reverse split between flagged_date and now.
    Returns (had_split, ratio) where ratio is the split multiplier.
    A ratio > 1 means reverse split (price went up artificially).
    """
    try:
        stock = yf.Ticker(ticker)
        splits = stock.splits
        if splits.empty:
            return False, 1.0

        since_ts = pd.Timestamp(since_date).tz_localize("America/New_York")
        if splits.index.tz is not None:
            since_ts = since_ts.tz_convert(splits.index.tz)
        recent_splits = splits[splits.index >= since_ts]

        if recent_splits.empty:
            return False, 1.0

        # Product of all split ratios since flagged date
        # yfinance stores splits as ratio (e.g. 0.0833 for 1:12 reverse split)
        combined_ratio = recent_splits.prod()
        return True, round(float(combined_ratio), 4)

    except Exception as e:
        print(f"  Split check failed for {ticker}: {e}")
        return False, 1.0


def is_anomalous_return(flagged_price, current_price, days):
    """
    Detect returns that are physically implausible without a corporate action.
    Uses different thresholds for T+1, T+3, T+7.
    Note: ELAB went 8x in a week — so threshold must be above that for genuine moves.
    """
    if flagged_price <= 0 or current_price <= 0:
        return False

    ratio = current_price / flagged_price

    # Thresholds by holding period
    # Set high enough to not flag genuine penny stock squeezes
    if days == 1 and ratio > 5.0:  # 5x in 1 day is almost always a split
        return True
    if days == 3 and ratio > 10.0:  # 10x in 3 days — split territory
        return True
    if days == 7 and ratio > 15.0:  # 15x in 7 days — split territory
        return True

    # Downside: 90%+ loss in any period is suspicious but possible
    # Don't auto-skip these — flag for review instead
    return False


def calculate_return(flagged_price, current_price):
    if not flagged_price or flagged_price == 0:
        return None
    return round(((current_price - flagged_price) / flagged_price) * 100, 2)


def process_update(conn, row, period_days, price_col, return_col, updated_col):
    """
    Process a single performance tracking update with split detection.
    Returns True if updated, False if skipped.
    """
    ticker = row["ticker"]
    flagged_date = row["flagged_date"]
    flagged_price = row["flagged_price"]

    # Skip excluded tickers
    if ticker in EXCLUDED_TICKERS:
        print(f"  {ticker} | SKIPPING — excluded ticker")
        conn.execute(
            f"UPDATE performance_tracking SET {updated_col} = 1 "
            f"WHERE ticker = ? AND flagged_date = ?",
            (ticker, flagged_date),
        )
        return False

    price = fetch_current_price(ticker)
    if not price:
        return False

    # Check for reverse split
    had_split, split_ratio = had_split_since(ticker, flagged_date)
    if had_split:
        print(
            f"  {ticker} | SPLIT DETECTED (ratio={split_ratio}) — "
            f"adjusting flagged price ${flagged_price} → "
            f"${round(flagged_price / split_ratio, 4)}"
        )
        # Adjust flagged price to post-split equivalent for fair comparison
        # If 1:12 reverse split, flagged_price × 12 = post-split equivalent
        # split_ratio from yfinance for reverse splits is < 1 (e.g. 0.0833 for 1:12)
        # So adjusted = flagged_price / split_ratio
        adjusted_flagged = round(flagged_price / split_ratio, 4)

        # Update flagged_price in DB to post-split adjusted
        conn.execute(
            "UPDATE performance_tracking SET flagged_price = ? "
            "WHERE ticker = ? AND flagged_date = ?",
            (adjusted_flagged, ticker, flagged_date),
        )
        flagged_price = adjusted_flagged

    # Sanity check after adjustment
    if is_anomalous_return(flagged_price, price, period_days):
        print(
            f"  {ticker} | ANOMALOUS RETURN after adjustment "
            f"(flagged=${flagged_price}, current=${price}) — marking updated, skipping"
        )
        # Mark as updated so we don't retry — flag in DB with sentinel value
        conn.execute(
            f"UPDATE performance_tracking "
            f"SET {price_col} = ?, {return_col} = ?, {updated_col} = 1 "
            f"WHERE ticker = ? AND flagged_date = ?",
            (price, -999.0, ticker, flagged_date),  # -999 = anomaly flag
        )
        return False

    ret = calculate_return(flagged_price, price)
    conn.execute(
        f"UPDATE performance_tracking "
        f"SET {price_col} = ?, {return_col} = ?, {updated_col} = 1 "
        f"WHERE ticker = ? AND flagged_date = ?",
        (price, ret, ticker, flagged_date),
    )

    split_note = f" [split-adjusted]" if had_split else ""
    print(
        f"  {ticker} | flagged @ ${flagged_price}{split_note} "
        f"→ T+{period_days} @ ${price} | return: {ret:+.2f}%"
    )
    return True


def update_performance_prices():
    conn = get_connection()
    today = datetime.now().strftime("%Y-%m-%d")
    updated_total = 0

    print(f"=== Price Updater — {today} ===\n")

    # T+1
    pending_1d = conn.execute(
        """
        SELECT ticker, flagged_date, flagged_price
        FROM performance_tracking
        WHERE updated_1d = 0
          AND flagged_price > 0
          AND julianday(?) - julianday(flagged_date) >= 1
        """,
        (today,),
    ).fetchall()

    if pending_1d:
        print(f"Updating T+1 prices for {len(pending_1d)} stocks...")
        for row in pending_1d:
            if process_update(conn, row, 1, "price_1d", "return_1d", "updated_1d"):
                updated_total += 1
            time.sleep(0.5)
    else:
        print("No T+1 updates needed")

    conn.commit()

    # T+3
    pending_3d = conn.execute(
        """
        SELECT ticker, flagged_date, flagged_price
        FROM performance_tracking
        WHERE updated_3d = 0
          AND flagged_price > 0
          AND julianday(?) - julianday(flagged_date) >= 3
        """,
        (today,),
    ).fetchall()

    if pending_3d:
        print(f"\nUpdating T+3 prices for {len(pending_3d)} stocks...")
        for row in pending_3d:
            if process_update(conn, row, 3, "price_3d", "return_3d", "updated_3d"):
                updated_total += 1
            time.sleep(0.5)
    else:
        print("No T+3 updates needed")

    conn.commit()

    # T+7
    pending_7d = conn.execute(
        """
        SELECT ticker, flagged_date, flagged_price
        FROM performance_tracking
        WHERE updated_7d = 0
          AND flagged_price > 0
          AND julianday(?) - julianday(flagged_date) >= 7
        """,
        (today,),
    ).fetchall()

    if pending_7d:
        print(f"\nUpdating T+7 prices for {len(pending_7d)} stocks...")
        for row in pending_7d:
            if process_update(conn, row, 7, "price_7d", "return_7d", "updated_7d"):
                updated_total += 1
            time.sleep(0.5)
    else:
        print("No T+7 updates needed")

    conn.commit()
    conn.close()

    print(f"\n✓ Price updater complete — {updated_total} records updated")


if __name__ == "__main__":
    update_performance_prices()
