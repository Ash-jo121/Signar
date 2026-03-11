import requests
import json
import os
import time

TICKERS_CACHE_FILE = "valid_tickers.json"


def fetch_all_tickers():
    all_tickers = set()
    headers = {"User-Agent": "Mozilla/5.0"}

    exchanges = ["nasdaq", "nyse", "amex"]

    for exchange in exchanges:
        try:
            print(f"Fetching {exchange.upper()} tickers...")
            url = f"https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=10000&exchange={exchange}&download=true"
            response = requests.get(url, headers=headers, timeout=30)

            if response.status_code == 200:
                data = response.json()
                rows = data.get("data", {}).get("rows", [])
                before = len(all_tickers)

                for row in rows:
                    symbol = row.get("symbol", "").strip()
                    # Only pure alphabetic tickers, 1-5 chars
                    if symbol and symbol.isalpha() and 1 <= len(symbol) <= 5:
                        all_tickers.add(symbol.upper())

                added = len(all_tickers) - before
                print(
                    f"  {exchange.upper()}: added {added} tickers (total: {len(all_tickers)})"
                )
            else:
                print(
                    f"  {exchange.upper()}: failed with status {response.status_code}"
                )

            time.sleep(1)  # be polite between requests

        except Exception as e:
            print(f"  {exchange.upper()}: error — {e}")

    if all_tickers:
        with open(TICKERS_CACHE_FILE, "w") as f:
            json.dump(list(all_tickers), f)
        print(f"\nCached {len(all_tickers)} valid tickers to {TICKERS_CACHE_FILE}")

    return all_tickers


def load_valid_tickers():
    if os.path.exists(TICKERS_CACHE_FILE):
        file_age_days = (time.time() - os.path.getmtime(TICKERS_CACHE_FILE)) / 86400

        if file_age_days < 7:
            with open(TICKERS_CACHE_FILE, "r") as f:
                tickers = set(json.load(f))
                print(f"Loaded {len(tickers)} tickers from cache")
                return tickers
        else:
            print("Cache is older than 7 days, refreshing...")

    return fetch_all_tickers()


VALID_TICKERS = load_valid_tickers()
