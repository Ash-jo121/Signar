import json
import math
import re
import time
import os
from datetime import date
from constants.exclusion import LOW_QUALITY_PATTERNS
from integrations.google_sheets_integration import update_spreadsheet
from integrations.yahooFn import enrich_with_price
from database import (
    get_connection,
    init_db,
    record_flagged_stocks,
    save_score_metadata,
)
from database import save_daily_results
from scraper import fetch_all
from extractor import extract_from_post
from sentiment import (
    analyze_sentiment,
    assess_catalyst_quality,
    _request_times,
    deduplicate_similar_contexts,
)
from tqdm import tqdm
import traceback


CATALYST_MULTIPLIERS = {
    "none": 1.05,
    "merger": 1.08,
    "regulatory": 1.05,
    "clinical": 1.0,
    "fda": 0.9,
    "contract": 0.88,
    "capital raise": 0.75,
    "production": 0.95,
    "earnings": 0.98,
    "partnership": 0.95,
    "patent": 1.0,
    "short squeeze": 0.9,
    "sec filing": 0.95,
    "government contract": 0.92,
}

CATALYST_ALIASES = {
    "approval": "regulatory",
    "trial": "clinical",
    "clinical trial": "clinical",
    "contract/partnership": "partnership",
    "licensing": "contract",
    "offering": "capital raise",
    "atm": "capital raise",
    "dilution": "capital raise",
    "product launch": "production",
}

CATALYST_CONFIDENCE_BLEND = 0.7

SUBREDDIT_MULTIPLIERS = {
    "pennystocks": 1.0,
    "pennystock": 1.0,
    "smallstreetbets": 0.98,
    "robinhoodpennystocks": 0.95,
    "10xpennystocks": 0.95,
    "shortsqueeze": 0.9,
    "squeezeplays": 0.92,
    "wallstreetbets": 0.94,
    "stocks": 1.03,
    "investing": 1.05,
}

PROMOTION_RISK_PATTERNS = [
    r"\bmo+on\b",
    r"\b10x\b",
    r"\b100x\b",
    r"\bloaded\b",
    r"\bdon'?t miss\b",
    r"\beasy money\b",
    r"\bsqueeze is real\b",
    r"\bgoing parabolic\b",
    r"\bnext runner\b",
    r"\bready to explode\b",
    r"\blotto\b",
    r"\blottery ticket\b",
    r"\bsend it\b",
]

UNREALISTIC_TARGET_PATTERNS = [
    r"\bfrom\s+\$?\d+(?:\.\d+)?\s+to\s+\$?\d+(?:\.\d+)?\b",
    r"\b\d{3,}%\s+upside\b",
    r"\bguaranteed\b",
]


def clamp(value, minimum, maximum):
    return min(max(value, minimum), maximum)


def normalize_catalyst_type(catalyst_type):
    normalized = (catalyst_type or "none").strip().lower()
    return CATALYST_ALIASES.get(normalized, normalized)


def get_catalyst_multiplier(catalyst_type, confidence=1.0):
    normalized = normalize_catalyst_type(catalyst_type)
    raw_multiplier = CATALYST_MULTIPLIERS.get(normalized, 0.95)
    confidence = clamp(confidence or 0, 0, 1)
    blended_confidence = CATALYST_CONFIDENCE_BLEND + (
        (1 - CATALYST_CONFIDENCE_BLEND) * confidence
    )
    return 1.0 + ((raw_multiplier - 1.0) * blended_confidence)


def calculate_cross_subreddit_multiplier(subreddit_count):
    return {1: 1.0, 2: 1.1, 3: 1.18, 4: 1.25}.get(
        min(max(subreddit_count, 1), 4), 1.25
    )


def calculate_subreddit_multiplier(subreddit_mentions):
    """Weight ticker mentions by the historical signal quality of each subreddit."""
    if not subreddit_mentions:
        return 1.0

    positive_mentions = {
        subreddit: mentions
        for subreddit, mentions in subreddit_mentions.items()
        if mentions > 0
    }
    total_mentions = sum(positive_mentions.values())
    if total_mentions == 0:
        return 1.0

    weighted_total = 0
    for subreddit, mentions in positive_mentions.items():
        multiplier = SUBREDDIT_MULTIPLIERS.get(str(subreddit).lower(), 1.0)
        weighted_total += multiplier * mentions

    return weighted_total / total_mentions


def calculate_mention_density_multiplier(mentions, context_count):
    """Reward tickers that are repeatedly discussed inside their sampled contexts."""
    if context_count <= 0:
        return 1.0

    density = mentions / context_count
    if density < 0.5:
        return 0.9
    if density < 1.0:
        return 1.0
    if density < 1.5:
        return 1.08
    if density < 2.5:
        return 1.15
    return 1.2


def calculate_mention_sweet_spot_multiplier(mentions):
    """
    Favor sustained interest over viral spikes.

    Backtests showed 10-20 mentions behaved better than very high mention counts,
    which often reflect Reddit arriving after the price move.
    """
    if mentions < 5:
        return 0.85
    if mentions < 10:
        return 1.0
    if mentions <= 20:
        return 1.18
    if mentions <= 35:
        return 0.95
    return 0.8


def calculate_sentiment_timing_multiplier(avg_sentiment):
    """Reward calm curiosity and penalize euphoric late-cycle excitement."""
    if avg_sentiment < -0.2:
        return 0.75
    if avg_sentiment < 0:
        return 0.95
    if avg_sentiment <= 0.2:
        return 1.15
    if avg_sentiment <= 0.4:
        return 1.0
    return 0.85


