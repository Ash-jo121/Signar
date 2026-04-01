import re
from moderator import COMMUNITY_CALL_PATTERNS, MOD_ACTING_PATTERNS
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


def check_mod_intervention(comment_body, comment_score):
    """
    Check if a comment contains mod intervention or community pump warning.
    Returns dict with flag details or None if no intervention detected.
    """
    text_lower = comment_body.lower()

    for pattern in MOD_ACTING_PATTERNS:
        if re.search(pattern, text_lower):
            return {
                "mod_flagged": True,
                "mod_flag_type": "mod_acting",
                "mod_flag_score": comment_score,
            }

    for pattern in COMMUNITY_CALL_PATTERNS:
        if re.search(pattern, text_lower):
            return {
                "mod_flagged": True,
                "mod_flag_type": "community_call",
                "mod_flag_score": comment_score,
            }

    return None


def extract_from_post(post):
    found = {}

    # Skip post body for refreshed posts — already analyzed on first fetch
    if not post.get("is_refresh", False):
        text = post["title"] + " " + post["body"]
        tickers = extract_tickers(text)

        for ticker in tickers:
            if ticker not in found:
                found[ticker] = {
                    "mentions": 0,
                    "scores": [],
                    "contexts": [],
                    "top_comment": None,
                    "mod_flagged": False,
                    "mod_flag_type": None,
                    "mod_flag_score": 0,
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
        if not comment_tickers:
            continue

        # Check mod intervention on every comment regardless of ticker
        intervention = check_mod_intervention(
            comment.get("body", ""), comment.get("score", 0)
        )

        for ticker in comment_tickers:
            if ticker not in found:
                found[ticker] = {
                    "mentions": 0,
                    "scores": [],
                    "contexts": [],
                    "top_comment": None,
                    "mod_flagged": False,
                    "mod_flag_type": None,
                    "mod_flag_score": 0,
                }

            mention_weight = comment.get("mention_weight", 1.0)
            found[ticker]["mentions"] += mention_weight
            found[ticker]["scores"].append(comment["score"])
            found[ticker]["contexts"].append(
                {
                    "text": comment["body"][:300],
                    "source": "comment",
                    "score": comment["score"],
                }
            )

            # Apply mod intervention — upgrade if stronger signal found
            if intervention:
                existing_type = found[ticker]["mod_flag_type"]
                # mod_acting always wins over community_call
                if (
                    not found[ticker]["mod_flagged"]
                    or (
                        existing_type == "community_call"
                        and intervention["mod_flag_type"] == "mod_acting"
                    )
                    or (
                        intervention["mod_flag_score"] > found[ticker]["mod_flag_score"]
                    )
                ):
                    found[ticker]["mod_flagged"] = True
                    found[ticker]["mod_flag_type"] = intervention["mod_flag_type"]
                    found[ticker]["mod_flag_score"] = intervention["mod_flag_score"]

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
