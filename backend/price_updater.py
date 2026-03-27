import sqlite3
import time
from datetime import datetime
from database import get_connection
import yfinance as yf


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


def calculate_return(flagged_price, current_price):
    if not flagged_price or flagged_price == 0:
        return None
    return round(((current_price - flagged_price) / flagged_price) * 100, 2)


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
            ticker, flagged_date, flagged_price = (
                row["ticker"],
                row["flagged_date"],
                row["flagged_price"],
            )
            price = fetch_current_price(ticker)
            if price:
                ret = calculate_return(flagged_price, price)
                conn.execute(
                    """
                    UPDATE performance_tracking
                    SET price_1d = ?, return_1d = ?, updated_1d = 1
                    WHERE ticker = ? AND flagged_date = ?
                    """,
                    (price, ret, ticker, flagged_date),
                )
                print(
                    f"  {ticker} | flagged @ ${flagged_price} → T+1 @ ${price} | return: {ret:+.2f}%"
                )
                updated_total += 1
            time.sleep(0.5)  # be gentle with yfinance
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
            ticker, flagged_date, flagged_price = (
                row["ticker"],
                row["flagged_date"],
                row["flagged_price"],
            )
            price = fetch_current_price(ticker)
            if price:
                ret = calculate_return(flagged_price, price)
                conn.execute(
                    """
                    UPDATE performance_tracking
                    SET price_3d = ?, return_3d = ?, updated_3d = 1
                    WHERE ticker = ? AND flagged_date = ?
                    """,
                    (price, ret, ticker, flagged_date),
                )
                print(
                    f"  {ticker} | flagged @ ${flagged_price} → T+3 @ ${price} | return: {ret:+.2f}%"
                )
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
            ticker, flagged_date, flagged_price = (
                row["ticker"],
                row["flagged_date"],
                row["flagged_price"],
            )
            price = fetch_current_price(ticker)
            if price:
                ret = calculate_return(flagged_price, price)
                conn.execute(
                    """
                    UPDATE performance_tracking
                    SET price_7d = ?, return_7d = ?, updated_7d = 1
                    WHERE ticker = ? AND flagged_date = ?
                    """,
                    (price, ret, ticker, flagged_date),
                )
                print(
                    f"  {ticker} | flagged @ ${flagged_price} → T+7 @ ${price} | return: {ret:+.2f}%"
                )
                updated_total += 1
            time.sleep(0.5)
    else:
        print("No T+7 updates needed")

    conn.commit()
    conn.close()

    print(f"\n✓ Price updater complete — {updated_total} records updated")


if __name__ == "__main__":
    update_performance_prices()


# ```

# **One important thing** — `price_updater.py` should run **after** `main.py` completes each day, not before. The order matters:
# ```
# main.py          → flags stocks, records entry prices
# price_updater.py → fills in T+1/T+3/T+7 for previously flagged stocks
# ```

# On Railway you'll set two cron jobs:
# ```
# main.py          → runs at 8:00 AM IST daily
# price_updater.py → runs at 8:30 AM IST daily (after main finishes)