def calculate_engagement_multiplier(engagement_ratio):
    """Engagement is useful, but noisy, so keep it in a narrow band."""
    return 0.9 + (clamp(engagement_ratio, 0, 1) * 0.15)


def calculate_account_age_multiplier(author_scores):
    """Use account age when scraper metadata is available; stay neutral otherwise."""
    if not author_scores:
        return 1.0

    age_multipliers = []
    for item in author_scores:
        age_days = item.get("account_age_days")
        if age_days is None:
            continue
        if age_days < 30:
            age_multipliers.append(0.6)
        elif age_days < 90:
            age_multipliers.append(0.75)
        elif age_days < 365:
            age_multipliers.append(0.9)
        elif age_days < 365 * 3:
            age_multipliers.append(1.0)
        else:
            age_multipliers.append(1.05)

    if not age_multipliers:
        return 1.0

    return sum(age_multipliers) / len(age_multipliers)


def calculate_karma_multiplier(author_scores):
    """Small credibility nudge from known Reddit karma; neutral when unavailable."""
    known_karma = []
    for item in author_scores:
        link_karma = item.get("link_karma")
        comment_karma = item.get("comment_karma")
        if link_karma is None and comment_karma is None:
            continue
        known_karma.append(max(0, (link_karma or 0) + (comment_karma or 0)))

    if not known_karma:
        return 1.0

    avg_log_karma = sum(math.log10(karma + 1) for karma in known_karma) / len(
        known_karma
    )
    if avg_log_karma < 2:
        return 0.9
    if avg_log_karma < 3:
        return 0.97
    if avg_log_karma < 4:
        return 1.0
    return 1.03


def calculate_user_credibility_multiplier(author_scores):
    """
    Combine account-age and karma signals conservatively.

    Missing profile metadata is neutral. This avoids treating unavailable account
    data as a bearish signal and limits overfitting to one day's author mix.
    """
    if not author_scores:
        return {
            "account_age_multiplier": 1.0,
            "karma_multiplier": 1.0,
            "user_credibility_multiplier": 1.0,
        }

    known_authors = {
        item["author"]
        for item in author_scores
        if item.get("author") and item.get("author") not in {"unknown", "[deleted]"}
    }
    account_age_multiplier = calculate_account_age_multiplier(author_scores)
    karma_multiplier = calculate_karma_multiplier(author_scores)
    author_diversity_multiplier = min(1.05, 1.0 + (len(known_authors) * 0.005))
    user_credibility_multiplier = clamp(
        account_age_multiplier * karma_multiplier * author_diversity_multiplier,
        0.65,
        1.1,
    )

    return {
        "account_age_multiplier": account_age_multiplier,
        "karma_multiplier": karma_multiplier,
        "author_diversity_multiplier": author_diversity_multiplier,
        "user_credibility_multiplier": user_credibility_multiplier,
    }


def calculate_post_quality_multiplier(context_lengths):
    """Reward fuller ticker contexts and penalize very thin mentions."""
    if not context_lengths:
        return 1.0

    avg_length = sum(context_lengths) / len(context_lengths)
    if avg_length < 50:
        return 0.8
    if avg_length < 150:
        return 0.9
    if avg_length < 300:
        return 1.0
    return 1.05


def calculate_author_concentration(contexts):
    authors = [
        context.get("author") or "unknown"
        for context in contexts
        if context.get("author") not in {None, ""}
    ]
    total_mentions = len(contexts)
    if not authors or total_mentions == 0:
        return {
            "unique_authors": 0,
            "top_author_mentions": 0,
            "top_author_share": 0.0,
            "author_concentration_multiplier": 1.0,
        }

    count_by_author = {}
    for author in authors:
        count_by_author[author] = count_by_author.get(author, 0) + 1

    unique_authors = len(count_by_author)
    top_author_mentions = max(count_by_author.values())
    top_author_share = top_author_mentions / total_mentions

    if top_author_share >= 0.60:
        multiplier = 0.70
    elif top_author_share >= 0.40:
        multiplier = 0.85
    elif unique_authors <= 2 and total_mentions >= 5:
        multiplier = 0.80
    else:
        multiplier = 1.0

    return {
        "unique_authors": unique_authors,
        "top_author_mentions": top_author_mentions,
        "top_author_share": top_author_share,
        "author_concentration_multiplier": multiplier,
    }


def calculate_promotion_risk(contexts):
    total_contexts = len(contexts)
    if total_contexts == 0:
        return {
            "promotion_risk_score": 0.0,
            "promotion_terms_count": 0,
            "unrealistic_target_count": 0,
        }

    promotion_hits = 0
    unrealistic_hits = 0
    for context in contexts:
        text = context.get("text") or context.get("full") or context.get("short", "")
        for pattern in PROMOTION_RISK_PATTERNS:
            promotion_hits += len(re.findall(pattern, text, re.IGNORECASE))
        for pattern in UNREALISTIC_TARGET_PATTERNS:
            unrealistic_hits += len(re.findall(pattern, text, re.IGNORECASE))

    risk_score = min(1.0, (promotion_hits + unrealistic_hits) / total_contexts)
    return {
        "promotion_risk_score": risk_score,
        "promotion_terms_count": promotion_hits,
        "unrealistic_target_count": unrealistic_hits,
    }


