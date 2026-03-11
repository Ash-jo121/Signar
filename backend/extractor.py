from multiprocessing import context
import re
import requests
from tickers import VALID_TICKERS

from comparison import is_comparison_mention

print(f"Extractor loaded, VALID_TICKERS size: {len(VALID_TICKERS)}")
print(f"AND in VALID_TICKERS: {'AND' in VALID_TICKERS}")


LARGE_CAP_EXCLUDE = {
    # Original large caps
    "AAPL",
    "MSFT",
    "GOOGL",
    "GOOG",
    "AMZN",
    "META",
    "TSLA",
    "NVDA",
    "NFLX",
    "SPY",
    "QQQ",
    "IWM",
    "DIA",
    "VTI",
    "JPM",
    "BAC",
    "WFC",
    "GS",
    "V",
    "MA",
    "WMT",
    "HD",
    "COST",
    "NKE",
    "DIS",
    "SBUX",
    "MCD",
    "XOM",
    "CVX",
    # Common words that are technically valid tickers
    # but almost never meant as stocks in Reddit comments
    "IT",
    "BE",
    "FOR",
    "ARE",
    "BY",
    "DO",
    "GO",
    "HE",
    "IF",
    "IN",
    "IS",
    "ME",
    "MY",
    "NO",
    "OF",
    "OK",
    "ON",
    "OR",
    "SO",
    "TO",
    "UP",
    "US",
    "WE",
    "AND",
    "ANY",
    "BUT",
    "CAN",
    "GET",
    "GOT",
    "HAD",
    "HAS",
    "HIM",
    "HIS",
    "HOW",
    "ITS",
    "LET",
    "MAY",
    "NEW",
    "NOT",
    "NOW",
    "OLD",
    "ONE",
    "OUR",
    "OWN",
    "PUT",
    "RAN",
    "RUN",
    "SAY",
    "SEE",
    "SET",
    "SHE",
    "SIX",
    "SUN",
    "TEN",
    "THE",
    "TOO",
    "TWO",
    "USE",
    "WAS",
    "WAY",
    "WHO",
    "WHY",
    "WIN",
    "WON",
    "YES",
    "YET",
    "YOU",
    "EYES",
    "GOOD",
    "HAVE",
    "HERE",
    "JUST",
    "KNOW",
    "LIKE",
    "MAKE",
    "MANY",
    "MORE",
    "MOST",
    "MUCH",
    "NEED",
    "NEXT",
    "NONE",
    "ONLY",
    "OVER",
    "REAL",
    "SAID",
    "SAME",
    "SEEM",
    "SOME",
    "SUCH",
    "SURE",
    "TAKE",
    "THAN",
    "THAT",
    "THEM",
    "THEN",
    "THEY",
    "THIS",
    "TIME",
    "VERY",
    "WANT",
    "WELL",
    "WENT",
    "WERE",
    "WHAT",
    "WHEN",
    "WITH",
    "YOUR",
}


def extract_tickers(text):
    tickers = set()

    dollar_tickers = re.findall(r"\$([A-Z]{1,5})\b", text.upper())

    for t in dollar_tickers:
        if t in VALID_TICKERS and t not in LARGE_CAP_EXCLUDE:
            tickers.add(t)

    standalone = re.findall(r"\b([A-Z]{3,5})\b", text.upper())
    for t in standalone:
        if t in VALID_TICKERS and t not in LARGE_CAP_EXCLUDE:
            tickers.add(t)

    return list(tickers)


def extract_from_post(post):
    found = {}

    text = post["title"] + " " + post["body"]
    tickers = extract_tickers(text)

    for ticker in tickers:
        if ticker not in found:
            found[ticker] = {"mentions": 0, "scores": [], "contexts": []}
        found[ticker]["mentions"] += 1
        found[ticker]["contexts"].append(post["title"][:100])

    for comment in post.get("comments", []):

        comment_tickers = comment.get("tickers", [])
        is_inherited = comment.get("inherited", False)

        if not comment_tickers:
            continue

        for ticker in comment_tickers:
            if ticker not in found:
                found[ticker] = {"mentions": 0, "scores": [], "contexts": []}
            mention_weight = comment.get("mention_weight", 1.0)
            found[ticker]["mentions"] += mention_weight
            found[ticker]["scores"].append(comment["score"])
            found[ticker]["contexts"].append(comment["body"][:100])

    return found


def aggregate_tickers(all_posts):
    master = {}

    for post in all_posts:
        found = extract_from_post(post)
        for ticker, data in found.items():
            if ticker not in master:
                master[ticker] = {"mentions": 0, "scores": [], "contexts": []}
            master[ticker]["mentions"] += data["mentions"]
            master[ticker]["scores"].extend(data["scores"])
            master[ticker]["contexts"].extend(data["contexts"])

    sorted_tickers = sorted(
        master.items(), key=lambda x: x[1]["mentions"], reverse=True
    )
    return sorted_tickers


if __name__ == "__main__":
    from scraper import fetch_all

    print("Fetching all posts...")
    posts = fetch_all()

    print("Extracting tickers...")
    results = aggregate_tickers(posts)

    print("\nTop 20 most mentioned tickers:")
    for ticker, data in results[:20]:
        avg_score = sum(data["scores"]) / len(data["scores"]) if data["scores"] else 0
        print(
            f"  {ticker}: {data['mentions']} mentions | avg comment score: {avg_score:.1f}"
        )
