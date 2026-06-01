import time
from datetime import datetime

import pandas as pd
import yfinance as yf

from database import PERFORMANCE_TRACKING_COLUMNS, ensure_column, get_connection
from market_calendar import get_market_session

BENCHMARK_SYMBOL = "IWM"
today_dt = datetime.now()

if __name__ == "__main__":
    market_session = get_market_session(today_dt.date())
    if market_session["market_session"] == "closed":
        print(
            f"Market closed for {market_session['run_date']} "
            f"({market_session['market_closed_reason']}). "
            "Skipping price updater and marking run as non-trading-day."
        )
        exit(0)


# Tickers to skip in performance tracking
# These are exclusions that were added after some records were already created.
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


RETURN_WINDOWS = [
    (
        1,
        "price_1d",
        "return_1d",
        "updated_1d",
        "benchmark_price_t1",
        "benchmark_return_t1",
        "excess_return_t1",
    ),
    (
        3,
        "price_3d",
        "return_3d",
        "updated_3d",
        "benchmark_price_t3",
        "benchmark_return_t3",
        "excess_return_t3",
    ),
    (
        7,
        "price_7d",
        "return_7d",
        "updated_7d",
        "benchmark_price_t7",
        "benchmark_return_t7",
        "excess_return_t7",
    ),
    (
        14,
        "price_t14",
        "return_t14",
        "updated_t14",
        "benchmark_price_t14",
        "benchmark_return_t14",
        "excess_return_t14",
    ),
    (
        30,
        "price_t30",
        "return_t30",
        "updated_t30",
        "benchmark_price_t30",
        "benchmark_return_t30",
        "excess_return_t30",
    ),
]
BENCHMARK_RETURN_CACHE = {}


def fetch_current_price(ticker):
    """Fetch current price using yfinance."""
    try:
        stock = yf.Ticker(ticker)
        price = stock.info.get("currentPrice") or stock.info.get("regularMarketPrice")
        if price:
            return round(float(price), 4)
    except Exception as exc:
        print(f"  Price fetch failed for {ticker}: {exc}")
    return None


def fetch_historical_close(ticker, target_date):
    """Return the first available close on or after target_date."""
    try:
        start = pd.Timestamp(target_date)
        end = start + pd.Timedelta(days=7)
        history = yf.Ticker(ticker).history(
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            interval="1d",
            auto_adjust=False,
        )
        if history is None or history.empty:
            return None
        return round(float(history.iloc[0]["Close"]), 4)
    except Exception as exc:
        print(f"  Historical close fetch failed for {ticker} @ {target_date}: {exc}")
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

        # yfinance stores splits as ratio; product covers multiple split events.
        combined_ratio = recent_splits.prod()
        return True, round(float(combined_ratio), 4)

    except Exception as exc:
        print(f"  Split check failed for {ticker}: {exc}")
        return False, 1.0


def is_anomalous_return(flagged_price, current_price, days):
    """
    Detect returns that are physically implausible without a corporate action.
    Longer horizons use wider bounds because penny stocks can genuinely squeeze.
    """
    if flagged_price <= 0 or current_price <= 0:
        return False

    ratio = current_price / flagged_price

    if days == 1 and ratio > 5.0:
        return True
    if days == 3 and ratio > 10.0:
        return True
    if days == 7 and ratio > 15.0:
        return True
    if days in {14, 30} and ratio > 25.0:
        return True

    return False


def calculate_return(flagged_price, current_price):
    if not flagged_price or flagged_price == 0:
        return None
    return round(((current_price - flagged_price) / flagged_price) * 100, 2)


def benchmark_return_since(flagged_date):
    """Compare stock returns to IWM so backtests know if picks beat small caps."""
    if flagged_date in BENCHMARK_RETURN_CACHE:
        return BENCHMARK_RETURN_CACHE[flagged_date]

    benchmark_start = fetch_historical_close(BENCHMARK_SYMBOL, flagged_date)
    benchmark_price = fetch_current_price(BENCHMARK_SYMBOL)
    if not benchmark_start or not benchmark_price:
        BENCHMARK_RETURN_CACHE[flagged_date] = (None, None)
        return BENCHMARK_RETURN_CACHE[flagged_date]

    BENCHMARK_RETURN_CACHE[flagged_date] = (
        benchmark_price,
        calculate_return(benchmark_start, benchmark_price),
    )
    return BENCHMARK_RETURN_CACHE[flagged_date]


def mark_resolution(conn, ticker, flagged_date, updated_col, status):
    conn.execute(
        f"""
        UPDATE performance_tracking
        SET {updated_col} = 1,
            resolution_status = ?
        WHERE ticker = ? AND flagged_date = ?
        """,
        (status, ticker, flagged_date),
    )