def calculate_signal_multipliers(data, engagement_ratio, avg_sentiment):
    """
    Group signals by reliability before multiplying.

    High-quality social conviction gets the most room. Medium-quality credibility,
    subreddit, and post-quality signals are kept in tighter bands so they can
    refine rankings without drowning out sentiment or catalysts.
    """
    subreddit_mentions = data.get("subreddit_mentions", {})
    subreddit_count = len(
        [mentions for mentions in subreddit_mentions.values() if mentions > 0]
    )
    context_count = len(data.get("contexts", []))
    mentions = data.get("mentions", 0)
    cross_subreddit_multiplier = calculate_cross_subreddit_multiplier(subreddit_count)
    mention_density_multiplier = calculate_mention_density_multiplier(
        mentions, context_count
    )
    mention_sweet_spot_multiplier = calculate_mention_sweet_spot_multiplier(mentions)
    sentiment_timing_multiplier = calculate_sentiment_timing_multiplier(avg_sentiment)
    engagement_multiplier = calculate_engagement_multiplier(engagement_ratio)
    subreddit_multiplier = calculate_subreddit_multiplier(subreddit_mentions)
    credibility = calculate_user_credibility_multiplier(data.get("author_scores", []))
    post_quality_multiplier = calculate_post_quality_multiplier(
        data.get("context_lengths", [])
    )
    author_concentration = calculate_author_concentration(data.get("contexts", []))
    social_conviction_multiplier = clamp(
        cross_subreddit_multiplier
        * mention_density_multiplier
        * mention_sweet_spot_multiplier
        * engagement_multiplier,
        0.8,
        1.45,
    )
    evidence_quality_multiplier = post_quality_multiplier
    timing_multiplier = sentiment_timing_multiplier
    pre_catalyst_signal_multiplier = clamp(
        social_conviction_multiplier
        * timing_multiplier
        * evidence_quality_multiplier
        * credibility["user_credibility_multiplier"]
        * author_concentration["author_concentration_multiplier"]
        * subreddit_multiplier,
        0.5,
        1.65,
    )

    return {
        "social_conviction_multiplier": social_conviction_multiplier,
        "credibility_multiplier": credibility["user_credibility_multiplier"],
        "evidence_quality_multiplier": evidence_quality_multiplier,
        "timing_multiplier": timing_multiplier,
        "pre_catalyst_signal_multiplier": pre_catalyst_signal_multiplier,
        "cross_subreddit_multiplier": cross_subreddit_multiplier,
        "ticker_mention_density_multiplier": mention_density_multiplier,
        "mention_sweet_spot_multiplier": mention_sweet_spot_multiplier,
        "sentiment_timing_multiplier": sentiment_timing_multiplier,
        "engagement_multiplier": engagement_multiplier,
        "subreddit_multiplier": subreddit_multiplier,
        "user_credibility_multiplier": credibility["user_credibility_multiplier"],
        "account_age_multiplier": credibility["account_age_multiplier"],
        "karma_multiplier": credibility["karma_multiplier"],
        "author_diversity_multiplier": credibility.get(
            "author_diversity_multiplier", 1.0
        ),
        "author_concentration_multiplier": author_concentration[
            "author_concentration_multiplier"
        ],
        "unique_authors": author_concentration["unique_authors"],
        "top_author_mentions": author_concentration["top_author_mentions"],
        "top_author_share": author_concentration["top_author_share"],
        "post_quality_multiplier": post_quality_multiplier,
        "subreddits_mentioning_ticker": subreddit_count,
    }


def calculate_risk_score(result):
    """Estimate how dangerous/chase-like the setup is on a 0-100 scale."""
    change_percent = result.get("change_percent", 0) or 0
    mentions = result.get("mentions", 0) or 0
    avg_sentiment = result.get("avg_sentiment", 0) or 0
    catalyst_type = normalize_catalyst_type(result.get("catalyst_type", "none"))
    days_seen = result.get("persistence_days_seen", 1) or 1

    if change_percent > 30:
        chase_risk = 1.0
    elif change_percent > 20:
        chase_risk = 0.75
    elif change_percent > 10:
        chase_risk = 0.45
    elif change_percent > 5:
        chase_risk = 0.25
    else:
        chase_risk = 0.05

    if mentions > 35:
        mention_risk = 0.5
    elif mentions > 20:
        mention_risk = 0.3
    elif mentions >= 10:
        mention_risk = 0.1
    else:
        mention_risk = 0.05

    if avg_sentiment > 0.55:
        sentiment_risk = 0.5
    elif avg_sentiment > 0.35:
        sentiment_risk = 0.3
    elif avg_sentiment > 0.2:
        sentiment_risk = 0.15
    else:
        sentiment_risk = 0.05

    catalyst_risk_map = {
        "capital raise": 0.75,
        "fda": 0.45,
        "contract": 0.4,
        "short squeeze": 0.6,
        "government contract": 0.35,
        "production": 0.25,
        "partnership": 0.2,
        "earnings": 0.25,
        "merger": 0.2,
        "regulatory": 0.18,
        "none": 0.1,
    }
    catalyst_risk = catalyst_risk_map.get(catalyst_type, 0.25)

    if days_seen > 7:
        persistence_risk = 0.45
    elif days_seen > 4:
        persistence_risk = 0.25
    else:
        persistence_risk = 0.05

    flag_risk = 0
    if result.get("vampire_flagged"):
        flag_risk = max(flag_risk, 1.0)
    if result.get("mod_flagged"):
        flag_risk = max(flag_risk, 0.65)
    if result.get("stale_repetition_multiplier", 1.0) < 1.0:
        flag_risk = max(flag_risk, 0.35)

    promotion_risk = result.get("promotion_risk_score", 0) or 0
    velocity_risk = 0.35 if result.get("mention_velocity_label") == "stale" else 0
    volume_risk = (
        0.25
        if result.get("relative_volume") is not None
        and result.get("relative_volume") < 0.8
        else 0
    )
    concentration_risk = 0
    if result.get("top_author_share", 0) >= 0.6:
        concentration_risk = 0.7
    elif result.get("top_author_share", 0) >= 0.4:
        concentration_risk = 0.4
    elif (
        result.get("unique_authors", 0) <= 2
        and len(result.get("top_contexts", [])) >= 5
    ):
        concentration_risk = 0.45

    risk = (
        chase_risk * 30
        + mention_risk * 15
        + sentiment_risk * 15
        + catalyst_risk * 15
        + persistence_risk * 10
        + flag_risk * 25
        + promotion_risk * 25
        + velocity_risk * 10
        + volume_risk * 10
        + concentration_risk * 15
    )
    return round(clamp(risk, 0, 100), 1)


