from multiprocessing import context
import re
import requests

from comparison import is_comparison_mention


def load_valid_tickers():
    BLACKLIST = {
        "A",
        "I",
        "IT",
        "BE",
        "ARE",
        "GO",
        "SO",
        "AT",
        "IN",
        "ON",
        "DO",
        "BY",
        "IF",
        "OR",
        "IS",
        "TO",
        "UP",
        "US",
        "AN",
        "AS",
        "HE",
        "WE",
        "ME",
        "MY",
        "NO",
        "OK",
        "AI",
        "DD",
        "IMO",
        "NFA",
        "CEO",
        "IPO",
        "ETF",
        "NYSE",
        "SEC",
        "FDA",
        "EPS",
        "ATH",
        "RIP",
        "EOD",
        "AH",
        "PM",
        "AM",
        "PT",
        "TP",
        "SL",
        "RS",
        "OTC",
        "GDP",
        "COST",
    }
    return BLACKLIST


def extract_tickers(text):
    blacklist = load_valid_tickers()
    tickers = set()

    dollar_tickers = re.findall(r"\$([A-Z]{1,5})\b", text.upper())

    for t in dollar_tickers:
        if t not in blacklist:
            tickers.add(t)

    standalone = re.findall(rf"\b([A-Z]{2,5})\b", text.upper())
    for t in standalone:
        if t not in blacklist:
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
