# save as test_tickers.py in backend folder
import requests
import json

headers = {"User-Agent": "Mozilla/5.0"}
all_tickers = set()

for exchange in ["nasdaq", "nyse", "amex"]:
    url = f"https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=10000&exchange={exchange}&download=true"
    response = requests.get(url, headers=headers, timeout=30)

    if response.status_code == 200:
        rows = response.json().get("data", {}).get("rows", [])
        for row in rows:
            symbol = row.get("symbol", "").strip()
            if symbol and symbol.isalpha() and 1 <= len(symbol) <= 5:
                all_tickers.add(symbol.upper())
        print(f"{exchange.upper()}: {len(all_tickers)} total tickers so far")
    else:
        print(f"{exchange.upper()}: failed {response.status_code}")

print(f"\nTotal: {len(all_tickers)}")
print(f"AND in tickers: {'AND' in all_tickers}")
print(f"COULD in tickers: {'COULD' in all_tickers}")
print(f"GANX in tickers: {'GANX' in all_tickers}")

# Save to file
with open("valid_tickers.json", "w") as f:
    json.dump(list(all_tickers), f)
print("Saved to valid_tickers.json")
