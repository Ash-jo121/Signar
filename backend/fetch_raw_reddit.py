import argparse
import json
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

from constants.config import LOOKBACK_SECONDS, VAMPIRE_LOOKBACK_SECONDS
from constants.subreddits import BEARISH_SUBREDDITS, SUBREDDITS
from runtime_paths import raw_data_path

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

BLOCK_MARKERS = ("network security", "theme-beta", "blocked", "/cdn-cgi/")
LISTING_BACKOFFS = [30, 90, 180]
COMMENT_BACKOFFS = [30, 60, 120]
AUTHOR_BACKOFFS = [30, 60]

MIN_GAP = float(os.getenv("REDDIT_FETCH_MIN_GAP", "1.2"))
MAX_GAP = float(os.getenv("REDDIT_FETCH_MAX_GAP", "2.8"))
MIN_RAW_POSTS = int(os.getenv("THREADRADAR_MIN_RAW_POSTS", "200"))
AUTHOR_LOOKUP_COOLDOWN_SECONDS = int(os.getenv("AUTHOR_LOOKUP_COOLDOWN_SECONDS", "180"))
# 0 means unlimited. Keep defaults complete; use env caps only if Reddit 429s
# become worse than the missing-comment/missing-author tradeoff.
MAX_COMMENT_FETCHES = int(os.getenv("REDDIT_MAX_COMMENT_FETCHES", "0"))
MAX_AUTHOR_LOOKUPS = int(os.getenv("AUTHOR_PROFILE_LOOKUP_LIMIT", "0"))


class OptionalFetchRateLimited(Exception):
    pass


class RawDataValidationError(Exception):
    pass


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def reddit_url(path):
    return f"https://old.reddit.com{path}"


def proxy_config():
    user = os.getenv("PROXY_USER")
    password = os.getenv("PROXY_PASS")
    if not user or not password:
        return None
    host = os.getenv("PROXY_HOST", "gate.decodo.com")
    port = os.getenv("PROXY_PORT", "10000")
    return {
        "server": f"http://{host}:{port}",
        "username": user,
        "password": password,
    }


class StealthRedditFetcher:
    def __init__(self, headless=True):
        self.request_count = 0
        self.rate_limit_count = 0
        self.hard_block_count = 0
        self._consecutive_429s = 0
        self._adaptive_gap_extra = 0.0
        self._stealth = Stealth()
        self._pw_ctx = self._stealth.use_sync(sync_playwright())
        self._pw = self._pw_ctx.__enter__()
        launch_kwargs = {"headless": headless}
        proxy = proxy_config()
        if proxy:
            launch_kwargs["proxy"] = proxy
        self._browser = self._pw.chromium.launch(**launch_kwargs)
        self._context = self._browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1280, "height": 800},
            locale="en-US",
        )
        self._page = self._context.new_page()

    def warmup(self):
        try:
            response = self._page.goto(
                "https://old.reddit.com/r/pennystocks/",
                wait_until="networkidle",  # wait until no network activity for 500ms
                timeout=60000,
            )
            # Extra wait for any JS-driven redirects to complete
            time.sleep(5)
            
            status = response.status if response else "None"
            current_url = self._page.url
            print(f"Warmup status: {status}, final URL: {current_url}")
            
            try:
                body_preview = self._page.evaluate(
                    "() => document.body ? document.body.innerText.slice(0, 300) : 'NO BODY'"
                )
                print(f"Warmup body preview: {body_preview[:300]}")
            except Exception as eval_err:
                print(f"Warmup eval failed (redirect likely): {eval_err}")
                # Check where we ended up
                print(f"Current URL after redirect: {self._page.url}")
                
        except Exception as e:
            print(f"Warmup failed entirely: {e}")
            raise

    def pace(self):
        time.sleep(random.uniform(MIN_GAP, MAX_GAP) + self._adaptive_gap_extra)

    def get_json(self, url, backoffs):
        for attempt, backoff in enumerate([0] + backoffs):
            if backoff:
                print(
                    f"      [429 backoff] sleeping {backoff}s before retry "
                    f"{attempt}/{len(backoffs)} for {url.split('reddit.com')[-1]}"
                )
                time.sleep(backoff)

            self.request_count += 1
            response = self._page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=45000,
            )
            status = response.status if response else 0
            body = self._page.evaluate(
                "() => document.body ? document.body.innerText : ''"
            )

            if status == 429:
                self.rate_limit_count += 1
                self._consecutive_429s += 1
                self._adaptive_gap_extra = min(self._consecutive_429s * 5.0, 30.0)
                if attempt < len(backoffs):
                    continue
                raise OptionalFetchRateLimited(f"429 persisted: {url}")

            low = body[:300].lower()
            if status != 200 or any(marker in low for marker in BLOCK_MARKERS):
                self.hard_block_count += 1
                raise RuntimeError(f"HARD BLOCK status={status}: {url}")

            self._consecutive_429s = max(0, self._consecutive_429s - 1)
            self._adaptive_gap_extra = max(0.0, self._adaptive_gap_extra - 1.0)
            return json.loads(body)

        raise OptionalFetchRateLimited(f"fetch exhausted retries: {url}")

    def close(self):
        try:
            self._browser.close()
        finally:
            self._pw_ctx.__exit__(None, None, None)