def risk_level(risk_score):
    if risk_score >= 70:
        return "extreme"
    if risk_score >= 45:
        return "high"
    if risk_score >= 25:
        return "medium"
    return "low"


def calculate_radar_score(result):
    """
    Score unusual Reddit attention, independent of whether the setup is tradable.

    This intentionally ignores price-action risk, promotion risk, and catalyst
    danger. A ticker can have a high radar score while still having a low trade
    score if the discussion looks crowded, promotional, or late.
    """
    mentions = result.get("mentions", 0) or 0
    return (
        math.log1p(max(mentions, 0))
        * result.get("social_conviction_multiplier", 1.0)
        * result.get("subreddit_multiplier", 1.0)
    )


def calculate_volume_confirmation_multiplier(relative_volume, price_change_1d):
    if relative_volume is None:
        return 1.0
    if relative_volume >= 3 and (price_change_1d or 0) < 20:
        return 1.10
    if relative_volume < 0.8:
        return 0.85
    return 1.0


def pct_change(current, previous):
    if current is None or previous is None or previous <= 0:
        return None
    return ((current - previous) / previous) * 100


def classify_setup(result):
    risk = result.get("risk_score", 0) or 0
    promotion_risk = result.get("promotion_risk_score", 0) or 0
    top_author_share = result.get("top_author_share", 0) or 0
    catalyst_type = normalize_catalyst_type(result.get("catalyst_type", "none"))
    change_percent = result.get("change_percent", 0) or 0
    avg_sentiment = result.get("avg_sentiment", 0) or 0
    mentions = result.get("mentions", 0) or 0
    days_since_first_seen = result.get("days_since_first_seen", 0) or 0
    days_trending = result.get("days_trending", 1) or 1
    mention_velocity = result.get("mention_velocity_label")
    post_quality = result.get("post_quality_multiplier", 1.0) or 1.0
    trade_score = result.get("trade_score", result.get("final_score", 0)) or 0

    if catalyst_type == "capital raise":
        return "dilution_risk"
    if result.get("vampire_flagged") or result.get("mod_flagged"):
        return "promotion_risk"
    if promotion_risk >= 0.55 and (top_author_share >= 0.4 or risk >= 45):
        return "promotion_risk"
    if promotion_risk >= 0.35 and post_quality < 0.95:
        return "low_quality_hype"
    if change_percent > 15 or result.get("anti_chase_multiplier", 1.0) < 1.0:
        return "anti_chase"
    if mention_velocity == "emerging" and risk < 45:
        return "early_discovery"
    if change_percent < -5 and days_since_first_seen <= 3 and mentions >= 5:
        return "post_spike_pullback"
    if mention_velocity == "stale" or (days_trending >= 6 and mentions >= 10):
        return "stale_squeeze"
    if days_trending >= 4 and avg_sentiment < 0:
        return "bagholder_chatter"
    if days_since_first_seen == 0 and 5 <= mentions <= 20 and risk < 45:
        return "early_discovery"
    if trade_score > 0 and risk < 35 and 5 <= mentions <= 20:
        return "clean_momentum"
    if promotion_risk > 0:
        return "low_quality_hype"
    return "early_discovery" if days_since_first_seen <= 2 else "clean_momentum"


def apply_rank_scores(result):
    """
    Split the blended score into discovery, tradability, and risk views.

    final_score remains as a backward-compatible alias for trade_score.
    """
    if "signal_score" not in result:
        result["signal_score"] = round(result.get("final_score", 0), 3)

    radar_score = calculate_radar_score(result)
    risk = calculate_risk_score(result)
    signal_score = result.get("signal_score", result.get("final_score", 0)) or 0
    risk_dampener = risk / 100 * 0.4
    promotion_risk = result.get("promotion_risk_score", 0) or 0
    promotion_trade_multiplier = 0.75 if promotion_risk > 0.5 else 1.0
    volume_confirmation_multiplier = result.get("volume_confirmation_multiplier", 1.0)

    if signal_score >= 0:
        trade_score = signal_score * (1 - risk_dampener)
    else:
        trade_score = signal_score * (1 + risk_dampener)
    trade_score *= promotion_trade_multiplier * volume_confirmation_multiplier

    result["radar_score"] = round(radar_score, 3)
    result["trade_score"] = round(trade_score, 3)
    result["risk_score"] = risk
    result["risk_level"] = risk_level(risk)
    result["promotion_trade_multiplier"] = promotion_trade_multiplier
    result["setup_type"] = classify_setup(result)
    result["final_score"] = result["trade_score"]


