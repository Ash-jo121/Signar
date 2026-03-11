import os
import json
import re
from transformers import pipeline
from dotenv import load_dotenv
from groq import Groq
import time

_last_groq_call = 0
_GROQ_MIN_INTERVAL = 4

load_dotenv()

print("Loading FinBERT model...")
sentiment_pipeline = pipeline(
    "text-classification", model="ProsusAI/finbert", tokenizer="ProsusAI/finbert"
)

groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))


def finbert_analyze(text):
    text = text[:512]
    try:
        results = sentiment_pipeline(text, top_k=None)
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


def groq_analyze(text):
    global _last_groq_call

    elapsed = time.time() - _last_groq_call
    if elapsed < _GROQ_MIN_INTERVAL:
        time.sleep(_GROQ_MIN_INTERVAL - elapsed)

    _last_groq_call = time.time()

    try:
        response = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",  # fast and free
            messages=[
                {
                    "role": "user",
                    "content": f"""Analyze sentiment of this Reddit stock comment.
Be conservative with scores — reserve extreme values for very strong signals.

Scoring guide:
- +0.8 to +1.0: Very strong bullish (FDA approval, massive earnings beat)
- +0.4 to +0.8: Moderately bullish (positive outlook, buying interest)
- +0.1 to +0.4: Slightly bullish (mild positive sentiment)
- -0.1 to +0.1: Neutral (watching, unsure, holding)
- -0.4 to -0.1: Slightly bearish (mild concern)
- -0.4 to -0.8: Moderately bearish (negative outlook)
- -0.8 to -1.0: Very strong bearish (scam, fraud, bankruptcy)

Financial slang reference:
- Bullish: moon, rocket, 🚀, squeeze, breakout, calls, accumulating
- Bearish: dump, short, puts, scam, dilution, avoid, bankrupt

Return ONLY JSON: {{"label": "positive/negative/neutral", "score": 0.0}}

Comment: "{text}"
""",
                }
            ],
            temperature=0.1,  # low temperature = more consistent outputs
        )

        raw = response.choices[0].message.content.strip()

        # Clean up response in case model adds extra text
        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
            return {
                "score": round(float(result.get("score", 0)), 3),
                "label": result.get("label", "neutral"),
            }
    except Exception as e:
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
