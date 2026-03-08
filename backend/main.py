import json
from yahooFn import enrich_with_price
from scraper import fetch_all
from extractor import aggregate_tickers, extract_from_post
from sentiment import analyze_sentiment

old_results = [
    {
        "ticker": "GANX",
        "mentions": 5,
        "avg_sentiment": 0.314,
        "final_score": 0.888,
        "top_contexts": [
            {
                "text": "Gain Therapeutics ($GANX) - The Parkinson's 'Unicorn' the biotech market is sleeping on. Clinical pr",
                "sentiment": "neutral",
                "score": 0.215,
            },
            {
                "text": "Is Gain Therapeutics about to make history at AD/PD(3/17) by becoming the first small molecule drug ",
                "sentiment": "positive",
                "score": 0.661,
            },
            {
                "text": "($GANX): March Update- Evidence of Disease Modification Keeps Getting Stronger",
                "sentiment": "positive",
                "score": 0.905,
            },
        ],
    },
    {
        "ticker": "IBRX",
        "mentions": 3,
        "avg_sentiment": 0.245,
        "final_score": 0.406,
        "top_contexts": [
            {
                "text": "$AAOI and $IBRX are the only ones i'm tracking. I think each will 3 X by EOY",
                "sentiment": "neutral",
                "score": 0.016,
            },
            {
                "text": "WATCHLIST AND SET UPS FOR THIS COMING WEEK (HUGE LIST)",
                "sentiment": "neutral",
                "score": -0.012,
            },
            {
                "text": "$IBRX - held 8.57 nicely, needs a strong close above $8.85 and the it has room for $9+ (key break at",
                "sentiment": "positive",
                "score": 0.734,
            },
        ],
    },
    {
        "ticker": "MBAI",
        "mentions": 3,
        "avg_sentiment": 0.257,
        "final_score": 0.382,
        "top_contexts": [
            {
                "text": "$MBAI looking good for tomorrow and a swing into the merger",
                "sentiment": "positive",
                "score": 0.836,
            },
            {
                "text": "This stock could go big soon - news expected any day",
                "sentiment": "neutral",
                "score": 0.044,
            },
            {
                "text": "This stock could explode soon - massive news expected soon",
                "sentiment": "neutral",
                "score": -0.216,
            },
        ],
    },
    {
        "ticker": "GBR",
        "mentions": 4,
        "avg_sentiment": 0.182,
        "final_score": 0.344,
        "top_contexts": [
            {
                "text": "WATCHLIST AND SET UPS FOR THIS COMING WEEK (HUGE LIST)",
                "sentiment": "neutral",
                "score": -0.012,
            },
            {
                "text": "$IBRX - held 8.57 nicely, needs a strong close above $8.85 and the it has room for $9+ (key break at",
                "sentiment": "positive",
                "score": 0.734,
            },
            {
                "text": "WATCHLIST AT MARKET OPEN WITH SET UPS",
                "sentiment": "neutral",
                "score": 0.02,
            },
        ],
    },
    {
        "ticker": "EONR",
        "mentions": 8,
        "avg_sentiment": 0.126,
        "final_score": 0.291,
        "top_contexts": [
            {
                "text": "What rising oil prices means for $EONR",
                "sentiment": "neutral",
                "score": 0.026,
            },
            {
                "text": "$EONR. Heaving Insider Buying. Debt almost nil.",
                "sentiment": "negative",
                "score": -0.541,
            },
            {
                "text": "In the world of small-cap stocks accessible on the NYSE Amex (i.e., excluding OTC), there are crazy ",
                "sentiment": "neutral",
                "score": 0.045,
            },
        ],
    },
    {
        "ticker": "CTM",
        "mentions": 2,
        "avg_sentiment": 0.12,
        "final_score": 0.284,
        "top_contexts": [
            {
                "text": "Castellum, Inc. ($CTM) releases 2025 Annual Report",
                "sentiment": "neutral",
                "score": -0.014,
            },
            {
                "text": "$CTM - they’re currently on Phase 3. We’re growing stronger than ever. Do your DD and you’ll be fasc",
                "sentiment": "neutral",
                "score": 0.245,
            },
        ],
    },
    {
        "ticker": "LUNR",
        "mentions": 2,
        "avg_sentiment": 0.166,
        "final_score": 0.277,
        "top_contexts": [
            {
                "text": "WATCHLIST AND SET UPS FOR THIS COMING WEEK (HUGE LIST)",
                "sentiment": "neutral",
                "score": -0.012,
            },
            {
                "text": "$LUNR 17.43 is support so this needs to hold, if we get a close above $17.72, this has to break $18.",
                "sentiment": "positive",
                "score": 0.345,
            },
        ],
    },
    {
        "ticker": "BNAI",
        "mentions": 7,
        "avg_sentiment": 0.122,
        "final_score": 0.267,
        "top_contexts": [
            {
                "text": "WATCHLIST AND SET UPS FOR THIS COMING WEEK (HUGE LIST)",
                "sentiment": "neutral",
                "score": -0.012,
            },
            {
                "text": "$IBRX - held 8.57 nicely, needs a strong close above $8.85 and the it has room for $9+ (key break at",
                "sentiment": "positive",
                "score": 0.734,
            },
            {
                "text": "AH WATCHLIST WITH SET UPS, MESSAGE FOR SET UPS ON YOUR STOCKS TOO",
                "sentiment": "neutral",
                "score": 0.04,
            },
        ],
    },
    {
        "ticker": "AIFF",
        "mentions": 3,
        "avg_sentiment": 0.191,
        "final_score": 0.259,
        "top_contexts": [
            {
                "text": "$AIFF +64% — brain scan AI company announces 33x growth in scans + NVIDIA partnership",
                "sentiment": "positive",
                "score": 0.871,
            },
            {"text": "⚡MORNING WATCHLIST⚡", "sentiment": "neutral", "score": -0.034},
            {
                "text": "$AIFF +64% — brain scan AI company announces 33x growth in scans + NVIDIA partnership",
                "sentiment": "positive",
                "score": 0.871,
            },
        ],
    },
    {
        "ticker": "SOC",
        "mentions": 2,
        "avg_sentiment": 0.177,
        "final_score": 0.258,
        "top_contexts": [
            {
                "text": "AH WATCHLIST AND SET UPS",
                "sentiment": "neutral",
                "score": 0.079,
            },
            {
                "text": "$SOC , Sable Offshore Corp. - Up over 25% today",
                "sentiment": "positive",
                "score": 0.927,
            },
        ],
    },
]


