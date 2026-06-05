from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")
REGULAR_OPEN = time(9, 30)
REGULAR_CLOSE = time(16, 0)


def observed_date(month, day, year):
    holiday = date(year, month, day)
    if holiday.weekday() == 5:
        return holiday - timedelta(days=1)
    if holiday.weekday() == 6:
        return holiday + timedelta(days=1)
    return holiday


def nth_weekday(year, month, weekday, n):
    current = date(year, month, 1)
    offset = (weekday - current.weekday()) % 7
    return current + timedelta(days=offset + (n - 1) * 7)


def last_weekday(year, month, weekday):
    current = date(year, month + 1, 1) - timedelta(days=1)
    offset = (current.weekday() - weekday) % 7
    return current - timedelta(days=offset)


def easter_date(year):
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def market_holidays(year):
    holidays = {
        observed_date(1, 1, year),
        nth_weekday(year, 1, 0, 3),
        nth_weekday(year, 2, 0, 3),
        easter_date(year) - timedelta(days=2),
        last_weekday(year, 5, 0),
        observed_date(6, 19, year),
        observed_date(7, 4, year),
        nth_weekday(year, 9, 0, 1),
        nth_weekday(year, 11, 3, 4),
        observed_date(12, 25, year),
    }

    # New Year's Day can be observed in the previous calendar year.
    holidays.add(observed_date(1, 1, year + 1))
    return holidays


def get_market_session(run_date=None):
    if run_date is None:
        run_date = date.today()

    if isinstance(run_date, str):
        run_date = date.fromisoformat(run_date)

    if run_date.weekday() >= 5:
        reason = "weekend"
    elif run_date in market_holidays(run_date.year):
        reason = "market_holiday"
    else:
        reason = None

    if reason:
        return {
            "run_date": run_date.isoformat(),
            "market_session": "closed",
            "market_session_phase": "closed",
            "market_closed_reason": reason,
            "price_update_status": "skipped_market_closed",
            "eligible_for_backtest": False,
            "next_trading_session_signal": True,
        }

    phase = get_market_session_phase(run_date)
    return {
        "run_date": run_date.isoformat(),
        "market_session": "open",
        "market_session_phase": phase,
        "market_closed_reason": None,
        "price_update_status": "eligible",
        "eligible_for_backtest": True,
        "next_trading_session_signal": False,
    }


def get_market_session_phase(run_date=None, now=None):
    if run_date is None:
        run_date = date.today()
    if isinstance(run_date, str):
        run_date = date.fromisoformat(run_date)

    now_et = now or datetime.now(EASTERN)
    if now_et.tzinfo is None:
        now_et = now_et.replace(tzinfo=EASTERN)
    else:
        now_et = now_et.astimezone(EASTERN)

    if now_et.date() < run_date:
        return "pre_market"
    if now_et.date() > run_date:
        return "after_hours"
    if now_et.time() < REGULAR_OPEN:
        return "pre_market"
    if now_et.time() < REGULAR_CLOSE:
        return "regular"
    return "after_hours"


def is_market_open(run_date=None):
    return get_market_session(run_date)["market_session"] == "open"
