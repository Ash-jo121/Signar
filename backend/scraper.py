import datetime
import re
import requests
import time
from datetime import timezone, datetime
from exclusion import COMMON_ABBREVIATIONS, LARGE_CAP_EXCLUDE
from tickers import VALID_TICKERS
from database import (
    archive_old_posts,
    get_active_posts,
    save_post,
    update_post_after_refresh,
)

HEADERS = {"User-Agent": "ThreadRadar/1.0"}

SUBREDDITS = [
    "pennystocks",
    "smallstreetbets",
    "Pennystock",
    "RobinHoodPennyStocks",
    "10xPennyStocks",
    "Shortsqueeze",
    "SqueezePlays",
]

LOOKBACK_SECONDS = 24 * 60 * 60  # 24 hours

print(f"✓ Scraper loaded VALID_TICKERS: {len(VALID_TICKERS)} tickers")


def extract_tickers_simple(text):
    """Simple ticker extraction using validated ticker list"""
    tickers = set()

    dollar_tickers = re.findall(r"\$([A-Za-z]{1,5})\b", text)
    for t in dollar_tickers:
        t = t.upper()
        if (
            t in VALID_TICKERS
            and t not in LARGE_CAP_EXCLUDE
            and t not in COMMON_ABBREVIATIONS
        ):
            tickers.add(t)

    standalone = re.findall(r"\b([A-Z]{3,5})\b", text)
    for t in standalone:
        if (
            t in VALID_TICKERS
            and t not in LARGE_CAP_EXCLUDE
            and t not in COMMON_ABBREVIATIONS
        ):
            tickers.add(t)

    return list(tickers)


def parse_post(p):
    """Normalize raw Reddit post data into our format"""
    return {
        "id": p["data"]["id"],
        "title": p["data"]["title"],
        "body": p["data"].get("selftext", ""),
        "score": p["data"]["score"],
        "subreddit": p["data"]["subreddit"],
        "url": f"https://reddit.com{p['data']['permalink']}",
        "created_utc": p["data"]["created_utc"],
        "num_comments": p["data"]["num_comments"],
    }


# def fetch_posts(subreddit, category="hot", limit=100):
#     url = f"https://www.reddit.com/r/{subreddit}/{category}.json?limit={limit}"

#     for attempt in range(3):
#         response = requests.get(url, headers=HEADERS)

#         if response.status_code == 200:
#             posts = response.json()["data"]["children"]
#             print(f"Fetched a total of {len(posts)} posts from the subreddit")
#             for p in posts:
#                 save_post(p["data"])

#             return [
#                 {
#                     "id": p["data"]["id"],
#                     "title": p["data"]["title"],
#                     "body": p["data"].get("selftext", ""),
#                     "score": p["data"]["score"],
#                     "subreddit": subreddit,
#                     "url": f"https://reddit.com{p['data']['permalink']}",
#                 }
#                 for p in posts
#             ]

#         elif response.status_code == 429:
#             wait = (attempt + 1) * 30  # 30s, 60s, 90s
#             print(f"  Rate limited. Waiting {wait}s before retry...")
#             time.sleep(wait)

#         else:
#             print(
#                 f"Failed to fetch posts from the subreddit: {subreddit} :: {response.status_code}"
#             )
#             return []

#     return []


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


def fetch_new_24h(subreddit):
    """
    Paginate through /new until we hit posts older than 24h.
    Since /new is newest-first, we stop as soon as cutoff is crossed.
    """
    cutoff = datetime.now(timezone.utc).timestamp() - LOOKBACK_SECONDS
    posts = []
    after = None
    page = 0

    while True:
        url = f"https://www.reddit.com/r/{subreddit}/new.json?limit=100"
        if after:
            url += f"&after={after}"

        for attempt in range(3):
            response = requests.get(url, headers=HEADERS)

            if response.status_code == 200:
                data = response.json()["data"]
                children = data["children"]
                after = data.get("after")

                if not children:
                    return posts

                reached_cutoff = False
                for p in children:
                    if p["data"]["created_utc"] < cutoff:
                        reached_cutoff = True
                        break
                    posts.append(parse_post(p))

                if reached_cutoff or not after:
                    print(
                        f"    /new: {len(posts)} posts in last 24h ({page + 1} pages)"
                    )
                    return posts

                page += 1
                time.sleep(2)
                break

            elif response.status_code == 429:
                wait = (attempt + 1) * 30
                print(f"    Rate limited. Waiting {wait}s...")
                time.sleep(wait)

            else:
                print(
                    f"    Failed r/{subreddit}/new page {page}: {response.status_code}"
                )
                return posts

    return posts


def fetch_hot(subreddit, limit=25):
    """
    Fetch top hot posts. These catch active discussions on posts
    older than 24h that are still getting engagement.
    """
    url = f"https://www.reddit.com/r/{subreddit}/hot.json?limit={limit}"

    for attempt in range(3):
        response = requests.get(url, headers=HEADERS)

        if response.status_code == 200:
            children = response.json()["data"]["children"]
            posts = [parse_post(p) for p in children]
            print(f"    /hot: {len(posts)} posts fetched")
            return posts

        elif response.status_code == 429:
            wait = (attempt + 1) * 30
            print(f"    Rate limited. Waiting {wait}s...")
            time.sleep(wait)

        else:
            print(f"    Failed r/{subreddit}/hot: {response.status_code}")
            return []

    return []


