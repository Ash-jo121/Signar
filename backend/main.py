import json
import math
import re
from google_sheets_integration import update_spreadsheet
from yahooFn import enrich_with_price
from scraper import fetch_all
from extractor import aggregate_tickers, extract_from_post
from sentiment import analyze_sentiment
import random
from tqdm import tqdm
import traceback


def has_diverse_contexts(contexts, min_unique_patterns=3):
    patterns = set(c["text"][:30] for c in contexts)
    return len(patterns) >= min_unique_patterns


def is_valid_context(text: str) -> bool:
    cleaned = re.sub(r"http\S+", "", text).strip()

    # Too short after URL removal
    if len(cleaned) < 30:
        return False

    # Just emojis and caps — watchlist spam
    alpha_chars = sum(1 for c in cleaned if c.isalpha())
    if alpha_chars < 20:
        return False

    # Common low quality patterns
    LOW_QUALITY_PATTERNS = [
        r"WATCHLIST",
        r"SET UPS",
        r"MARKET OPEN",
        r"GOOD MORNING",
        r"END OF DAY",
        r"AFTER HOURS",
        r"^[\s\W]+$",  # only whitespace/punctuation
    ]
    for pattern in LOW_QUALITY_PATTERNS:
        if re.search(pattern, cleaned, re.IGNORECASE):
            return False

    return True


def clean_context(text: str) -> str:
    # Remove URLs
    text = re.sub(r"http\S+|www\S+", "", text)
    # Remove Reddit image previews
    text = re.sub(r"https://preview\.redd\.it\S+", "", text)
    # Remove HTML entities
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    # Clean up extra whitespace
    text = re.sub(r"\n+", " ", text).strip()
    return text


def sample_contexts(contexts, ticker, max_contexts=15):
    if len(contexts) <= max_contexts:
        return contexts

    # Tier 1: contexts that explicitly mention the ticker
    direct = [c for c in contexts if ticker.upper() in c.upper()]

    # Tier 2: longer contexts (more information dense)
    others = [c for c in contexts if c not in direct]
    sorted_others = sorted(others, key=len, reverse=True)

    # Take all direct mentions first, fill rest with longest others
    selected = direct[:10] + sorted_others[: max(0, max_contexts - len(direct[:10]))]
    return selected[:max_contexts]


