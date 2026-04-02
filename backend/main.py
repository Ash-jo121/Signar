import json
import math
import re
import time
from constants.exclusion import LOW_QUALITY_PATTERNS
from integrations.google_sheets_integration import update_spreadsheet
from integrations.yahooFn import enrich_with_price
from database import init_db, record_flagged_stocks
from database import save_daily_results
from scraper import fetch_all
from extractor import extract_from_post
from sentiment import analyze_sentiment, assess_catalyst_quality, _request_times
from tqdm import tqdm
import traceback


def has_diverse_contexts(contexts, min_unique_patterns=3):
    patterns = set(c["full"][:30] for c in contexts)
    return len(patterns) >= min_unique_patterns


def is_valid_context(text: str) -> bool:
    cleaned = re.sub(r"http\S+", "", text).strip()

    if len(cleaned) < 30:
        return False

    alpha_chars = sum(1 for c in cleaned if c.isalpha())
    if alpha_chars < 20:
        return False

    for pattern in LOW_QUALITY_PATTERNS:
        if re.search(pattern, cleaned, re.IGNORECASE):
            return False

    return True


def clean_context(text: str) -> str:
    text = re.sub(r"http\S+|www\S+", "", text)
    text = re.sub(r"https://preview\.redd\.it\S+", "", text)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = re.sub(r"\n+", " ", text).strip()
    return text


def sample_contexts(contexts, ticker, max_contexts=15):
    if len(contexts) <= max_contexts:
        return contexts

    seen = set()
    deduped = []
    for c in contexts:
        key = re.sub(r"[$\s]", "", c[:80]).lower()
        if key not in seen:
            seen.add(key)
            deduped.append(c)

    direct = [c for c in deduped if ticker.upper() in c.upper()]
    others = [c for c in deduped if c not in direct]
    sorted_others = sorted(others, key=len, reverse=True)
    selected = direct[:10] + sorted_others[: max(0, max_contexts - len(direct[:10]))]
    return selected[:max_contexts]


def apply_mod_penalty(result):
    """
    Apply score penalty based on mod intervention type and upvote score.
    Returns adjusted final_score and logs the intervention.
    """
    if not result.get("mod_flagged"):
        return result["final_score"]

    flag_type = result.get("mod_flag_type")
    flag_score = result.get("mod_flag_score", 0)
    ticker = result["ticker"]
    original = result["final_score"]

    if flag_type == "mod_acting":
        multiplier = 0.2
        print(f"  {ticker}: MOD INTERVENTION detected → score {original:.3f} × 0.2")
    elif flag_type == "community_call":
        # Higher upvotes on the warning = stronger penalty
        if flag_score > 20:
            multiplier = 0.3
        elif flag_score > 10:
            multiplier = 0.4
        else:
            multiplier = 0.5
        print(
            f"  {ticker}: community pump warning (upvotes={flag_score}) "
            f"→ score {original:.3f} × {multiplier}"
        )
    else:
        return original

    return round(original * multiplier, 3)


def analyze_ticker_sentiment(all_posts):
    master = {}
    groq_calls = 0
    finbert_calls = 0

    seen_context_keys = set()

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
                    "mod_flagged": False,
                    "mod_flag_type": None,
                    "mod_flag_score": 0,
                }

            master[ticker]["mentions"] += data["mentions"]
            master[ticker]["post_scores"].append(post["score"])

            # Propagate mod flags — upgrade if stronger signal
            if data.get("mod_flagged"):
                existing_type = master[ticker]["mod_flag_type"]
                incoming_type = data["mod_flag_type"]
                incoming_score = data["mod_flag_score"]

                if (
                    not master[ticker]["mod_flagged"]
                    or (
                        existing_type == "community_call"
                        and incoming_type == "mod_acting"
                    )
                    or incoming_score > master[ticker]["mod_flag_score"]
                ):
                    master[ticker]["mod_flagged"] = True
                    master[ticker]["mod_flag_type"] = incoming_type
                    master[ticker]["mod_flag_score"] = incoming_score

            for context in data["contexts"]:
                if is_valid_context(context["text"]):
                    cleaned = clean_context(context["text"])

                    context_key = re.sub(r"[$\s]", "", cleaned[:80]).lower()
                    if context_key in seen_context_keys:
                        continue
                    seen_context_keys.add(context_key)

                    master[ticker]["contexts"].append(
                        {
                            "full": cleaned[:500],
                            "short": cleaned[:300],
                            "score": context["score"],
                            "source": context["source"],
                        }
                    )

            tc = data.get("top_comment")
            if tc:
                existing = master[ticker]["top_comment"]
                if existing is None or tc["score"] > existing["score"]:
                    master[ticker]["top_comment"] = tc

    total_contexts = sum(
        min(len(data["contexts"]), 15)
        for data in master.values()
        if has_diverse_contexts(data["contexts"])
    )

    print(f"\nPass 2: Analyzing sentiment for {len(master)} tickers...")
    print(f"Total contexts to analyze: {total_contexts}")

    results = []

    with tqdm(total=total_contexts, desc="Analyzing", unit="context") as pbar:
        for ticker, data in master.items():
            try:
                all_ctx_count = len(data["contexts"])
                if not has_diverse_contexts(data["contexts"]):
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

            top_comment = data.get("top_comment")
            if top_comment and avg_post > 0.3 and top_comment["score"] > 20:
                tc_sentiment = analyze_sentiment(top_comment["text"])
                groq_calls += 1 if tc_sentiment["source"] == "groq" else 0
                finbert_calls += 1 if tc_sentiment["source"] == "finbert" else 0
                if tc_sentiment["score"] < -0.3:
                    print(
                        f"  {ticker}: contrarian signal detected "
                        f"(top comment score={top_comment['score']}, "
                        f"sentiment={tc_sentiment['score']:.2f})"
                    )
                    avg_sentiment = max(-1.0, avg_sentiment - 0.5)

            post_count = sum(1 for c in data["contexts"] if c["source"] == "post")
            comment_count = sum(1 for c in data["contexts"] if c["source"] == "comment")

            if post_count + comment_count > 0:
                engagement_ratio = comment_count / (post_count + comment_count)
            else:
                engagement_ratio = 0

            engagement_multiplier = 0.4 + (0.6 * engagement_ratio)

            final_score = (
                avg_sentiment
                * (1 + math.log(1 + data["mentions"]) * 0.3)
                * engagement_multiplier
            )

            result = {
                "ticker": ticker,
                "mentions": round(data["mentions"], 1),
                "avg_sentiment": round(avg_sentiment, 3),
                "final_score": round(final_score, 3),
                "top_contexts": top_contexts[:7],
                "mod_flagged": data["mod_flagged"],
                "mod_flag_type": data["mod_flag_type"],
                "mod_flag_score": data["mod_flag_score"],
            }

            # Apply mod penalty immediately after score computation
            result["final_score"] = apply_mod_penalty(result)

            results.append(result)

    print(f"\nSentiment sources: FinBERT={finbert_calls}, Groq={groq_calls}")
    print(f"Groq API calls used: {groq_calls}/14400 daily limit")
    print(f"Groq API calls efficiency: {groq_calls / 14400 * 100:.2f}%")

    results.sort(key=lambda x: x["final_score"], reverse=True)
    return results


