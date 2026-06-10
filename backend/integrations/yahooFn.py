from datetime import datetime, timezone
import math

import yfinance as yf


def safe_float(value):
    try:
        if value is None:
            return None
        parsed = float(value)
        if not math.isfinite(parsed):
            return None
        return parsed
    except (TypeError, ValueError):
        return None


def safe_int(value):
    try:
        if value is None:
            return 0
        return int(value)
    except (TypeError, ValueError):
        return 0


def round_or_none(value, digits=2):
    return round(value, digits) if value is not None else None


def pct_change(current, previous):
    current = safe_float(current)
    previous = safe_float(previous)
    if current is None or previous is None or previous <= 0:
        return None
    return ((current - previous) / previous) * 100


def clean_history(history):
    if history is None or history.empty:
        return history
    return history.dropna(subset=["Close"])


def market_date_from_index(index_value):
    if hasattr(index_value, "date"):
        return index_value.date().isoformat()
    return str(index_value)[:10]


def average(values):
    values = [safe_float(value) for value in values if safe_float(value) is not None]
    return sum(values) / len(values) if values else None


def build_float_snapshot(info, price=None):
    """
    Prefer Yahoo's reported float and keep estimates explicitly labeled.

    Yahoo coverage is uneven for microcaps. When floatShares is missing, shares
    outstanding less insider-held shares is a useful estimate, but it must not
    be presented as verified float.
    """
    reported_float = safe_float(info.get("floatShares"))
    if reported_float is not None and reported_float <= 0:
        reported_float = None
    shares_outstanding = safe_float(
        info.get("sharesOutstanding") or info.get("impliedSharesOutstanding")
    )
    if shares_outstanding is not None and shares_outstanding <= 0:
        shares_outstanding = None
    if (
        reported_float is not None
        and shares_outstanding is not None
        and reported_float > shares_outstanding * 1.05
    ):
        reported_float = None
    market_cap = safe_float(info.get("marketCap"))
    if shares_outstanding is None and market_cap and price and price > 0:
        shares_outstanding = market_cap / price

    insider_ownership = safe_float(info.get("heldPercentInsiders"))
    estimated_float = None
    if shares_outstanding is not None and insider_ownership is not None:
        insider_ownership = min(max(insider_ownership, 0.0), 1.0)
        estimated_float = shares_outstanding * (1 - insider_ownership)

    effective_float = reported_float or estimated_float or shares_outstanding
    if reported_float is not None:
        source = "yahoo_float_shares"
        quality = "reported"
    elif estimated_float is not None:
        source = "estimated_outstanding_minus_insiders"
        quality = "estimated"
    elif shares_outstanding is not None:
        source = "shares_outstanding_upper_bound"
        quality = "upper_bound"
    else:
        source = "unavailable"
        quality = "missing"

    return {
        "float_shares": reported_float,
        "float_shares_estimate": estimated_float,
        "effective_float_shares": effective_float,
        "float_shares_source": source,
        "float_data_quality": quality,
        "shares_outstanding": shares_outstanding,
        "insider_ownership_pct": (
            insider_ownership * 100 if insider_ownership is not None else None
        ),
        "float_data_timestamp": datetime.now(timezone.utc).isoformat(),
    }


def attach_float_snapshot(result, float_snapshot):
    result["float_shares"] = round_or_none(float_snapshot.get("float_shares"), 0)
    result["float_shares_estimate"] = round_or_none(
        float_snapshot.get("float_shares_estimate"),
        0,
    )
    result["effective_float_shares"] = round_or_none(
        float_snapshot.get("effective_float_shares"),
        0,
    )
    result["float_shares_source"] = float_snapshot.get("float_shares_source")
    result["float_data_quality"] = float_snapshot.get("float_data_quality")
    result["shares_outstanding"] = round_or_none(
        float_snapshot.get("shares_outstanding"),
        0,
    )
    result["insider_ownership_pct"] = round_or_none(
        float_snapshot.get("insider_ownership_pct"),
        2,
    )
    result["float_data_timestamp"] = float_snapshot.get("float_data_timestamp")