def apply_catalyst_multiplier(result):
    catalyst_multiplier = get_catalyst_multiplier(
        result.get("catalyst_type", "none"),
        result.get("catalyst_confidence", 1.0),
    )
    result["catalyst_multiplier"] = round(catalyst_multiplier, 3)
    score_field = "signal_score" if "signal_score" in result else "final_score"
    original = result[score_field]
    result[score_field] = round(original * catalyst_multiplier, 3)
    result["combined_signal_multiplier"] = round(
        result.get("combined_signal_multiplier", 1.0) * catalyst_multiplier, 3
    )
    apply_rank_scores(result)

    if catalyst_multiplier != 1.0:
        print(
            f"  {result['ticker']}: catalyst multiplier "
            f"({result.get('catalyst_type', 'none')}) "
            f"{original:.3f} x {catalyst_multiplier:.2f} = "
            f"{result[score_field]:.3f} signal / {result['trade_score']:.3f} trade"
        )


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


def apply_anti_chase_penalty(result):
    """
    Penalize stocks that already made a large same-day move.

    This turns price action into a timing signal: strong Reddit attention after
    a large move is more likely late-cycle excitement than early discovery.
    """
    change_percent = result.get("change_percent", 0) or 0
    if change_percent > 30:
        multiplier = 0.65
    elif change_percent > 15:
        multiplier = 0.80
    elif change_percent > 5:
        multiplier = 0.95
    else:
        multiplier = 1.0

    result["price_change_1d"] = change_percent
    result["anti_chase_multiplier"] = multiplier
    if multiplier != 1.0:
        original = result["final_score"]
        result["final_score"] = round(original * multiplier, 3)
        result["combined_signal_multiplier"] = round(
            result.get("combined_signal_multiplier", 1.0) * multiplier,
            3,
        )
        print(
            f"  {result['ticker']}: anti-chase penalty "
            f"({change_percent:+.1f}% same-day) -> score {original} x {multiplier:.2f}"
        )


def apply_price_volume_confirmation(result):
    price_change_1d = result.get("price_change_1d", result.get("change_percent"))
    result["price_change_1d"] = price_change_1d
    multiplier = calculate_volume_confirmation_multiplier(
        result.get("relative_volume"),
        price_change_1d,
    )
    result["volume_confirmation_multiplier"] = round(multiplier, 3)


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
                    "subreddit_mentions": {},
                    "author_scores": [],
                    "context_lengths": [],
                }

            master[ticker]["mentions"] += data["mentions"]
            master[ticker]["post_scores"].append(post["score"])
            for subreddit, mentions in data.get("subreddit_mentions", {}).items():
                master[ticker]["subreddit_mentions"][subreddit] = (
                    master[ticker]["subreddit_mentions"].get(subreddit, 0) + mentions
                )
            master[ticker]["author_scores"].extend(data.get("author_scores", []))
            master[ticker]["context_lengths"].extend(data.get("context_lengths", []))

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
                            "subreddit": context.get(
                                "subreddit", post.get("subreddit", "unknown")
                            ),
                            "author": context.get("author", "unknown"),
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
                unique_contexts = deduplicate_similar_contexts(
                    unique_contexts, threshold=0.6
                )
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
                short_to_subreddit = {}
                short_to_author = {}

                for c in data["contexts"]:
                    short_to_full[c["short"]] = c["full"]
                    short_to_score[c["short"]] = c["score"]
                    short_to_source[c["short"]] = c["source"]
                    short_to_subreddit[c["short"]] = c.get("subreddit", "unknown")
                    short_to_author[c["short"]] = c.get("author", "unknown")

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
                            "source": source,
                            "subreddit": short_to_subreddit.get(
                                context_short, "unknown"
                            ),
                            "author": short_to_author.get(context_short, "unknown"),
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

            final_score = (
                avg_sentiment
                * (1 + math.log(1 + data["mentions"]) * 0.1)
            )
            base_final_score = final_score
            signal_multipliers = calculate_signal_multipliers(
                data, engagement_ratio, avg_sentiment
            )
            promotion_risk = calculate_promotion_risk(data["contexts"])
            combined_signal_multiplier = signal_multipliers[
                "pre_catalyst_signal_multiplier"
            ]
            final_score *= combined_signal_multiplier

            result = {
                "ticker": ticker,
                "mentions": round(data["mentions"], 1),
                "avg_sentiment": round(avg_sentiment, 3),
                "final_score": round(final_score, 3),
                "base_final_score": round(base_final_score, 3),
                "top_contexts": top_contexts[:7],
                "mod_flagged": data["mod_flagged"],
                "mod_flag_type": data["mod_flag_type"],
                "mod_flag_score": data["mod_flag_score"],
                "engagement_ratio": round(engagement_ratio, 3),
                "cross_subreddit_multiplier": round(
                    signal_multipliers["cross_subreddit_multiplier"], 3
                ),
                "subreddit_multiplier": round(
                    signal_multipliers["subreddit_multiplier"], 3
                ),
                "user_credibility_multiplier": round(
                    signal_multipliers["user_credibility_multiplier"], 3
                ),
                "post_quality_multiplier": round(
                    signal_multipliers["post_quality_multiplier"], 3
                ),
                "catalyst_multiplier": 1.0,
                "social_conviction_multiplier": round(
                    signal_multipliers["social_conviction_multiplier"], 3
                ),
                "credibility_multiplier": round(
                    signal_multipliers["credibility_multiplier"], 3
                ),
                "evidence_quality_multiplier": round(
                    signal_multipliers["evidence_quality_multiplier"], 3
                ),
                "timing_multiplier": round(signal_multipliers["timing_multiplier"], 3),
                "ticker_mention_density_multiplier": round(
                    signal_multipliers["ticker_mention_density_multiplier"], 3
                ),
                "mention_sweet_spot_multiplier": round(
                    signal_multipliers["mention_sweet_spot_multiplier"], 3
                ),
                "sentiment_timing_multiplier": round(
                    signal_multipliers["sentiment_timing_multiplier"], 3
                ),
                "engagement_multiplier": round(
                    signal_multipliers["engagement_multiplier"], 3
                ),
                "account_age_multiplier": round(
                    signal_multipliers["account_age_multiplier"], 3
                ),
                "karma_multiplier": round(signal_multipliers["karma_multiplier"], 3),
                "author_diversity_multiplier": round(
                    signal_multipliers["author_diversity_multiplier"], 3
                ),
                "author_concentration_multiplier": round(
                    signal_multipliers["author_concentration_multiplier"], 3
                ),
                "unique_authors": signal_multipliers["unique_authors"],
                "top_author_mentions": signal_multipliers["top_author_mentions"],
                "top_author_share": round(signal_multipliers["top_author_share"], 3),
                "promotion_risk_score": round(
                    promotion_risk["promotion_risk_score"], 3
                ),
                "promotion_terms_count": promotion_risk["promotion_terms_count"],
                "unrealistic_target_count": promotion_risk[
                    "unrealistic_target_count"
                ],
                "combined_signal_multiplier": round(combined_signal_multiplier, 3),
                "subreddits_mentioning_ticker": signal_multipliers[
                    "subreddits_mentioning_ticker"
                ],
                "subreddit_mentions": data.get("subreddit_mentions", {}),
            }

            # Apply mod penalty immediately after score computation
            result["final_score"] = apply_mod_penalty(result)

            results.append(result)

    print(f"\nSentiment sources: FinBERT={finbert_calls}, Groq={groq_calls}")
    print(f"Groq API calls used: {groq_calls}/14400 daily limit")
    print(f"Groq API calls efficiency: {groq_calls / 14400 * 100:.2f}%")

    results.sort(key=lambda x: x["final_score"], reverse=True)
    return results


