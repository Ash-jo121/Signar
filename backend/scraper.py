import datetime
import os
import re
import requests
import time
from datetime import timezone, datetime
from urllib.parse import quote
from constants.config import LOOKBACK_SECONDS, VAMPIRE_LOOKBACK_SECONDS
from sentiment import classify_vampire_post
from constants.subreddits import BEARISH_SUBREDDITS, SUBREDDITS
from constants.exclusion import COMMON_ABBREVIATIONS, LARGE_CAP_EXCLUDE
from helpers.tickers import VALID_TICKERS
from database import (
    archive_old_posts,
    get_active_posts,
    get_connection,
    save_post,
    update_post_after_refresh,
)

HEADERS = {"User-Agent": "ThreadRadar/1.0"}

print(f"✓ Scraper loaded VALID_TICKERS: {len(VALID_TICKERS)} tickers")


def get_proxies():
    """
    Returns proxy dict if credentials available,
    None otherwise (falls back to direct connection)
    """
    user = os.getenv("PROXY_USER")
    passwd = os.getenv("PROXY_PASS")
    host = os.getenv("PROXY_HOST", "gate.decodo.com")
    port = os.getenv("PROXY_PORT", "10000")

    if user and passwd:
        proxy_url = f"http://{user}:{passwd}@{host}:{port}"
        print(f"✓ Proxy enabled: {host}:{port}")
        return {"http": proxy_url, "https": proxy_url}

    print("✓ Proxy disabled — direct connection")
    return None


PROXIES = get_proxies()
AUTHOR_PROFILE_CACHE = {}
AUTHOR_PROFILE_LOOKUPS = 0
AUTHOR_PROFILE_LOOKUP_LIMIT = int(os.getenv("AUTHOR_PROFILE_LOOKUP_LIMIT", "180"))


def fetch_author_profile(author):
    """
    Fetch lightweight author credibility metadata with an in-process cap.

    Missing, deleted, suspended, or rate-limited profiles return neutral metadata.
    """
    global AUTHOR_PROFILE_LOOKUPS

    if not author or author in {"unknown", "[deleted]", "AutoModerator"}:
        return {}

    if author in AUTHOR_PROFILE_CACHE:
        return AUTHOR_PROFILE_CACHE[author]

    if AUTHOR_PROFILE_LOOKUPS >= AUTHOR_PROFILE_LOOKUP_LIMIT:
        AUTHOR_PROFILE_CACHE[author] = {}
        return {}

    AUTHOR_PROFILE_LOOKUPS += 1
    url = f"https://www.reddit.com/user/{quote(author)}/about.json"

    try:
        response = requests.get(url, headers=HEADERS, proxies=PROXIES, timeout=20)
        if response.status_code != 200:
            AUTHOR_PROFILE_CACHE[author] = {}
            return {}

        data = response.json().get("data", {})
        created_utc = data.get("created_utc")
        profile = {
            "author_created_utc": created_utc,
            "author_account_age_days": (
                max(0, int((time.time() - created_utc) / 86400))
                if created_utc
                else None
            ),
            "author_link_karma": data.get("link_karma"),
            "author_comment_karma": data.get("comment_karma"),
        }
        AUTHOR_PROFILE_CACHE[author] = profile
        return profile

    except Exception as e:
        print(f"    Author profile fetch failed for u/{author}: {str(e)[:60]}")
        AUTHOR_PROFILE_CACHE[author] = {}
        return {}


def attach_author_profile(item):
    item.update(fetch_author_profile(item.get("author", "unknown")))
    return item


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
    post = {
        "id": p["data"]["id"],
        "title": p["data"]["title"],
        "body": p["data"].get("selftext", ""),
        "score": p["data"]["score"],
        "subreddit": p["data"]["subreddit"],
        "url": f"https://reddit.com{p['data']['permalink']}",
        "created_utc": p["data"]["created_utc"],
        "num_comments": p["data"]["num_comments"],
        "author": p["data"].get("author", "unknown"),
    }
    if extract_tickers_simple(post["title"] + " " + post["body"]):
        attach_author_profile(post)
    return post


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
                mention_weight = max(0.1, 0.5 - (depth * 0.2))

            comment = {
                "body": body,
                "score": data["score"],
                "author": data.get("author", "unknown"),
                "tickers": effective_tickers,
                "inherited": inherited,
                "mention_weight": mention_weight,
            }
            if effective_tickers:
                attach_author_profile(comment)
            comments.append(comment)

            replies = data.get("replies", "")
            if replies and isinstance(replies, dict):
                nested = replies["data"]["children"]
                comments.extend(
                    parse_comments_recursive(nested, effective_tickers, depth + 1)
                )

    return comments