if __name__ == "__main__":
    print("=== ThreadRadar ===\n")

    init_db()

    print("Step 1: Fetching posts...")
    posts = fetch_all()

    print("\nStep 2: Analyzing tickers and sentiment...")
    results = analyze_ticker_sentiment(posts)

    print("\nStep 3: Adding Stock prices from yahoo finance...")
    results = enrich_with_price(results)

    trackable = [
        r
        for r in results
        if r.get("price", 0) > 0.05  # raised from 0.01
        and r.get("price", 0) <= 15
        and r["mentions"] >= 2
    ]

    print("\nStep 4: Saving results to database...")
    save_daily_results(trackable)
    record_flagged_stocks(trackable)

    results = [
        r
        for r in results
        if r.get("price", 0) > 0.05  # raised from 0.01
        and r.get("price", 0) <= 15
        and 0 < r.get("market_cap", 0) <= 500000000
        and r.get("float_shares", 0) <= 50000000
        and r["mentions"] >= 5
        and len(r["top_contexts"]) >= 3
    ]

    print("\nStep 5: Catalyst assessment for filtered results...")
    _request_times.clear()
    time.sleep(65)

    catalyst_calls = 0
    for result in results:
        context_texts = [ctx["text"] for ctx in result.get("top_contexts", [])]
        catalyst = assess_catalyst_quality(result["ticker"], context_texts)
        result["has_catalyst"] = catalyst["has_catalyst"]
        result["catalyst_type"] = catalyst["catalyst_type"]
        result["catalyst_confidence"] = catalyst["confidence"]
        catalyst_calls += 1
        print(
            f"  {result['ticker']}: has_catalyst={catalyst['has_catalyst']} "
            f"type={catalyst['catalyst_type']} "
            f"confidence={catalyst['confidence']} "
            f"| {catalyst['reasoning']}"
        )

    print(f"  Catalyst assessment: {catalyst_calls} Groq calls used")

    print("\nStep 6: Writing output to files...\n")

    with open("output.json", "w", encoding="utf-8") as file:
        json.dump(results[:10], file, indent=2, ensure_ascii=False)

    with open("output.txt", "w", encoding="utf-8") as file:
        for r in results[:10]:
            catalyst_str = (
                f"[CATALYST: {r.get('catalyst_type', 'none').upper()}]"
                if r.get("has_catalyst")
                else "[NO CATALYST]"
            )
            mod_str = (
                f"[MOD FLAG: {r.get('mod_flag_type', '').upper()}]"
                if r.get("mod_flagged")
                else ""
            )
            file.write(f"${r['ticker']} {catalyst_str} {mod_str}\n")
            file.write(
                f"  Mentions: {r['mentions']} | Sentiment: {r['avg_sentiment']:+.3f} "
                f"| Score: {r['final_score']:+.3f}\n"
            )
            file.write(
                f"  Context: {r['top_contexts'][0]['text'][:100] if r['top_contexts'] else 'N/A'}\n"
            )
            file.write("\n")

    print("\nStep 7: Updating Google Sheet...")
    try:
        update_spreadsheet(results)
    except Exception as e:
        print(f"Google Sheets update failed: {e}")
        print("output.json was already saved — data is not lost")