def analyze_ticker_sentiment(all_posts):
    master = {}
    groq_calls = 0
    finbert_calls = 0

    # Progress bar for post collection pass
    print("\nPass 1: Collecting contexts from posts...")
    for post in tqdm(all_posts, desc="Collecting", unit="post"):
        found = extract_from_post(post)

        for ticker, data in found.items():
            if ticker not in master:
                master[ticker] = {
                    "mentions": 0,
                    "contexts": [],
                    "post_scores": [],
                    "top_comment": None,
                }

            master[ticker]["mentions"] += data["mentions"]
            master[ticker]["post_scores"].append(post["score"])
            if has_diverse_contexts(data["contexts"]):
                for context in data["contexts"]:
                    if is_valid_context(context["text"]):
                        cleaned = clean_context(context["text"])
                        master[ticker]["contexts"].append(
                            {
                                "full": cleaned[:500],
                                "short": cleaned[:200],
                                "score": context["score"],
                                "source": context["source"],
                            }
                        )
            # Track highest-upvoted comment across all posts for this ticker
            tc = data.get("top_comment")
            if tc:
                existing = master[ticker]["top_comment"]
                if existing is None or tc["score"] > existing["score"]:
                    master[ticker]["top_comment"] = tc

    # Count total contexts to analyze after sampling
    total_contexts = sum(
        min(len(data["contexts"]), 15)
        for data in master.values()
        if data["mentions"] >= 5  # match your filter
    )

    print(f"\nPass 2: Analyzing sentiment for {len(master)} tickers...")
    print(f"Total contexts to analyze: {total_contexts}")

    results = []

    # Progress bar for sentiment analysis pass
    with tqdm(total=total_contexts, desc="Analyzing", unit="context") as pbar:
        for ticker, data in master.items():
            try:
                all_ctx_count = len(data["contexts"])
                if data["mentions"] < 5:
                    continue

                all_short_texts = [c["short"] for c in data["contexts"]]

                unique_contexts = list({c[:50]: c for c in all_short_texts}.values())
                sampled_contexts = sample_contexts(
                    unique_contexts, ticker, max_contexts=15
                )
                print(
                    f"  {ticker}: {all_ctx_count} contexts → sampling {len(sampled_contexts)}"
                )

                top_contexts = []

                short_to_full = {}
                short_to_score = {}
                short_to_source = {}

                for c in data["contexts"]:
                    short_to_full[c["short"]] = c["full"]
                    short_to_score[c["short"]] = c["score"]
                    short_to_source[c["short"]] = c["source"]

                post_scores = []
                comment_scores = []

                for context_short in sampled_contexts:
                    sentiment = analyze_sentiment(context_short)
                    ctx_score = short_to_score.get(context_short, 0)
                    source = short_to_source.get(context_short, "comment")

                    if sentiment["source"] == "groq":
                        groq_calls += 1
                    elif sentiment["source"] == "finbert":
                        finbert_calls += 1

                    effective_score = sentiment["score"]

                    if source == "comment":
                        # Improvement 3: community downvoting a bullish comment is a bearish signal
                        if effective_score > 0.3 and ctx_score < -2:
                            effective_score = effective_score * -0.5
                        comment_weight = min(2.0, max(0.5, 1.0 + (ctx_score / 100)))
                        comment_scores.append(effective_score * comment_weight)
                    else:
                        post_scores.append(effective_score)

                    full_text = short_to_full.get(context_short, context_short)
                    top_contexts.append(
                        {
                            "text": full_text[:300],
                            "sentiment": sentiment["label"],
                            "score": sentiment["score"],
                        }
                    )

                    pbar.set_postfix(
                        {"ticker": ticker, "groq": groq_calls, "finbert": finbert_calls}
                    )
                    pbar.update(1)

            except Exception as e:
                print(f"Error analyzing sentiment for {ticker}: {e}")
                traceback.print_exc()
                continue

            # Improvement 1: post body = 1 voice, comments = community judgment
            # Give community more weight when there's high engagement (>=10 comment contexts)
            avg_post = sum(post_scores) / len(post_scores) if post_scores else 0
            avg_community = (
                sum(comment_scores) / len(comment_scores) if comment_scores else 0
            )

            if post_scores and comment_scores:
                post_weight = 0.3 if len(comment_scores) >= 10 else 0.5
                community_weight = 1.0 - post_weight
                avg_sentiment = (
                    avg_post * post_weight + avg_community * community_weight
                )
            elif post_scores:
                avg_sentiment = avg_post
            else:
                avg_sentiment = avg_community

            # Improvement 2: contrarian signal — top comment strongly contradicts post thesis
            top_comment = data.get("top_comment")
            if top_comment and avg_post > 0.3 and top_comment["score"] > 20:
                tc_sentiment = analyze_sentiment(top_comment["text"][:200])
                groq_calls += 1 if tc_sentiment["source"] == "groq" else 0
                finbert_calls += 1 if tc_sentiment["source"] == "finbert" else 0
                if tc_sentiment["score"] < -0.3:
                    print(
                        f"  {ticker}: contrarian signal detected (top comment score={top_comment['score']}, sentiment={tc_sentiment['score']:.2f})"
                    )
                    avg_sentiment = max(-1.0, avg_sentiment - 0.5)

            final_score = avg_sentiment * (1 + math.log(1 + data["mentions"]) * 0.3)

            results.append(
                {
                    "ticker": ticker,
                    "mentions": round(data["mentions"], 1),
                    "avg_sentiment": round(avg_sentiment, 3),
                    "final_score": round(final_score, 3),
                    "top_contexts": top_contexts[:7],
                }
            )

    print(f"\nSentiment sources: FinBERT={finbert_calls}, Groq={groq_calls}")
    print(f"Groq API calls used: {groq_calls}/14400 daily limit")
    print(f"Groq API calls efficiency: {groq_calls / 14400 * 100:.2f}%")

    results.sort(key=lambda x: x["final_score"], reverse=True)
    results = [r for r in results if r["mentions"] >= 2]
    return results


if __name__ == "__main__":
    print("=== ThreadRadar ===\n")

    print("Step 1: Fetching posts...")
    posts = fetch_all()

    print("\nStep 2: Analyzing tickers and sentiment...")
    results = analyze_ticker_sentiment(posts)

    print("\nStep 3: Adding Stock prices from yahoo finance...")
    results = enrich_with_price(results)

    results = [
        r for r in results if r.get("price", 0) > 0.01 and r.get("price", 0) <= 15
    ]

    results = [r for r in results if r["mentions"] >= 5 and len(r["top_contexts"]) >= 3]

    print("\nStep 4: Writing output to files...\n")

    with open("output.json", "w", encoding="utf-8") as file:
        json.dump(results[:10], file, indent=2, ensure_ascii=False)

    with open("output.txt", "w", encoding="utf-8") as file:
        for r in results[:10]:
            file.write(f"${r['ticker']}\n")
            file.write(
                f"  Mentions: {r['mentions']} | Sentiment: {r['avg_sentiment']:+.3f} | Score: {r['final_score']:+.3f}\n"
            )
            file.write(
                f"  Context: {r['top_contexts'][0]['text'][:100] if r['top_contexts'] else 'N/A'}\n"
            )
            file.write("\n")  # blank line between stocks

    print("\nStep 5: Updating Google Sheet...")
    try:
        update_spreadsheet(results)
    except Exception as e:
        print(f"Google Sheets update failed: {e}")
        print("output.json was already saved — data is not lost")