def parse_post_child(child):
    data = child["data"]
    return {
        "id": data["id"],
        "title": data.get("title", ""),
        "body": data.get("selftext", ""),
        "score": data.get("score", 0),
        "subreddit": data.get("subreddit", ""),
        "url": f"https://reddit.com{data.get('permalink', '')}",
        "created_utc": data.get("created_utc", 0),
        "num_comments": data.get("num_comments", 0),
        "author": data.get("author", "unknown"),
        "comments": [],
        "fetch_errors": [],
    }


def parse_comments_recursive(children):
    """Keep the raw comment tree; ticker extraction happens in the analysis pipeline."""
    comments = []
    for child in children:
        if child.get("kind") != "t1":
            continue

        data = child.get("data", {})
        comment = {
            "body": data.get("body", ""),
            "score": data.get("score", 0),
            "author": data.get("author", "unknown"),
            "replies": [],
        }

        replies = data.get("replies", "")
        if replies and isinstance(replies, dict):
            comment["replies"] = parse_comments_recursive(
                replies.get("data", {}).get("children", [])
            )
        comments.append(comment)
    return comments


def fetch_listing_posts(fetcher, subreddit, sort, lookback_seconds, limit=100):
    cutoff = datetime.now(timezone.utc).timestamp() - lookback_seconds
    posts = []
    after = None
    page = 0

    while True:
        path = f"/r/{subreddit}/{sort}.json?limit={limit}"
        if after:
            path += f"&after={after}"

        data = fetcher.get_json(reddit_url(path), LISTING_BACKOFFS)["data"]
        children = data.get("children", [])
        after = data.get("after")
        reached_cutoff = False

        for child in children:
            post = parse_post_child(child)
            if sort == "new" and post["created_utc"] < cutoff:
                reached_cutoff = True
                break
            posts.append(post)

        page += 1
        if sort != "new" or reached_cutoff or not after or page > 8:
            return posts
        fetcher.pace()


def comment_priority(post):
    return (
        int(post.get("num_comments") or 0),
        int(post.get("score") or 0),
    )


def fetch_comments_for_posts(fetcher, posts):
    prioritized = sorted(posts, key=comment_priority, reverse=True)
    # By default we fetch every comment thread. The priority list only matters
    # when REDDIT_MAX_COMMENT_FETCHES is set as a safety valve for 429-heavy runs.
    if MAX_COMMENT_FETCHES > 0:
        selected_ids = {post["id"] for post in prioritized[:MAX_COMMENT_FETCHES]}
    else:
        selected_ids = {post["id"] for post in prioritized}
    skipped = 0
    failures = 0

    for index, post in enumerate(posts, start=1):
        if post["id"] not in selected_ids:
            skipped += 1
            post["comments_skipped_reason"] = "comment_fetch_cap"
            continue

        path = f"/r/{post['subreddit']}/comments/{post['id']}.json"
        try:
            data = fetcher.get_json(reddit_url(path), COMMENT_BACKOFFS)
            children = data[1]["data"]["children"] if len(data) > 1 else []
            post["comments"] = parse_comments_recursive(children)
        except OptionalFetchRateLimited as exc:
            failures += 1
            post["fetch_errors"].append(str(exc))
            post["comments"] = []
        except Exception as exc:
            failures += 1
            post["fetch_errors"].append(str(exc)[:200])
            post["comments"] = []

        if index % 25 == 0:
            print(f"    comments: {index}/{len(posts)} posts visited")
        fetcher.pace()

    return {"selected": len(selected_ids), "skipped": skipped, "failures": failures}


def authors_needing_profiles(posts):
    """Collect raw authors so credibility metadata is available before analysis."""
    authors = []
    seen = set()

    def add(author):
        if author and author not in {"unknown", "[deleted]", "AutoModerator"}:
            if author not in seen:
                seen.add(author)
                authors.append(author)

    def add_comment_authors(comments):
        for comment in comments:
            add(comment.get("author"))
            add_comment_authors(comment.get("replies", []))

    for post in posts:
        add(post.get("author"))
        add_comment_authors(post.get("comments", []))

    if MAX_AUTHOR_LOOKUPS > 0:
        return authors[:MAX_AUTHOR_LOOKUPS]
    return authors