def build_market_snapshot(stock, info, ticker):
    history = clean_history(stock.history(period="45d", interval="1d", auto_adjust=False))
    now = datetime.now(timezone.utc).isoformat()

    if history is None or history.empty:
        price = safe_float(info.get("currentPrice") or info.get("regularMarketPrice"))
        volume = safe_int(info.get("regularMarketVolume"))
        average_volume = safe_float(
            info.get("averageDailyVolume10Day")
            or info.get("averageVolume10days")
            or info.get("averageVolume")
        )
        previous_close = safe_float(info.get("previousClose"))
        relative_volume = volume / average_volume if average_volume else None
        return {
            "price": price,
            "previous_close": previous_close,
            "open": safe_float(info.get("regularMarketOpen")),
            "high": safe_float(info.get("dayHigh")),
            "low": safe_float(info.get("dayLow")),
            "close": price,
            "adjusted_close": price,
            "volume_today": volume,
            "avg_volume_10d": average_volume,
            "avg_volume_30d": safe_float(info.get("averageVolume")),
            "dollar_volume": price * volume if price is not None else None,
            "relative_volume_10d": relative_volume,
            "relative_volume_30d": relative_volume,
            "price_change_1d_pct": pct_change(price, previous_close),
            "price_change_3d_pct": None,
            "price_change_7d_pct": None,
            "gap_pct": None,
            "intraday_range_pct": None,
            "distance_from_20dma_pct": None,
            "data_timestamp": now,
            "market_data_as_of": None,
            "market_session": "unknown",
            "source": "yfinance",
        }

    latest = history.iloc[-1]
    latest_index = history.index[-1]
    previous = history.iloc[-2] if len(history) >= 2 else None
    closes = history["Close"].tolist()
    volumes = history["Volume"].tolist() if "Volume" in history.columns else []

    close_price = safe_float(latest.get("Close"))
    price = safe_float(info.get("currentPrice") or info.get("regularMarketPrice"))
    if price is None or price <= 0:
        price = close_price
    previous_close = (
        safe_float(previous.get("Close")) if previous is not None else safe_float(info.get("previousClose"))
    )
    volume_today = safe_int(latest.get("Volume") or info.get("regularMarketVolume"))
    avg_volume_10d = average(volumes[-10:])
    avg_volume_30d = average(volumes[-30:])
    if avg_volume_10d is None:
        avg_volume_10d = safe_float(info.get("averageDailyVolume10Day") or info.get("averageVolume10days"))
    if avg_volume_30d is None:
        avg_volume_30d = safe_float(info.get("averageVolume"))

    open_price = safe_float(latest.get("Open"))
    high_price = safe_float(latest.get("High"))
    low_price = safe_float(latest.get("Low"))
    adjusted_close = safe_float(latest.get("Adj Close")) or close_price
    avg_close_20d = average(closes[-20:])

    return {
        "price": price,
        "previous_close": previous_close,
        "open": open_price,
        "high": high_price,
        "low": low_price,
        "close": close_price,
        "adjusted_close": adjusted_close,
        "volume_today": volume_today,
        "avg_volume_10d": avg_volume_10d,
        "avg_volume_30d": avg_volume_30d,
        "dollar_volume": price * volume_today if price is not None else None,
        "relative_volume_10d": volume_today / avg_volume_10d if avg_volume_10d else None,
        "relative_volume_30d": volume_today / avg_volume_30d if avg_volume_30d else None,
        "price_change_1d_pct": pct_change(price, previous_close),
        "price_change_3d_pct": pct_change(price, closes[-3]) if len(closes) >= 3 else None,
        "price_change_7d_pct": pct_change(price, closes[-7]) if len(closes) >= 7 else None,
        "gap_pct": pct_change(open_price, previous_close),
        "intraday_range_pct": (
            ((high_price - low_price) / previous_close) * 100
            if high_price is not None and low_price is not None and previous_close
            else None
        ),
        "distance_from_20dma_pct": pct_change(price, avg_close_20d),
        "data_timestamp": now,
        "market_data_as_of": market_date_from_index(latest_index),
        "market_session": "open",
        "source": "yfinance",
    }