def analyze_ticker_sentiment(all_posts):
    master = {}

    for post in all_posts:
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
                sentiment = analyze_sentiment(context)

                weighted_score = sentiment["score"] * engagement_weight

                master[ticker]["sentiment_scores"].append(weighted_score)
                master[ticker]["contexts"].append(
                    {
                        "text": context[:150],
                        "sentiment": sentiment["label"],
                        "score": sentiment["score"],
                    }
                )

    results = []
    for ticker, data in master.items():
        if data["mentions"] < 1:
            continue

        avg_sentiment = (
            sum(data["sentiment_scores"]) / len(data["sentiment_scores"])
            if data["sentiment_scores"]
            else 0
        )

        avg_post_score = (
            sum(data["post_scores"]) / len(data["post_scores"])
            if (data["post_scores"])
            else 0
        )

        final_score = (
            avg_sentiment * (1 + data["mentions"] * 0.1) * (1 + avg_post_score * 0.01)
        )

        results.append(
            {
                "ticker": ticker,
                "mentions": data["mentions"],
                "avg_sentiment": round(avg_sentiment, 3),
                "final_score": round(final_score, 3),
                "top_contexts": data["contexts"][:3],
            }
        )

    results.sort(key=lambda x: x["final_score"], reverse=True)
    results = [r for r in results if r["mentions"] >= 2]
    return results


if __name__ == "__main__":
    print("=== ThreadRadar ===\n")

    # print("Step 1: Fetching posts...")
    # posts = fetch_all()

    # print("\nStep 2: Analyzing tickers and sentiment...")
    # results = analyze_ticker_sentiment(posts)

    print("\nStep 3: Adding Stock prices from yahoo finance...")
    results = enrich_with_price(old_results[:10])

    print("\n=== TOP STOCK PICKS ===\n")

    with open("output.json", "w", encoding="utf-8") as file:
        json.dump(results, file, indent=2, ensure_ascii=False)

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