def process_update(
    conn,
    row,
    period_days,
    price_col,
    return_col,
    updated_col,
    benchmark_price_col,
    benchmark_return_col,
    excess_return_col,
):
    """
    Process one performance update.
    This records raw return, IWM-relative return, and a resolution status so
    unresolvable/delisted/split-anomalous names do not silently pollute averages.
    """
    ticker = row["ticker"]
    flagged_date = row["flagged_date"]
    flagged_price = row["flagged_price"]

    if ticker in EXCLUDED_TICKERS:
        print(f"  {ticker} | SKIPPING - excluded ticker")
        mark_resolution(conn, ticker, flagged_date, updated_col, "excluded")
        return False

    price = fetch_current_price(ticker)
    if not price:
        print(f"  {ticker} | unresolved price - marking unresolvable")
        mark_resolution(conn, ticker, flagged_date, updated_col, "unresolvable")
        return False

    had_split, split_ratio = had_split_since(ticker, flagged_date)
    if had_split and not row["split_adjusted"]:
        adjusted_flagged = round(flagged_price / split_ratio, 4)
        print(
            f"  {ticker} | SPLIT DETECTED (ratio={split_ratio}) - "
            f"adjusting flagged price ${flagged_price} -> ${adjusted_flagged}"
        )
        conn.execute(
            """
            UPDATE performance_tracking
            SET flagged_price = ?, split_adjusted = 1
            WHERE ticker = ? AND flagged_date = ?
            """,
            (adjusted_flagged, ticker, flagged_date),
        )
        flagged_price = adjusted_flagged
    elif had_split and row["split_adjusted"]:
        print(f"  {ticker} | split already adjusted - skipping re-adjustment")

    if is_anomalous_return(flagged_price, price, period_days):
        print(
            f"  {ticker} | ANOMALOUS RETURN after adjustment "
            f"(flagged=${flagged_price}, current=${price}) - marking for review"
        )
        conn.execute(
            f"""
            UPDATE performance_tracking
            SET {price_col} = ?,
                {return_col} = ?,
                {updated_col} = 1,
                resolution_status = 'anomalous'
            WHERE ticker = ? AND flagged_date = ?
            """,
            (price, -999.0, ticker, flagged_date),
        )
        return False

    ret = calculate_return(flagged_price, price)
    benchmark_price, benchmark_ret = benchmark_return_since(flagged_date)
    excess_ret = None if benchmark_ret is None or ret is None else round(ret - benchmark_ret, 2)

    conn.execute(
        f"""
        UPDATE performance_tracking
        SET {price_col} = ?,
            {return_col} = ?,
            {updated_col} = 1,
            {benchmark_price_col} = ?,
            {benchmark_return_col} = ?,
            {excess_return_col} = ?,
            benchmark_symbol = ?,
            resolution_status = 'resolved'
        WHERE ticker = ? AND flagged_date = ?
        """,
        (
            price,
            ret,
            benchmark_price,
            benchmark_ret,
            excess_ret,
            BENCHMARK_SYMBOL,
            ticker,
            flagged_date,
        ),
    )

    split_note = " [split-adjusted]" if had_split else ""
    benchmark_note = (
        f" | {BENCHMARK_SYMBOL}: {benchmark_ret:+.2f}% | excess: {excess_ret:+.2f}%"
        if benchmark_ret is not None and excess_ret is not None
        else ""
    )
    print(
        f"  {ticker} | flagged @ ${flagged_price}{split_note} "
        f"-> T+{period_days} @ ${price} | return: {ret:+.2f}%{benchmark_note}"
    )
    return True


def ensure_price_updater_columns(conn):
    existing_cols = [
        col[1]
        for col in conn.execute("PRAGMA table_info(performance_tracking)").fetchall()
    ]
    if "split_adjusted" not in existing_cols:
        conn.execute(
            "ALTER TABLE performance_tracking ADD COLUMN split_adjusted INTEGER DEFAULT 0"
        )
        print("Migration: added split_adjusted column")

    for column, definition in PERFORMANCE_TRACKING_COLUMNS:
        ensure_column(conn, "performance_tracking", column, definition)

    conn.commit()


def update_performance_prices():
    conn = get_connection()
    ensure_price_updater_columns(conn)

    today = datetime.now().strftime("%Y-%m-%d")
    updated_total = 0

    print(f"=== Price Updater - {today} ===\n")

    for (
        period_days,
        price_col,
        return_col,
        updated_col,
        benchmark_price_col,
        benchmark_return_col,
        excess_return_col,
    ) in RETURN_WINDOWS:
        pending = conn.execute(
            f"""
            SELECT ticker, flagged_date, flagged_price, split_adjusted
            FROM performance_tracking
            WHERE {updated_col} = 0
              AND flagged_price > 0
              AND julianday(?) - julianday(flagged_date) >= ?
            """,
            (today, period_days),
        ).fetchall()

        if pending:
            print(f"\nUpdating T+{period_days} prices for {len(pending)} stocks...")
            for row in pending:
                if process_update(
                    conn,
                    row,
                    period_days,
                    price_col,
                    return_col,
                    updated_col,
                    benchmark_price_col,
                    benchmark_return_col,
                    excess_return_col,
                ):
                    updated_total += 1
                time.sleep(0.5)
        else:
            print(f"No T+{period_days} updates needed")

        conn.commit()

    conn.close()
    print(f"\nPrice updater complete - {updated_total} records updated")


if __name__ == "__main__":
    update_performance_prices()
