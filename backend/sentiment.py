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

_request_times = deque()
_MAX_REQUESTS_PER_MINUTE = 20
_MAX_TOKENS_PER_MINUTE = 5000
_ESTIMATED_TOKENS_PER_REQUEST = 120

load_dotenv()

groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
sentiment_pipeline = None


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
    global _request_times

    now = time.time()
    while _request_times and now - _request_times[0] > 60:
        _request_times.popleft()

    if len(_request_times) >= _MAX_REQUESTS_PER_MINUTE:
        wait_time = 60 - (now - _request_times[0]) + 0.5
        if wait_time > 0:
            print(f"  Rate limit approaching — waiting {wait_time:.1f}s")
            time.sleep(wait_time)

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
            model="llama-3.1-8b-instant",
            messages=[
                {
                    "role": "user",
                    "content": f"""Analyze Reddit stock comment sentiment.
Return ONLY JSON: {{"label":"positive/negative/neutral","score":0.0}}

Score by conviction level:
Positive: +0.2 mild interest/watching, +0.4 moderately bullish with reasoning,
          +0.6 strongly bullish with catalyst, +0.8 to +1.0 very high conviction
Negative: -0.2 mild concern, -0.4 moderately bearish,
          -0.6 strongly bearish, -0.8 to -1.0 very bearish
Neutral: 0.0 for questions, confusion, meta-commentary, price reporting

Default to LOWER scores when unsure. Questions alone score 0.0.
Bullish slang: moon,rocket,🚀,squeeze,breakout,calls,accumulating,sleeping on
Bearish slang: dump,short,scam,dilution,avoid,bankrupt,rekt,trap

IMPORTANT: score must match label sign. Never mismatch.

Comment: "{text}"
""",
                }
            ],
            temperature=0.1,
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
            print(f"  429 hit — waiting 60s")
            time.sleep(60)
            _request_times.clear()
            if not retry:
                return groq_analyze(text, retry=True)
        else:
            print(f"Groq error: {e}")

    return {"score": 0.0, "label": "neutral"}


def assess_catalyst_quality(ticker, contexts, retry=False):
    if not contexts:
        return {
            "has_catalyst": False,
            "catalyst_type": "none",
            "confidence": 0.0,
            "reasoning": "",
        }

    contexts_text = "\n---\n".join([c[:200] for c in contexts[:5]])
    wait_for_rate_limit()
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {
                    "role": "user",
                    "content": f"""Analyze these Reddit comments about stock {ticker}.

Is there evidence of a REAL verifiable catalyst?

REAL catalysts (return true):
- FDA approval, trial results, PDUFA date
- Government contract, DoD/DHS award
- Revenue/earnings news with specific numbers
- Named partnership or commercial agreement
- SEC filing, 10-K, specific regulatory event
- Clinical trial data or milestone

NOT catalysts (return false):
- Short squeeze setup, float/short interest discussion
- Price targets without backing
- General hype, moon/rocket language
- Watchlist mentions without reasoning
- Technical analysis only

Return ONLY JSON:
{{"has_catalyst": true/false, "catalyst_type": "FDA/contract/earnings/partnership/clinical/regulatory/none", "confidence": 0.0-1.0, "reasoning": "one sentence max"}}

Comments about {ticker}:
{contexts_text}""",
                }
            ],
            temperature=0.1,
        )

        raw = response.choices[0].message.content.strip()
        print(f"  [{ticker}] raw: {raw[:80]}")  # debug log

        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if json_match:
            try:
                result = json.loads(json_match.group())
            except json.JSONDecodeError:
                try:
                    result = ast.literal_eval(json_match.group())
                except:
                    result = {
                        "has_catalyst": False,
                        "catalyst_type": "none",
                        "confidence": 0.0,
                    }

            return {
                "has_catalyst": bool(result.get("has_catalyst", False)),
                "catalyst_type": result.get("catalyst_type", "none"),
                "confidence": round(float(result.get("confidence", 0.0)), 2),
                "reasoning": result.get("reasoning", ""),
            }

    except Exception as e:
        error_str = str(e)
        if "429" in error_str or "rate_limit" in error_str.lower():
            print(f"  429 hit — waiting 60s")
            time.sleep(60)
            _request_times.clear()
            if not retry:
                return assess_catalyst_quality(ticker, contexts, retry=True)
        else:
            print(f"  Catalyst assessment error for {ticker}: {e}")

    return {
        "has_catalyst": False,
        "catalyst_type": "none",
        "confidence": 0.0,
        "reasoning": "",
    }


def analyze_sentiment(text):
    finbert_result = finbert_analyze(text)

    if finbert_result["confident"]:
        return {
            "score": finbert_result["score"],
            "label": finbert_result["label"],
            "source": "finbert",
        }

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
