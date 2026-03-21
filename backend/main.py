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
        comment_count = len(post.get("comments", []))
        engagement_weight = min(1.0, 0.3 + (comment_count / 50) * 0.7)
        found = extract_from_post(post)

        for ticker, data in found.items():
            if ticker not in master:
                master[ticker] = {
                    "mentions": 0,
                    "sentiment_scores": [],
                    "contexts": [],
                    "post_scores": [],
                }

            master[ticker]["mentions"] += data["mentions"]
            master[ticker]["post_scores"].append(post["score"])
            for context in data["contexts"]:
                if is_valid_context(context):
                    master[ticker]["contexts"].append(
                        {
                            "full": clean_context(context)[:500],
                            "short": clean_context(context)[:200],
                            "comment_score": max(0, context.get("comment_score", 0)),
                        }
                    )

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
                avg_post_score = (
                    sum(data["post_scores"]) / len(data["post_scores"])
                    if data["post_scores"]
                    else 0
                )
                engagement_weight = min(1.0, 0.3 + (len(data["contexts"]) / 50) * 0.7)

                sentiment_scores = []
                top_contexts = []

                short_to_full = {c["short"]: c["full"] for c in data["contexts"]}
                short_to_comment_score = {
                    c["short"]: c.get("comment_score", 0) for c in data["contexts"]
                }

                for context_short in sampled_contexts:
                    sentiment = analyze_sentiment(context_short)
                    comment_score = short_to_comment_score.get(context_short, 0)

                    if sentiment["source"] == "groq":
                        groq_calls += 1
                    elif sentiment["source"] == "finbert":
                        finbert_calls += 1

                    comment_weight = min(2.0, max(0.5, 1.0 + (comment_score / 100)))
                    weighted_score = (
                        sentiment["score"] * engagement_weight * comment_weight
                    )
                    sentiment_scores.append(weighted_score)
                    full_text = short_to_full.get(context_short, context_short)

                    top_contexts.append(
                        {
                            "text": full_text[:300],
                            "sentiment": sentiment["label"],
                            "score": sentiment["score"],
                        }
                    )

                    # Update progress bar with current ticker info
                    pbar.set_postfix(
                        {"ticker": ticker, "groq": groq_calls, "finbert": finbert_calls}
                    )
                    pbar.update(1)

            except Exception as e:
                print(f"Error analyzing sentiment for {ticker}: {e}")
                traceback.print_exc()
                continue

            avg_sentiment = (
                sum(sentiment_scores) / len(sentiment_scores) if sentiment_scores else 0
            )

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