def fetch_author_profiles(fetcher, authors):
    profiles = {}
    failures = 0
    for author in authors:
        try:
            data = fetcher.get_json(
                reddit_url(f"/user/{author}/about.json"),
                AUTHOR_BACKOFFS,
            ).get("data", {})
            created_utc = data.get("created_utc")
            profiles[author] = {
                "author_created_utc": created_utc,
                "author_account_age_days": (
                    max(0, int((time.time() - created_utc) / 86400))
                    if created_utc
                    else None
                ),
                "author_link_karma": data.get("link_karma"),
                "author_comment_karma": data.get("comment_karma"),
            }
        except Exception:
            failures += 1
            profiles[author] = {}
        fetcher.pace()
    return profiles, failures


def attach_profiles(posts, profiles):
    def attach_comment_profiles(comments):
        for comment in comments:
            comment.update(profiles.get(comment.get("author"), {}))
            attach_comment_profiles(comment.get("replies", []))

    for post in posts:
        post.update(profiles.get(post.get("author"), {}))
        attach_comment_profiles(post.get("comments", []))


def dedupe_posts(posts):
    seen = set()
    deduped = []
    for post in posts:
        if post["id"] in seen:
            continue
        seen.add(post["id"])
        deduped.append(post)
    return deduped


def validate_raw_payload(payload):
    errors = []
    posts = payload.get("posts")
    if not isinstance(posts, list):
        errors.append("missing_or_invalid_posts")
        posts = []

    fetched_at = payload.get("fetched_at")
    if not fetched_at:
        errors.append("missing_fetched_at")

    if len(posts) < MIN_RAW_POSTS:
        errors.append(f"too_few_posts:{len(posts)}<{MIN_RAW_POSTS}")

    missing_subreddit = sum(
        1 for post in posts if not isinstance(post, dict) or not post.get("subreddit")
    )
    if missing_subreddit:
        errors.append(f"missing_subreddit:{missing_subreddit}")

    return errors


def build_payload(
    started,
    normal_posts,
    vampire_posts,
    comment_stats,
    vampire_comment_stats,
    fetcher,
    errors,
    authors=None,
    author_failures=0,
    author_lookup_status="pending",
):
    authors = authors or []
    return {
        "schema_version": 1,
        "fetched_at": utc_now_iso(),
        "fetch_metadata": {
            "duration_seconds": round(time.time() - started, 2),
            "normal_post_count": len(normal_posts),
            "vampire_post_count": len(vampire_posts),
            "comment_stats": comment_stats,
            "vampire_comment_stats": vampire_comment_stats,
            "author_lookup_status": author_lookup_status,
            "author_lookup_count": len(authors),
            "author_lookup_failures": author_failures,
            "requests": fetcher.request_count,
            "rate_limits": fetcher.rate_limit_count,
            "hard_blocks": fetcher.hard_block_count,
            "comment_fetch_limit": (
                MAX_COMMENT_FETCHES if MAX_COMMENT_FETCHES > 0 else None
            ),
            "author_lookup_limit": (
                MAX_AUTHOR_LOOKUPS if MAX_AUTHOR_LOOKUPS > 0 else None
            ),
            "author_lookup_cooldown_seconds": AUTHOR_LOOKUP_COOLDOWN_SECONDS,
            "errors": errors,
        },
        "posts": normal_posts,
        "vampire_posts": vampire_posts,
    }


