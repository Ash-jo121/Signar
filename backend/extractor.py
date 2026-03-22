from multiprocessing import context
import re
import requests
from exclusion import COMMON_ABBREVIATIONS, LARGE_CAP_EXCLUDE
from tickers import VALID_TICKERS

from comparison import is_comparison_mention

print(f"Extractor loaded, VALID_TICKERS size: {len(VALID_TICKERS)}")
print(f"AND in VALID_TICKERS: {'AND' in VALID_TICKERS}")


def extract_tickers(text):
    tickers = set()

    dollar_tickers = re.findall(r"\$([A-Za-z]{1,5})\b", text)

    for t in dollar_tickers:
        t_upper = t.upper()
        if (
            t_upper in VALID_TICKERS
            and t_upper not in LARGE_CAP_EXCLUDE
            and t_upper not in COMMON_ABBREVIATIONS
        ):
            tickers.add(t_upper)

    standalone = re.findall(r"\b([A-Z]{3,5})\b", text)
    for t in standalone:
        if (
            t in VALID_TICKERS
            and t not in LARGE_CAP_EXCLUDE
            and t not in COMMON_ABBREVIATIONS
        ):
            tickers.add(t)

    return list(tickers)


def extract_from_post(post):
    found = {}

    text = post["title"] + " " + post["body"]
    tickers = extract_tickers(text)

    for ticker in tickers:
        if ticker not in found:
            found[ticker] = {
                "mentions": 0,
                "scores": [],
                "contexts": [],
                "top_comment": None,
            }
        found[ticker]["mentions"] += 1
        found[ticker]["contexts"].append(
            {
                "text": text[:300],
                "source": "post",
                "score": post["score"],
            }
        )

    for comment in post.get("comments", []):

        comment_tickers = comment.get("tickers", [])
        is_inherited = comment.get("inherited", False)

        if not comment_tickers:
            continue

        for ticker in comment_tickers:
            if ticker not in found:
                found[ticker] = {
                    "mentions": 0,
                    "scores": [],
                    "contexts": [],
                    "top_comment": None,
                }
            mention_weight = comment.get("mention_weight", 1.0)
            found[ticker]["mentions"] += mention_weight
            found[ticker]["scores"].append(comment["score"])
            found[ticker]["contexts"].append(
                {
                    "text": comment["body"][:300],
                    "source": "comment",
                    "score": comment[
                        "score"
                    ],  # keep negatives for downvoted-bullish detection
                }
            )
            # Track highest-upvoted comment per ticker for contrarian signal detection
            tc = found[ticker]["top_comment"]
            if tc is None or comment["score"] > tc["score"]:
                found[ticker]["top_comment"] = {
                    "text": comment["body"][:300],
                    "score": comment["score"],
                }

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
