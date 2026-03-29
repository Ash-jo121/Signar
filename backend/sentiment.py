import ast
from collections import deque
import os
import json
import re
from transformers import pipeline
from dotenv import load_dotenv
from groq import Groq
import time

_last_groq_call = 0
_GROQ_MIN_INTERVAL = 4.0
_consecutive_429s = 0

# Track request timestamps in a sliding window
_request_times = deque()
_MAX_REQUESTS_PER_MINUTE = 20  # conservative, actual limit is 30
_MAX_TOKENS_PER_MINUTE = 5000  # conservative, actual limit is 6000
_ESTIMATED_TOKENS_PER_REQUEST = 120  # after prompt shortening

load_dotenv()

groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))


def get_pipeline():
    global sentiment_pipeline
    if sentiment_pipeline is None:
        print("Loading FinBERT model...")
        sentiment_pipeline = pipeline(
            "text-classification",
            model="ProsusAI/finbert",
            tokenizer="ProsusAI/finbert",
        )
    return sentiment_pipeline


def wait_for_rate_limit():
    """Proactively wait before sending request"""
    global _request_times

    now = time.time()

    # Remove requests older than 60 seconds
    while _request_times and now - _request_times[0] > 60:
        _request_times.popleft()

    # If we're at the request limit, wait
    if len(_request_times) >= _MAX_REQUESTS_PER_MINUTE:
        # Wait until oldest request is 60s old
        wait_time = 60 - (now - _request_times[0]) + 0.5
        if wait_time > 0:
            print(f"  Rate limit approaching — waiting {wait_time:.1f}s")
            time.sleep(wait_time)

    # If we're approaching token limit, wait
    tokens_used = len(_request_times) * _ESTIMATED_TOKENS_PER_REQUEST
    if tokens_used >= _MAX_TOKENS_PER_MINUTE:
        wait_time = 60 - (now - _request_times[0]) + 0.5
        if wait_time > 0:
            print(f"  Token limit approaching — waiting {wait_time:.1f}s")
            time.sleep(wait_time)

    _request_times.append(time.time())


def finbert_analyze(text):
    text = text[:512]
    try:
        pipe = get_pipeline()
        results = pipe(text, top_k=None)
        scores = {r["label"]: r["score"] for r in results}
        positive = scores.get("positive", 0)
        negative = scores.get("negative", 0)
        final_score = positive - negative
        dominant = max(scores, key=scores.get)
        return {
            "score": round(final_score, 3),
            "label": dominant,
            "confident": abs(final_score) > 0.7,
        }
    except:
        return {"score": 0.0, "label": "neutral", "confident": False}


def groq_analyze(text, retry=False):
    text = text[:500]

    wait_for_rate_limit()

    try:
        response = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",  # fast and free
            messages=[
                {
                    "role": "user",
                    "content": f"""Analyze Reddit stock comment sentiment.
Return ONLY JSON: {{"label":"positive/negative/neutral","score":0.0}}

Scores: +0.8 to +1.0 very bullish, +0.4 to +0.8 bullish, 
-0.4 to -0.8 bearish, -0.8 to -1.0 very bearish. Be conservative.
Bullish slang: moon,rocket,🚀,squeeze,breakout,calls,accumulating
Bearish slang: dump,short,scam,dilution,avoid,bankrupt,rekt

IMPORTANT: score must be negative for bearish/negative labels, 
positive for bullish/positive labels. Never return bearish with 
positive score or bullish with negative score.

Comment: "{text}"
""",
                }
            ],
            temperature=0.1,  # low temperature = more consistent outputs
        )

        raw = response.choices[0].message.content.strip()

        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if json_match:
            try:
                result = json.loads(json_match.group())
            except json.JSONDecodeError:
                try:
                    result = ast.literal_eval(json_match.group())
                except:
                    result = {"label": "neutral", "score": 0.0}
            return {
                "score": round(float(result.get("score", 0)), 3),
                "label": result.get("label", "neutral"),
            }
    except Exception as e:
        error_str = str(e)
        if "429" in error_str or "rate_limit" in error_str.lower():
            print(
                f"  429 hit #{_consecutive_429s} — interval now {_GROQ_MIN_INTERVAL}s, waiting 60s"
            )
            time.sleep(60)

            _request_times.clear()

            if not retry:
                return groq_analyze(text, retry=True)
        else:
            print(f"Groq error: {e}")

    return {"score": 0.0, "label": "neutral"}


def analyze_sentiment(text):
    # Step 1 — try FinBERT first
    finbert_result = finbert_analyze(text)

    # Step 2 — if FinBERT is confident, trust it
    if finbert_result["confident"]:
        return {
            "score": finbert_result["score"],
            "label": finbert_result["label"],
            "source": "finbert",
        }

    # Step 3 — FinBERT unsure, use Groq for better context understanding
    groq_result = groq_analyze(text)
    return {
        "score": groq_result["score"],
        "label": groq_result["label"],
        "source": "groq",
    }


if __name__ == "__main__":
    test_comments = [
        "RCKT is going to moon, expected FDA approval next week!",
        "This stock is a scam, avoid at all costs",
        "DNUT looking bullish, strong support at $8",
        "I lost all my money on this garbage stock",
        "GANX phase 2 trial shows 73% efficacy, PDUFA date March 28",
        "bears getting absolutely destroyed on this one 🚀",
        "dilution incoming, they always do this to retail",
        "Neutral on BYND, waiting to see earnings",
    ]

    for comment in test_comments:
        result = analyze_sentiment(comment)
        print(
            f"[{result['source']:7}] {result['score']:+.3f} | {result['label']:8} | {comment[:60]}"
        )
