import yfinance as yf


def enrich_with_price(results):
    for r in results:
        try:
            stock = yf.Ticker(r["ticker"])
            info = stock.info
            r["price"] = round(
                info.get("currentPrice") or info.get("regularMarketPrice") or 0, 2
            )
            r["change_percent"] = round(info.get("regularMarketChangePercent", 0), 2)
            r["market_cap"] = info.get("marketCap", 0)
            r["fifty_two_week_high"] = info.get("fiftyTwoWeekHigh", 0)
            r["fifty_two_week_low"] = info.get("fiftyTwoWeekLow", 0)
            r["volume"] = info.get("regularMarketVolume", 0)
            r["analyst_target"] = info.get("targetMeanPrice", 0)
            r["recommendation"] = info.get("recommendationKey", "none")
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
            r["stock_splits"] = info.get("stockSplits", {})

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
            r["price"] = 0
            r["change_percent"] = 0
            r["market_cap"] = 0
            r["fifty_two_week_high"] = 0
            r["fifty_two_week_low"] = 0
            r["volume"] = 0
            r["analyst_target"] = 0
            r["recommendation"] = "none"
            r["sector"] = "Unknown"
            r["description"] = ""
            r["name"] = ""
            r["symbol"] = ""
            r["short_name"] = ""
            r["industry"] = "Unknown"
            r["website"] = ""
            r["logo_url"] = ""
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
            r["stock_splits"] = {}
    return results