def attach_market_snapshot(result, snapshot):
    result["market_data"] = {
        "price": round_or_none(snapshot.get("price")),
        "previous_close": round_or_none(snapshot.get("previous_close")),
        "open": round_or_none(snapshot.get("open")),
        "high": round_or_none(snapshot.get("high")),
        "low": round_or_none(snapshot.get("low")),
        "volume_today": safe_int(snapshot.get("volume_today")),
        "avg_volume_10d": round_or_none(snapshot.get("avg_volume_10d"), 0),
        "avg_volume_30d": round_or_none(snapshot.get("avg_volume_30d"), 0),
        "dollar_volume": round_or_none(snapshot.get("dollar_volume")),
        "relative_volume_10d": round_or_none(snapshot.get("relative_volume_10d"), 3),
        "relative_volume_30d": round_or_none(snapshot.get("relative_volume_30d"), 3),
        "price_change_1d_pct": round_or_none(snapshot.get("price_change_1d_pct")),
        "price_change_3d_pct": round_or_none(snapshot.get("price_change_3d_pct")),
        "price_change_7d_pct": round_or_none(snapshot.get("price_change_7d_pct")),
        "gap_pct": round_or_none(snapshot.get("gap_pct")),
        "intraday_range_pct": round_or_none(snapshot.get("intraday_range_pct")),
        "distance_from_20dma_pct": round_or_none(snapshot.get("distance_from_20dma_pct")),
        "data_timestamp": snapshot.get("data_timestamp"),
        "market_session": snapshot.get("market_session", "unknown"),
    }

    result["price"] = result["market_data"]["price"] or 0
    result["previous_close"] = result["market_data"]["previous_close"]
    result["open_price"] = result["market_data"]["open"]
    result["high_price"] = result["market_data"]["high"]
    result["low_price"] = result["market_data"]["low"]
    result["close_price"] = round_or_none(snapshot.get("close"))
    result["adjusted_close"] = round_or_none(snapshot.get("adjusted_close"))
    result["change_percent"] = result["market_data"]["price_change_1d_pct"] or 0
    result["price_change_1d"] = result["market_data"]["price_change_1d_pct"]
    result["price_change_3d"] = result["market_data"]["price_change_3d_pct"]
    result["price_change_7d"] = result["market_data"]["price_change_7d_pct"]
    result["volume"] = result["market_data"]["volume_today"]
    result["average_volume"] = result["market_data"]["avg_volume_10d"]
    result["avg_volume_10d"] = result["market_data"]["avg_volume_10d"]
    result["avg_volume_30d"] = result["market_data"]["avg_volume_30d"]
    result["relative_volume"] = result["market_data"]["relative_volume_10d"]
    result["relative_volume_10d"] = result["market_data"]["relative_volume_10d"]
    result["relative_volume_30d"] = result["market_data"]["relative_volume_30d"]
    result["dollar_volume"] = result["market_data"]["dollar_volume"] or 0
    result["volume_change_vs_avg"] = (
        round((result["relative_volume_10d"] - 1) * 100, 2)
        if result.get("relative_volume_10d") is not None
        else None
    )
    result["gap_pct"] = result["market_data"]["gap_pct"]
    result["intraday_range_pct"] = result["market_data"]["intraday_range_pct"]
    result["distance_from_20dma_pct"] = result["market_data"]["distance_from_20dma_pct"]
    result["market_data_as_of"] = snapshot.get("market_data_as_of")
    result["market_data_source"] = snapshot.get("source", "yfinance")
    result["market_data_timestamp"] = snapshot.get("data_timestamp")


def attach_empty_market_fields(result):
    empty_snapshot = {
        "price": 0,
        "previous_close": None,
        "open": None,
        "high": None,
        "low": None,
        "close": None,
        "adjusted_close": None,
        "volume_today": 0,
        "avg_volume_10d": None,
        "avg_volume_30d": None,
        "dollar_volume": 0,
        "relative_volume_10d": None,
        "relative_volume_30d": None,
        "price_change_1d_pct": None,
        "price_change_3d_pct": None,
        "price_change_7d_pct": None,
        "gap_pct": None,
        "intraday_range_pct": None,
        "distance_from_20dma_pct": None,
        "data_timestamp": datetime.now(timezone.utc).isoformat(),
        "market_data_as_of": None,
        "market_session": "unknown",
        "source": "yfinance",
    }
    attach_market_snapshot(result, empty_snapshot)