def apply_repetition_decay(results):
    """
    Reward early persistence and penalize stale repetition.

    Backtests suggest 2-4 appearances can indicate early-cycle sustained interest,
    while longer streaks are more likely to be crowded or late.
    """
    conn = get_connection()
    today_date = date.today()
    today_iso = today_date.strftime("%Y-%m-%d")
    for result in results:
        ticker = result["ticker"]
        mentions_today = result.get("mentions", 0) or 0

        historical_rows = conn.execute(
            """
            SELECT date, mentions, price, volume
            FROM daily_sentiment
            WHERE ticker = ?
            ORDER BY date ASC
            """,
            (ticker,),
        ).fetchall()

        previous_day_mentions = None
        if historical_rows:
            first_seen_date = historical_rows[0]["date"]
            previous_day_mentions = historical_rows[-1]["mentions"]
            try:
                days_since_first_seen = (
                    today_date - date.fromisoformat(first_seen_date)
                ).days
            except ValueError:
                days_since_first_seen = 0
        else:
            first_seen_date = today_iso
            days_since_first_seen = 0

        days_trending = len({row["date"] for row in historical_rows}) + 1
        if days_since_first_seen == 0:
            earlyness_multiplier = 1.15
        elif days_since_first_seen <= 2:
            earlyness_multiplier = 1.0
        elif days_since_first_seen <= 5:
            earlyness_multiplier = 0.85
        else:
            earlyness_multiplier = 0.70

        if previous_day_mentions and previous_day_mentions > 0:
            mention_change_pct = (
                (result.get("mentions", 0) - previous_day_mentions)
                / previous_day_mentions
                * 100
            )
        else:
            mention_change_pct = None

        recent_mentions = [
            row["mentions"]
            for row in historical_rows[-3:]
            if row["mentions"] is not None
        ]
        mentions_3d_avg = (
            sum(recent_mentions) / len(recent_mentions) if recent_mentions else 0
        )
        mention_acceleration = mentions_today / max(mentions_3d_avg, 1)
        if mentions_today >= 5 and mention_acceleration >= 2:
            mention_velocity_label = "emerging"
        elif (
            len(recent_mentions) >= 2
            and mentions_today < recent_mentions[-1] < recent_mentions[-2]
        ):
            mention_velocity_label = "stale"
        else:
            mention_velocity_label = "steady"

        current_price = result.get("price")
        historical_prices = [
            row["price"] for row in historical_rows if row["price"] and row["price"] > 0
        ]
        price_change_3d = (
            pct_change(current_price, historical_prices[-3])
            if len(historical_prices) >= 3
            else None
        )
        price_change_7d = (
            pct_change(current_price, historical_prices[-7])
            if len(historical_prices) >= 7
            else None
        )
        price_change_1d = result.get("price_change_1d", result.get("change_percent"))
        volume_confirmation_multiplier = calculate_volume_confirmation_multiplier(
            result.get("relative_volume"),
            price_change_1d,
        )

        result["first_seen_date"] = first_seen_date
        result["first_seen_datetime"] = f"{first_seen_date}T00:00:00"
        result["days_since_first_seen"] = max(days_since_first_seen, 0)
        result["days_trending"] = days_trending
        result["mentions_today"] = round(mentions_today, 3)
        result["mentions_yesterday"] = previous_day_mentions
        result["mentions_3d_avg"] = round(mentions_3d_avg, 3)
        result["mention_acceleration"] = round(mention_acceleration, 3)
        result["mention_velocity_label"] = mention_velocity_label
        result["mention_declining_2d"] = mention_velocity_label == "stale"
        result["previous_day_mentions"] = previous_day_mentions
        result["mention_change_pct"] = (
            round(mention_change_pct, 2) if mention_change_pct is not None else None
        )
        result["earlyness_multiplier"] = earlyness_multiplier
        result["price_change_1d"] = price_change_1d
        result["price_change_3d"] = (
            round(price_change_3d, 2) if price_change_3d is not None else None
        )
        result["price_change_7d"] = (
            round(price_change_7d, 2) if price_change_7d is not None else None
        )
        result["volume_confirmation_multiplier"] = round(
            volume_confirmation_multiplier, 3
        )

        # Check consecutive appearances in last 7 days
        rows = conn.execute(
            """
            SELECT date, final_score, price
            FROM daily_sentiment
            WHERE ticker = ?
            AND date >= date('now', '-7 days')
            ORDER BY date DESC
            LIMIT 7
        """,
            (ticker,),
        ).fetchall()

        historical_days = len(rows)
        days_seen = historical_days + 1
        if days_seen == 1:
            persistence_multiplier = 1.0
        elif days_seen <= 4:
            persistence_multiplier = 1.15
        elif days_seen <= 7:
            persistence_multiplier = 0.95
        else:
            persistence_multiplier = 0.75

        result["historical_days_seen"] = historical_days
        result["persistence_days_seen"] = days_seen
        result["persistence_multiplier"] = round(persistence_multiplier, 3)
        result["stale_repetition_multiplier"] = 1.0

        if persistence_multiplier != 1.0:
            original = result["final_score"]
            result["final_score"] = round(original * persistence_multiplier, 3)
            result["combined_signal_multiplier"] = round(
                result.get("combined_signal_multiplier", 1.0)
                * persistence_multiplier,
                3,
            )
            print(
                f"  {ticker}: persistence timing ({days_seen} days) "
                f"-> score {original} x {persistence_multiplier:.2f}"
            )

        if len(rows) < 3:
            continue

        # Check price movement across appearances
        prices = [r["price"] for r in rows if r["price"] and r["price"] > 0]
        if len(prices) >= 2:
            price_range = (max(prices) - min(prices)) / min(prices)
            # If appeared 3+ days and price moved less than 5% total
            if price_range < 0.05:
                days = len(rows)
                decay = max(
                    0.15, 1.0 - (days - 2) * 0.15
                )  # 0.85 at 3d, 0.70 at 4d, 0.55 at 5d, 0.40 at 6d, 0.30 at 7d+
                original = result["final_score"]
                result["final_score"] = round(original * decay, 3)
                result["stale_repetition_multiplier"] = round(decay, 3)
                result["combined_signal_multiplier"] = round(
                    result.get("combined_signal_multiplier", 1.0) * decay,
                    3,
                )
                print(
                    f"  {ticker}: repetition decay ({days} days, {price_range:.1%} price move) → score {original} × {decay:.2f}"
                )

    conn.close()
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

    print("\nStep 3.25: Applying anti-chase price action penalties...")
    for result in results:
        apply_anti_chase_penalty(result)
        apply_price_volume_confirmation(result)

    print("\nStep 3.5: Checking bearish stock flags...")
    conn = get_connection()
    try:
        for result in results:
            bearish = conn.execute(
                """
                SELECT flag_type, confidence 
                FROM bearish_stocks
                WHERE ticker = ?
                AND flagged_date >= date('now', '-14 days')
                ORDER BY confidence DESC
                LIMIT 1
            """,
                (result["ticker"],),
            ).fetchone()

            if bearish:
                flag_type = bearish["flag_type"]
                confidence = bearish["confidence"]
                original = result["final_score"]

                if flag_type == "confirmed_dump":
                    vampire_multiplier = 0.05
                elif flag_type == "scam_group":
                    vampire_multiplier = 0.08
                elif flag_type == "pump_warning":
                    vampire_multiplier = 0.15
                elif flag_type == "investigation":
                    vampire_multiplier = 0.35
                else:
                    vampire_multiplier = 0.15

                result["final_score"] = round(original * vampire_multiplier, 3)
                result["vampire_multiplier"] = vampire_multiplier
                result["combined_signal_multiplier"] = round(
                    result.get("combined_signal_multiplier", 1.0)
                    * vampire_multiplier,
                    3,
                )

                result["vampire_flagged"] = True
                result["vampire_flag_type"] = flag_type
                result["vampire_confidence"] = confidence

                print(
                    f"  {result['ticker']}: VampireStocks {flag_type} "
                    f"(confidence={confidence}) → score {original} × penalty"
                )
            else:
                result["vampire_flagged"] = False
                result["vampire_flag_type"] = None
                result["vampire_confidence"] = 0.0
                result["vampire_multiplier"] = 1.0
    except Exception as e:
        print(f"Error checking bearish stock flags: {e}")
        traceback.print_exc()
    finally:
        conn.close()

    for r in results:
        r["raw_final_score"] = r["final_score"]

    results = apply_repetition_decay(results)
    for result in results:
        apply_rank_scores(result)

    trackable = [
        r
        for r in results
        if r.get("price", 0) > 0.05  # raised from 0.01
        and r.get("price", 0) <= 15
        and r["mentions"] >= 2
        and (r.get("float_shares") is None or r.get("float_shares", 0) > 0)
    ]

    print("\nStep 4: Saving results to database...")
    save_daily_results(trackable)
    record_flagged_stocks(trackable)

    for r in results:
        if r.get("float_shares") is None:
            print(
                f"  Warning: {r['ticker']} has no float data — including with caution!"
            )

    filtered_out = [
        r
        for r in results
        if abs(r.get("change_percent", 0)) > 30
        and r.get("price", 0) > 0.05
        and r.get("price", 0) <= 15
    ]

    results = [
        r
        for r in results
        if r.get("price", 0) > 0.05
        and r.get("price", 0) <= 15
        and 0 < r.get("market_cap", 0) <= 500000000
        and (r.get("float_shares") is None or r.get("float_shares", 0) <= 50000000)
        and r["mentions"] >= 5
        and len(r["top_contexts"]) >= 3
        and abs(r.get("change_percent", 0)) <= 30  # ← ADD THIS
    ]

    print("\nStep 5: Catalyst assessment for filtered results...")
    _request_times.clear()

    catalyst_calls = 0
    for result in results:
        ticker = result["ticker"]

        context_texts = [
            ctx["text"]
            for ctx in result.get("top_contexts", [])
            if ticker.upper() in ctx["text"].upper()
        ]
        if not context_texts:
            context_texts = [ctx["text"] for ctx in result.get("top_contexts", [])]

        catalyst = assess_catalyst_quality(result["ticker"], context_texts)
        result["has_catalyst"] = catalyst["has_catalyst"]
        result["catalyst_type"] = catalyst["catalyst_type"]
        result["catalyst_confidence"] = catalyst["confidence"]
        apply_catalyst_multiplier(result)
        catalyst_calls += 1
        print(
            f"  {result['ticker']}: has_catalyst={catalyst['has_catalyst']} "
            f"type={catalyst['catalyst_type']} "
            f"confidence={catalyst['confidence']} "
            f"| {catalyst['reasoning']}"
        )

    print(f"  Catalyst assessment: {catalyst_calls} Groq calls used")
    results.sort(key=lambda x: x.get("trade_score", x["final_score"]), reverse=True)

    print("\nStep 5.5: Updating catalyst data in database...")
    conn = get_connection()
    today = date.today().strftime("%Y-%m-%d")
    for result in results:
        conn.execute(
            """
            UPDATE daily_sentiment
            SET has_catalyst = ?,
                catalyst_type = ?,
                final_score = ?
            WHERE date = ? AND ticker = ?
            """,
            (
                1 if result.get("has_catalyst") else 0,
                result.get("catalyst_type"),
                result.get("final_score", 0),
                today,
                result["ticker"],
            ),
        )
        conn.execute(
            """
            UPDATE performance_tracking
            SET has_catalyst = ?,
                catalyst_type = ?,
                final_score = ?
            WHERE flagged_date = ? AND ticker = ?
            """,
            (
                1 if result.get("has_catalyst") else 0,
                result.get("catalyst_type", "none"),
                result.get("final_score", 0),
                today,
                result["ticker"],
            ),
        )
        save_score_metadata(conn, result, today)
    conn.commit()
    conn.close()
    print(f"  Updated catalyst data for {len(results)} stocks")

    if filtered_out:
        print(f"\nFiltered out {len(filtered_out)} already-moved stocks:")
        for r in filtered_out:
            print(
                f"  {r['ticker']}: {r['change_percent']:+.1f}% same-day move (score={r['final_score']})"
            )

    print("\nStep 6: Writing output to files...\n")

    with open("output.json", "w", encoding="utf-8") as file:
        json.dump(results[:10], file, indent=2, ensure_ascii=False)

    output_dir = "output"
    os.makedirs(output_dir, exist_ok=True)
    dated_file = os.path.join(
        output_dir, f"output_{date.today().strftime('%Y-%m-%d')}.json"
    )
    with open(dated_file, "w", encoding="utf-8") as file:
        json.dump(results[:10], file, indent=2, ensure_ascii=False)
    print(f"Output written to {dated_file}")

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
            setup_str = f"[SETUP: {r.get('setup_type', 'unknown').upper()}]"
            file.write(f"${r['ticker']} {setup_str} {catalyst_str} {mod_str}\n")
            file.write(
                f"  Mentions: {r['mentions']} | Sentiment: {r['avg_sentiment']:+.3f} "
                f"| Radar: {r.get('radar_score', 0):+.3f} "
                f"| Trade: {r.get('trade_score', r['final_score']):+.3f} "
                f"| Risk: {r.get('risk_score', 0):.1f} ({r.get('risk_level', 'n/a')})\n"
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