def fetch_raw_payload(headless=True, checkpoint_path=None):
    fetcher = StealthRedditFetcher(headless=headless)
    started = time.time()
    normal_posts = []
    vampire_posts = []
    errors = []

    try:
        fetcher.warmup()

        for subreddit in SUBREDDITS:
            print(f"\nFetching r/{subreddit} listings...")
            try:
                new_posts = fetch_listing_posts(
                    fetcher,
                    subreddit,
                    "new",
                    LOOKBACK_SECONDS,
                )
                hot_posts = fetch_listing_posts(fetcher, subreddit, "hot", 0, limit=50)
                normal_posts.extend(new_posts + hot_posts)
                print(
                    f"  r/{subreddit}: {len(new_posts)} new + {len(hot_posts)} hot"
                )

            except Exception as exc:
                errors.append({"subreddit": subreddit, "stage": "listing", "error": str(exc)})
            fetcher.pace()

        for subreddit in BEARISH_SUBREDDITS:
            print(f"\nFetching r/{subreddit} bearish listings...")
            try:
                new_posts = fetch_listing_posts(
                    fetcher,
                    subreddit,
                    "new",
                    VAMPIRE_LOOKBACK_SECONDS,
                )
                hot_posts = fetch_listing_posts(fetcher, subreddit, "hot", 0, limit=50)
                vampire_posts.extend(new_posts + hot_posts)
                print(
                    f"  r/{subreddit}: {len(new_posts)} new + {len(hot_posts)} hot"
                )
            except Exception as exc:
                errors.append({"subreddit": subreddit, "stage": "listing", "error": str(exc)})
            fetcher.pace()

        normal_posts = dedupe_posts(normal_posts)
        vampire_posts = dedupe_posts(vampire_posts)
        print(f"\nFetch summary: {len(normal_posts)} normal posts, {len(vampire_posts)} vampire posts")
        print(f"Errors during fetch: {json.dumps(errors, indent=2)}")
        print(f"Fetcher stats: {fetcher.request_count} requests, {fetcher.rate_limit_count} rate limits, {fetcher.hard_block_count} hard blocks")
        if len(normal_posts) < MIN_RAW_POSTS:
            raise RawDataValidationError(
                f"Only {len(normal_posts)} normal posts fetched; "
                f"minimum is {MIN_RAW_POSTS}. Skipping comments/upload."
            )

        comment_stats = fetch_comments_for_posts(fetcher, normal_posts)
        vampire_comment_stats = fetch_comments_for_posts(fetcher, vampire_posts)
        partial_payload = build_payload(
            started,
            normal_posts,
            vampire_posts,
            comment_stats,
            vampire_comment_stats,
            fetcher,
            errors,
            author_lookup_status="pending",
        )
        if checkpoint_path:
            write_payload(partial_payload, checkpoint_path)
            print(f"  Checkpoint raw_data.json written before author lookups: {checkpoint_path}")

        authors = authors_needing_profiles(normal_posts + vampire_posts)
        if authors and AUTHOR_LOOKUP_COOLDOWN_SECONDS > 0:
            print(
                "  Cooling down "
                f"{AUTHOR_LOOKUP_COOLDOWN_SECONDS}s before author lookups..."
            )
            time.sleep(AUTHOR_LOOKUP_COOLDOWN_SECONDS)

        profiles, author_failures = fetch_author_profiles(fetcher, authors)
        attach_profiles(normal_posts, profiles)
        attach_profiles(vampire_posts, profiles)

        return build_payload(
            started,
            normal_posts,
            vampire_posts,
            comment_stats,
            vampire_comment_stats,
            fetcher,
            errors,
            authors=authors,
            author_failures=author_failures,
            author_lookup_status="completed",
        )
    finally:
        fetcher.close()


def write_payload(payload, output_path):
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_name(f"{output_path.name}.tmp")
    with open(temp_path, "w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2, ensure_ascii=False)
    os.replace(temp_path, output_path)
    return output_path


def upload_payload(path, railway_url, api_key, trigger_analysis=False):
    endpoint = f"{railway_url.rstrip('/')}/api/upload-raw-data"
    params = {"trigger_analysis": "true" if trigger_analysis else "false"}
    with open(path, "rb") as file:
        response = requests.post(
            endpoint,
            params=params,
            headers={"x-api-key": api_key},
            files={"file": (Path(path).name, file, "application/json")},
            timeout=120,
        )
    response.raise_for_status()
    return response.json()


def main():
    parser = argparse.ArgumentParser(description="Fetch Reddit raw data with Playwright")
    parser.add_argument("--output", default=str(raw_data_path()))
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--upload", action="store_true")
    parser.add_argument("--trigger-analysis", action="store_true")
    args = parser.parse_args()

    try:
        payload = fetch_raw_payload(
            headless=not args.headed,
            checkpoint_path=args.output,
        )
    except RawDataValidationError as exc:
        print(f"Raw fetch skipped: {exc}")
        return

    validation_errors = validate_raw_payload(payload)
    if validation_errors:
        raise SystemExit(f"Raw data validation failed: {validation_errors}")

    output = write_payload(payload, args.output)
    print(f"\nRaw Reddit data written to {output}")
    print(json.dumps(payload["fetch_metadata"], indent=2))

    if args.upload:
        railway_url = os.environ["RAILWAY_URL"]
        api_key = os.environ["UPLOAD_API_KEY"]
        result = upload_payload(output, railway_url, api_key, args.trigger_analysis)
        print(f"Upload result: {result}")


if __name__ == "__main__":
    main()