def fetch_comments(post_id, subreddit):
    url = f"https://www.reddit.com/r/{subreddit}/comments/{post_id}.json"

    for attempt in range(3):
        try:
            response = requests.get(url, headers=HEADERS, proxies=PROXIES, timeout=60)

            if response.status_code == 200:
                comment_list = response.json()[1]["data"]["children"]
                return parse_comments_recursive(comment_list, parent_tickers=None)

            elif response.status_code == 429:
                wait = (attempt + 1) * 30
                print(f"    Rate limited on comments. Waiting {wait}s...")
                time.sleep(wait)

            else:
                print(f"    Comment fetch failed for {post_id}: {response.status_code}")
                return []

        except requests.exceptions.ProxyError as e:
            print(
                f"    Proxy error on attempt {attempt+1} for {post_id}: {str(e)[:60]}"
            )
            if attempt < 2:
                time.sleep(5)
                continue
            return []

        except requests.exceptions.Timeout:
            print(f"    Timeout on attempt {attempt+1} for {post_id}")
            if attempt < 2:
                time.sleep(5)
                continue
            return []

        except Exception as e:
            print(f"    Comment fetch error for {post_id}: {str(e)[:60]}")
            return []

    return []


def fetch_new_24h(subreddit, lookback=None):
    if lookback is None:
        lookback = LOOKBACK_SECONDS

    cutoff = datetime.now(timezone.utc).timestamp() - lookback
    posts = []
    after = None
    page = 0

    while True:
        url = f"https://www.reddit.com/r/{subreddit}/new.json?limit=100"
        if after:
            url += f"&after={after}"

        for attempt in range(3):
            try:
                response = requests.get(
                    url, headers=HEADERS, proxies=PROXIES, timeout=60
                )

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
                            f"    /new: {len(posts)} posts in last "
                            f"{lookback // 3600}h ({page + 1} pages)"
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
                        f"    Failed r/{subreddit}/new page {page}: "
                        f"{response.status_code}"
                    )
                    return posts

            except (
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                requests.exceptions.ProxyError,
            ) as e:
                print(
                    f"    Connection error on attempt {attempt+1} "
                    f"for r/{subreddit}/new: {str(e)[:60]}"
                )
                if attempt < 2:
                    time.sleep(10)
                    continue
                print(f"    Giving up on r/{subreddit}/new after 3 attempts")
                return posts

    return posts


def fetch_hot(subreddit, limit=50):
    url = f"https://www.reddit.com/r/{subreddit}/hot.json?limit={limit}"

    for attempt in range(3):
        try:
            response = requests.get(url, headers=HEADERS, proxies=PROXIES, timeout=60)

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

        except (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.ProxyError,
        ) as e:
            print(
                f"    Connection error on attempt {attempt+1} "
                f"for r/{subreddit}/hot: {str(e)[:60]}"
            )
            if attempt < 2:
                time.sleep(10)
                continue
            return []

    return []


def should_reanalyze(db_post, fresh_comment_count):
    """
    Only re-fetch comments if engagement has grown meaningfully.
    Saves Groq API calls on posts that haven't changed.
    """
    old_count = db_post.get("comment_count_at_analysis", 0)

    if old_count == 0 or fresh_comment_count > old_count * 1.2:
        return True

    if fresh_comment_count - old_count >= 10:
        return True

    return False


def refresh_active_posts(seen_ids):
    active = get_active_posts()

    if not active:
        print("  No active posts to refresh")
        return []

    print(f"  Refreshing {len(active)} active posts from DB...")
    refreshed = []

    for db_post in active:
        post_id = db_post["id"]

        if post_id in seen_ids:
            continue

        url = f"https://www.reddit.com/r/{db_post['subreddit']}/comments/{post_id}.json?limit=1"
        try:
            response = requests.get(url, headers=HEADERS, proxies=PROXIES, timeout=60)
            if response.status_code != 200:
                continue

            post_data = response.json()[0]["data"]["children"][0]["data"]
            fresh_comment_count = post_data.get("num_comments", 0)

            if not should_reanalyze(db_post, fresh_comment_count):
                continue

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
                    "is_refresh": True,
                }
            )

            seen_ids.add(post_id)
            print(f"    Refreshed '{db_post['title'][:40]}' → {len(comments)} comments")
            time.sleep(2)

        except (requests.exceptions.ProxyError, requests.exceptions.Timeout) as e:
            print(f"    Proxy/timeout error refreshing {post_id}: {str(e)[:60]}")
            continue

        except Exception as e:
            print(f"    Error refreshing {post_id}: {e}")
            continue

    print(f"  Refreshed {len(refreshed)} posts with new engagement")
    return refreshed