def enrich_with_price(results):
    for r in results:
        try:
            stock = yf.Ticker(r["ticker"])
            info = stock.info
            attach_market_snapshot(r, build_market_snapshot(stock, info, r["ticker"]))
            attach_float_snapshot(r, build_float_snapshot(info, r.get("price")))
            r["market_cap"] = info.get("marketCap", 0)
            r["fifty_two_week_high"] = info.get("fiftyTwoWeekHigh", 0)
            r["fifty_two_week_low"] = info.get("fiftyTwoWeekLow", 0)
            r["analyst_target"] = info.get("targetMeanPrice", 0)
            r["analyst_recommendation"] = info.get("recommendationKey", "none")
            r["recommendation"] = None
            r["sector"] = info.get("sector", "Unknown")
            r["description"] = info.get("longBusinessSummary", "")
            r["name"] = info.get("longName", "")
            r["symbol"] = info.get("symbol", "")
            r["short_name"] = info.get("shortName", "")
            r["industry"] = info.get("industry", "Unknown")
            r["website"] = info.get("website", "")
            r["exchange"] = info.get("exchange", "Unknown")
            r["currency"] = info.get("currency", "Unknown")
            r["country"] = info.get("country", "Unknown")
            r["city"] = info.get("city", "Unknown")
            r["state"] = info.get("state", "Unknown")
            r["zip"] = info.get("zip", "Unknown")
            r["phone"] = info.get("phone", "Unknown")
            r["email"] = info.get("email", "Unknown")
            r["ceo"] = info.get("ceo", "Unknown")
            r["num_employees"] = info.get("numEmployees", 0)
            r["founded"] = info.get("founded", 0)
            r["tags"] = info.get("tags", [])
            r["similar"] = info.get("similar", [])
            r["related"] = info.get("related", [])
            r["stats"] = info.get("stats", {})
            r["financials"] = info.get("financials", {})
            r["news"] = info.get("news", [])
            r["events"] = info.get("events", [])
            r["earnings"] = info.get("earnings", {})
            r["dividends"] = info.get("dividends", {})
            r["splits"] = info.get("splits", {})
            r["stock_splits"] = info.get("stockSplits", {})
            r["stock_dividends"] = info.get("stockDividends", {})

            if r["ticker"]:
                r["logo_url"] = (
                    f"https://financialmodelingprep.com/image-stock/{r['ticker']}.png"
                )
            else:
                r["logo_url"] = ""

            if r["website"]:
                domain = (
                    r["website"]
                    .replace("https://", "")
                    .replace("http://", "")
                    .replace("www.", "")
                    .split("/")[0]
                )
                r["logo_fallback"] = (
                    f"https://www.google.com/s2/favicons?domain={domain}&sz=64"
                )
            else:
                r["logo_fallback"] = ""

        except Exception as e:
            print(f"Could not fetch price for {r['ticker']}: {e}")
            attach_empty_market_fields(r)
            attach_float_snapshot(r, build_float_snapshot({}, None))
            r["market_cap"] = 0
            r["fifty_two_week_high"] = 0
            r["fifty_two_week_low"] = 0
            r["analyst_target"] = 0
            r["analyst_recommendation"] = "none"
            r["recommendation"] = None
            r["sector"] = "Unknown"
            r["description"] = ""
            r["name"] = ""
            r["symbol"] = ""
            r["short_name"] = ""
            r["industry"] = "Unknown"
            r["website"] = ""
            r["logo_url"] = ""
            r["logo_fallback"] = ""
            r["exchange"] = "Unknown"
            r["currency"] = "Unknown"
            r["country"] = "Unknown"
            r["city"] = "Unknown"
            r["state"] = "Unknown"
            r["zip"] = "Unknown"
            r["phone"] = "Unknown"
            r["email"] = "Unknown"
            r["ceo"] = "Unknown"
            r["num_employees"] = 0
            r["founded"] = 0
            r["tags"] = []
            r["similar"] = []
            r["related"] = []
            r["stats"] = {}
            r["financials"] = {}
            r["news"] = []
            r["events"] = []
            r["earnings"] = {}
            r["dividends"] = {}
            r["splits"] = {}
            r["stock_splits"] = {}
            r["stock_dividends"] = {}
    return results