def should_reanalyze(db_post, fresh_comment_count):
    """
    Only re-fetch comments if engagement has grown meaningfully.
    Saves Groq API calls on posts that haven't changed.
    """
    old_count = db_post.get("comment_count_at_analysis", 0)

    # More than 20% new comments since last analysis
    if old_count == 0 or fresh_comment_count > old_count * 1.2:
        return True

    # Absolute threshold — at least 10 new comments
    if fresh_comment_count - old_count >= 10:
        return True

    return False


def refresh_active_posts(seen_ids):
    """
    Re-fetch comments for all active posts in DB (created within 3 days).
    This is the recycling mechanism — catches comment evolution on older posts.
    Returns list of refreshed posts ready for sentiment analysis.
    """
    active = get_active_posts()

    if not active:
        print("  No active posts to refresh")
        return []

    print(f"  Refreshing {len(active)} active posts from DB...")
    refreshed = []

    for db_post in active:
        post_id = db_post["id"]

        # Skip if already fetched fresh this run (was in new/hot)
        if post_id in seen_ids:
            continue

        # Fetch fresh comment count from Reddit listing (lightweight)
        url = f"https://www.reddit.com/r/{db_post['subreddit']}/comments/{post_id}.json?limit=1"
        try:
            response = requests.get(url, headers=HEADERS)
            if response.status_code != 200:
                continue

            post_data = response.json()[0]["data"]["children"][0]["data"]
            fresh_comment_count = post_data.get("num_comments", 0)

            if not should_reanalyze(db_post, fresh_comment_count):
                print(
                    f"    Skipping '{db_post['title'][:40]}' — no significant new comments"
                )
                continue

            # Re-fetch full comments
            comments = fetch_comments(post_id, db_post["subreddit"])
            update_post_after_refresh(post_id, fresh_comment_count)

            refreshed.append(
                {
                    "id": post_id,
                    "title": db_post["title"],
                    "body": db_post["body"],
                    "score": db_post["post_score"],
                    "created_utc": db_post["created_utc"],
                    "subreddit": db_post["subreddit"],
                    "url": f"https://reddit.com/r/{db_post['subreddit']}/comments/{post_id}",
                    "comments": comments,
                }
            )

            seen_ids.add(post_id)
            print(f"    Refreshed '{db_post['title'][:40]}' → {len(comments)} comments")
            time.sleep(2)

        except Exception as e:
            print(f"    Error refreshing {post_id}: {e}")
            continue

    print(f"  Refreshed {len(refreshed)} posts with new engagement")
    return refreshed


def fetch_all():
    """
    Full fetch strategy:
      1. /new with 24h pagination — captures all fresh posts
      2. /hot top 25 — catches older posts still getting engagement
      3. DB active post refresh — recycles posts from last 3 days
    """
    all_data = []
    seen_ids = set()

    # --- Step 1 & 2: Fresh posts per subreddit ---
    for subreddit in SUBREDDITS:
        print(f"\nFetching r/{subreddit}...")

        # 24h new posts
        new_posts = fetch_new_24h(subreddit)
        for post in new_posts:
            if post["score"] < -5 or post["id"] in seen_ids:
                continue
            seen_ids.add(post["id"])
            save_post(
                {
                    "id": post["id"],
                    "subreddit": post["subreddit"],
                    "title": post["title"],
                    "selftext": post["body"],
                    "score": post["score"],
                    "num_comments": post.get("num_comments", 0),
                    "created_utc": post["created_utc"],
                }
            )
            comments = fetch_comments(post["id"], subreddit)
            post["comments"] = comments
            update_post_after_refresh(
                post["id"], post.get("num_comments", len(comments))
            )
            all_data.append(post)
            print(f"  [new] '{post['title'][:45]}' → {len(comments)} comments")
            time.sleep(2)

        time.sleep(5)

        # Hot posts — catches older posts with active discussion
        hot_posts = fetch_hot(subreddit, limit=50)
        for post in hot_posts:
            if post["score"] < -5 or post["id"] in seen_ids:
                continue
            seen_ids.add(post["id"])
            save_post(
                {
                    "id": post["id"],
                    "subreddit": post["subreddit"],
                    "title": post["title"],
                    "selftext": post["body"],
                    "score": post["score"],
                    "num_comments": post.get("num_comments", 0),
                    "created_utc": post["created_utc"],
                }
            )
            comments = fetch_comments(post["id"], subreddit)
            post["comments"] = comments
            update_post_after_refresh(
                post["id"], post.get("num_comments", len(comments))
            )
            all_data.append(post)
            print(f"  [hot] '{post['title'][:45]}' → {len(comments)} comments")
            time.sleep(2)

        time.sleep(10)

    # --- Step 3: Refresh active posts from DB (3-day recycling) ---
    print(f"\nRefreshing active posts from database...")
    refreshed = refresh_active_posts(seen_ids)
    all_data.extend(refreshed)

    # --- Step 4: Archive posts older than 3 days ---
    print(f"\nArchiving old posts...")
    archive_old_posts()

    print(f"\n✓ Total: {len(all_data)} posts ready for analysis")
    print(
        f"  ({len(all_data) - len(refreshed)} fresh + {len(refreshed)} refreshed from DB)"
    )
    return all_data


if __name__ == "__main__":
    data = fetch_all()
    print(data[0])