def fetch_vampire_posts():
    """
    Fetch VampireStocks posts using VAMPIRE_LOOKBACK_SECONDS window.
    Posts are classified and stored in bearish_stocks table only —
    they never enter the main sentiment pipeline.
    """
    print(f"\nFetching r/VampireStocks (bearish signal source)...")

    new_posts = fetch_new_24h("VampireStocks", lookback=VAMPIRE_LOOKBACK_SECONDS)
    hot_posts = fetch_hot("VampireStocks", limit=50)

    # Deduplicate between new and hot
    seen = set()
    all_posts = []
    for post in new_posts + hot_posts:
        if post["id"] not in seen:
            seen.add(post["id"])
            all_posts.append(post)

    print(f"  Processing {len(all_posts)} VampireStocks posts...")
    total_flagged = 0

    for post in all_posts:
        post["comments"] = fetch_comments(post["id"], post["subreddit"])
        flagged = process_vampire_post(post)
        total_flagged += len(flagged)
        time.sleep(1)  # gentle on rate limits between Groq calls

    print(f"  VampireStocks: {total_flagged} bearish tickers flagged")


def flatten_comment_texts(comments, limit=12):
    """
    Convert already-fetched comments into text snippets for VampireStocks analysis.

    fetch_comments() already performs the Reddit comment fetch and returns a flat
    list in the legacy scraper path. Raw Playwright snapshots keep replies nested,
    so this also walks optional "replies" without making another network request.
    """
    texts = []

    def visit(items):
        for comment in items:
            body = (comment.get("body") or "").strip()
            if body:
                texts.append(body)
                if len(texts) >= limit:
                    return
            visit(comment.get("replies", []))
            if len(texts) >= limit:
                return

    visit(comments or [])
    return texts[:limit]


def build_vampire_analysis_body(post):
    comments = flatten_comment_texts(post.get("comments", []))
    if not comments:
        return post.get("body", "")

    comment_context = "\n".join(f"- {text[:240]}" for text in comments)
    return (
        f"{post.get('body', '')}\n\n"
        "Relevant comments from this VampireStocks thread:\n"
        f"{comment_context}"
    )


def fetch_all():
    """
    Full fetch strategy:
      1. VampireStocks — bearish signal source, separate pipeline
      2. /new with 24h pagination — captures all fresh posts
      3. /hot top 50 — catches older posts still getting engagement
      4. DB active post refresh — recycles posts from last 3 days
    """
    all_data = []
    seen_ids = set()

    # --- Step 1: VampireStocks bearish pipeline ---
    # Must run first so bearish flags are available for Step 3.5 in main.py
    fetch_vampire_posts()

    # --- Step 2 & 3: Fresh posts per subreddit ---
    for subreddit in SUBREDDITS:
        print(f"\nFetching r/{subreddit}...")

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
                    "author": post.get("author", "unknown"),
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
                    "author": post.get("author", "unknown"),
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

    # --- Step 4: Refresh active posts from DB (3-day recycling) ---
    print(f"\nRefreshing active posts from database...")
    refreshed = refresh_active_posts(seen_ids)
    all_data.extend(refreshed)

    # --- Step 5: Archive posts older than 3 days ---
    print(f"\nArchiving old posts...")
    archive_old_posts()

    print(f"\n✓ Total: {len(all_data)} posts ready for analysis")
    print(
        f"  ({len(all_data) - len(refreshed)} fresh + {len(refreshed)} refreshed from DB)"
    )
    return all_data


def process_vampire_post(post):
    """
    Classify a VampireStocks post and store bearish tickers in bearish_stocks.
    Never enters the main sentiment pipeline.
    Returns list of (ticker, flag_type, confidence) tuples.
    """
    title = post["title"]
    body = build_vampire_analysis_body(post)
    today = datetime.now().strftime("%Y-%m-%d")
    conn = get_connection()

    classification = classify_vampire_post(title, body)
    flag_type = classification.get("flag_type", "neutral")
    confidence = classification.get("confidence", 0.0)

    # Skip neutral or low confidence posts
    if flag_type == "neutral" or confidence < 0.5:
        conn.close()
        return []

    # Union tickers from text extraction and Groq's suggestion
    text_tickers = extract_tickers_simple(title + " " + body)
    groq_tickers = [
        t.upper()
        for t in classification.get("tickers_mentioned", [])
        if isinstance(t, str)
    ]
    all_tickers = set(text_tickers) | set(groq_tickers)

    flagged = []
    for ticker in all_tickers:
        if ticker not in VALID_TICKERS:
            continue
        try:
            conn.execute(
                """
                INSERT OR IGNORE INTO bearish_stocks
                (ticker, flagged_date, source_subreddit, flag_type,
                 confidence, post_title, post_url)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ticker,
                    today,
                    "VampireStocks",
                    flag_type,
                    confidence,
                    title[:200],
                    post.get("url", ""),
                ),
            )
            flagged.append((ticker, flag_type, confidence))
            print(
                f"  [VampireStocks] {ticker} → {flag_type} "
                f"(confidence={confidence:.2f})"
            )
        except Exception as e:
            print(f"  [VampireStocks] Error inserting {ticker}: {e}")

    conn.commit()
    conn.close()
    return flagged


if __name__ == "__main__":
    data = fetch_all()
    print(data[0])
