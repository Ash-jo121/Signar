import json
import re
import requests
import time

from exclusion import LARGE_CAP_EXCLUDE
from tickers import VALID_TICKERS

HEADERS = {"User-Agent": "ThreadRadar/1.0"}

SUBREDDITS = ["pennystocks", "smallstreetbets", "Pennystock"]


print(f"✓ Scraper loaded VALID_TICKERS: {len(VALID_TICKERS)} tickers")


def extract_tickers_simple(text):
    """Simple ticker extraction using validated ticker list"""
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


def fetch_posts(subreddit, category="hot", limit=100):
    url = f"https://www.reddit.com/r/{subreddit}/{category}.json?limit={limit}"

    for attempt in range(3):
        response = requests.get(url, headers=HEADERS)

        if response.status_code == 200:
            posts = response.json()["data"]["children"]
            print(f"Fetched a total of {len(posts)} posts from the subreddit")
            return [
                {
                    "id": p["data"]["id"],
                    "title": p["data"]["title"],
                    "body": p["data"].get("selftext", ""),
                    "score": p["data"]["score"],
                    "subreddit": subreddit,
                    "url": f"https://reddit.com{p['data']['permalink']}",
                }
                for p in posts
            ]

        elif response.status_code == 429:
            wait = (attempt + 1) * 30  # 30s, 60s, 90s
            print(f"  Rate limited. Waiting {wait}s before retry...")
            time.sleep(wait)

        else:
            print(
                f"Failed to fetch posts from the subreddit: {subreddit} :: {response.status_code}"
            )
            return []

    return []


def parse_comments_recursive(comments_list, parent_tickers=None, depth=0):
    comments = []
    for c in comments_list:
        if c["kind"] == "t1":
            data = c["data"]
            body = data["body"]

            current_tickers = extract_tickers_simple(body)
            if current_tickers:
                effective_tickers = current_tickers
                inherited = False
                mention_weight = 1.0
            else:
                effective_tickers = parent_tickers or []
                inherited = True
                mention_weight = max(0.3, 1.0 - (depth * 0.2))

            comments.append(
                {
                    "body": body,
                    "score": data["score"],
                    "tickers": effective_tickers,
                    "inherited": inherited,
                    "mention_weight": mention_weight,
                }
            )

            replies = data.get("replies", "")
            if replies and isinstance(replies, dict):
                nested = replies["data"]["children"]
                comments.extend(
                    parse_comments_recursive(nested, effective_tickers, depth + 1)
                )

    return comments


def fetch_comments(post_id, subreddit):
    url = f"https://www.reddit.com/r/{subreddit}/comments/{post_id}.json"
    response = requests.get(url, headers=HEADERS)

    if response.status_code != 200:
        return []

    try:
        comment_list = response.json()[1]["data"]["children"]
        return parse_comments_recursive(comment_list, parent_tickers=None)
    except:
        return []


def fetch_all():
    all_data = []
    seen_ids = set()

    for subreddit in SUBREDDITS:
        for category in ["hot", "top", "new"]:
            print(f"Fetching r/{subreddit}/{category}...")
            posts = fetch_posts(subreddit, category=category, limit=100)

            for post in posts:
                if post["score"] < -5:
                    continue

                if post["id"] in seen_ids:
                    continue

                seen_ids.add(post["id"])

                comments = fetch_comments(post["id"], subreddit)
                post["comments"] = comments
                print(f"  Post: '{post['title'][:40]}' → {len(comments)} comments")
                all_data.append(post)
                time.sleep(2)

            time.sleep(10)
        time.sleep(15)

    print(f"Fetched {len(all_data)} posts total")
    return all_data


if __name__ == "__main__":
    data = fetch_all()
    print(data[0])
