# Signar

**Automated Reddit sentiment analysis for penny stock discovery**

Signar monitors penny stock communities across Reddit, extracts ticker mentions, and runs multi-factor financial sentiment analysis — turning hours of manual research into a ranked daily signal feed. Built as both a genuine investment research tool and an end-to-end ML engineering project.

---

## What It Does

Reddit is one of the fastest sources of retail sentiment on speculative stocks, but extracting signal from noise requires reading hundreds of posts and comment threads across multiple communities. A single bullish post surrounded by bearish comments tells a completely different story than the post alone. Doing this manually takes hours and misses most of the information.

Signar automates the full pipeline: scrape → extract → score → rank → track outcomes. The result is a daily ranked list of tickers with verified catalysts, multi-day persistence signals, risk classifications, and T+1/T+3/T+7/T+14/T+30 outcome tracking against the IWM benchmark.

---

## Architecture

```
GitHub Actions (fetch)  →  Railway (analysis + SQLite)  →  Vercel (React frontend)
```

The pipeline runs as two decoupled services. GitHub Actions handles Reddit scraping daily using Playwright with residential proxies and stealth fingerprinting to bypass bot detection. The raw payload is POSTed to Railway, which runs the analysis pipeline, writes structured results to a persistent SQLite database, and triggers price updates for outcome tracking.

### Scoring Pipeline

Each ticker passes through a multi-stage scoring system before appearing in the output:

**1. Mention aggregation** — Weighted mention counts across posts and comment trees, with context inheritance (a comment referencing a previously mentioned ticker inherits that context). Repetition decay penalises coordinated shill patterns where the same thesis is copy-pasted across multiple posts.

**2. Sentiment scoring** — FinBERT scores each mention in financial context. The aggregate reflects the full conversation: a bullish post with bearish comments scores lower than a bullish post with supporting engagement. VADER was rejected because it scores "going to the moon" as neutral.

**3. Signal multipliers** — Over a dozen multiplicative factors applied to the base score including cross-subreddit presence, author credibility, account age, karma, engagement ratio, post quality, catalyst type, timing, mention velocity, and promotion risk detection.

**4. Risk classification** — Tickers are classified as `low`, `medium`, or `high` risk based on a composite of price action, market cap, dilution indicators, author concentration, and vampire/shill detection. High-risk setups are surfaced in a separate `avoid_high_risk` bucket.

**5. Trade gates** — Even well-scored tickers must pass a set of market confirmation gates before appearing as actionable: minimum dollar volume, no `anti_chase` (already moved significantly), no `stale_squeeze_too_old`, sufficient market confirmation. Gate failures are logged with explicit reasons.

**6. Thesis confirmation** — A rolling 4-day persistence layer tracks whether each signal is `flash` (single day), `building`, `confirmed`, `stale`, or `fading/decaying`. Only tickers with sustained, broadening interest across multiple days and authors appear in the confirmed watchlist.

**7. Outcome tracking** — Price updater runs T+1, T+3, T+7, T+14, T+30 checks against each flagged date, with IWM benchmark comparison for excess return measurement, split detection, and anomaly flagging.

---

## Output Structure

Each daily run produces a structured JSON with the following sections:

| Section | Description |
|---|---|
| `best_trade_candidates` | Tickers that passed all risk gates — actionable signals |
| `radar_watchlist` | Signals present but failing one or more trade gates |
| `near_miss_candidates` | Ranked near-misses with explicit failure reasons |
| `avoid_high_risk` | High-risk setups: anti-chase, promotion risk, dilution risk, vampire-flagged |
| `multi_day_confirmation` | Full 4-day rolling persistence ledger for all tracked tickers |
| `confirmed_watchlist` | Tickers that have reached `building` or `confirmed` thesis state |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Reddit scraping | Playwright + playwright-stealth 2.0.3 + Decodo residential proxies |
| Ticker extraction | Regex + NASDAQ/NYSE/AMEX ticker whitelist + common word blacklist |
| Sentiment analysis | FinBERT (ProsusAI/finbert) + Groq API |
| Price data | yfinance |
| Database | SQLite (Railway persistent volume) |
| Pipeline orchestration | GitHub Actions (fetch) → Railway (analysis) |
| Scheduling | cron-job.org external trigger → GitHub Actions `workflow_dispatch` |
| Frontend | React + Tailwind CSS, deployed on Vercel |
| Backend | Python — FastAPI, `transformers`, `torch`, `playwright` |

---

## Subreddits Monitored

| Subreddit | Focus |
|---|---|
| r/pennystocks | Primary — most active penny stock community |
| r/Pennystock | Secondary — active with distinct author base |
| r/smallstreetbets | Tertiary — broader retail sentiment |
| r/RobinHoodPennyStocks | Emerging picks, lower quality filter required |
| r/10xPennyStocks | Higher conviction DD posts |
| r/Shortsqueeze | Short squeeze thesis tracking |
| r/SqueezePlays | Squeeze-specific setups |
| r/wallstreetbets | Filtered to penny stock mentions only |

---

## Database Schema

```
daily_sentiment       — per-ticker daily scores and all multipliers
score_metadata        — raw scoring components and gate results
daily_contexts        — top mention contexts per ticker per day
posts                 — raw scraped posts
performance_tracking  — T+1/3/7/14/30 outcomes with IWM benchmark
thesis_confirmation   — rolling 4-day confirmation state per ticker
```

---

## Project Structure

```
signar/
  backend/
    constants/
      config.py           # Environment and pipeline configuration
      exclusion.py        # Ticker blacklist (common words, ETFs, etc.)
    scraper/
      fetch_raw_reddit.py # Playwright fetch pipeline with stealth + proxies
    pipeline/
      main.py             # Analysis orchestration
      sentiment.py        # FinBERT + Groq scoring
      extractor.py        # Ticker extraction and filtering
      price_updater.py    # T+N outcome tracking with IWM benchmark
      backtest.py         # Signal quality analysis
    integrations/
      yahooFn.py          # yfinance price data
    database.py           # SQLite schema and migrations
    migrate.py            # Idempotent column migrations
  frontend/
    src/
      App.jsx
      components/
        Dashboard.jsx
        TickerCard.jsx
        DetailPage.jsx
  .github/
    workflows/
      fetch_raw_reddit.yml  # GitHub Actions fetch pipeline
  README.md
```

---

## Getting Started

### Prerequisites

- Python 3.10+
- Node.js 18+
- ~500MB disk space for FinBERT model (downloaded automatically on first run)

### Backend Setup

```bash
git clone https://github.com/Ash-jo121/Signar.git
cd signar/backend

pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium

# Run the analysis pipeline
python main.py
```

The first run downloads the FinBERT model (~500MB). Subsequent runs use the cached model.

### Frontend Setup

```bash
cd signar/frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

### Environment Variables

```
GROQ_API_KEY          # Groq API key for LLM-assisted catalyst classification
DECODO_PROXY_USER     # Residential proxy credentials
DECODO_PROXY_PASS
RAILWAY_UPLOAD_URL    # Railway endpoint for raw payload upload
GITHUB_PAT            # For external cron trigger via workflow_dispatch
```

---

## Roadmap

### V1 — Completed

- [x] Reddit scraper with recursive comment tree fetching
- [x] Ticker extraction with blacklist and density filtering
- [x] FinBERT sentiment analysis
- [x] Groq API catalyst classification
- [x] Multi-factor scoring with signal multipliers
- [x] Ranked output (JSON)
- [x] React dashboard
- [x] Yahoo Finance price integration
- [x] Playwright + residential proxy Reddit access (Cloudflare bypass)
- [x] Two-pipeline architecture: GitHub Actions fetch → Railway analysis
- [x] SQLite persistent storage
- [x] Repetition decay for coordinated shill detection
- [x] Vampire / pump-and-dump detection
- [x] Author credibility scoring
- [x] `change_percent` filter to exclude already-moved stocks
- [x] T+1/T+3/T+7 outcome tracking

### V2 — In Progress

- [x] T+14/T+30 long-horizon outcome tracking
- [x] IWM benchmark comparison and excess return calculation
- [x] Split detection and anomaly flagging
- [x] Thesis confirmation layer (flash → building → confirmed → stale → fading)
- [x] `confirmed_watchlist` and `near_miss_candidates` output sections
- [x] `raw_final_score` preservation for backtesting integrity
- [ ] FinBERT fine-tuning on accumulated domain data (planned after 4–6 weeks of data)
- [ ] Backtesting analysis with quantified signal quality metrics
- [ ] Ablation studies comparing scoring versions
- [ ] Frontend deployment on Vercel
- [ ] Multi-source expansion: StockTwits, SEC filings, news
- [ ] Level 2 sentiment analysis
- [ ] Subreddit expansion to 8 communities

---

## Known Limitations

**Pump-and-dump risk** — Reddit penny stock communities are susceptible to coordinated promotion. High signal scores do not guarantee legitimate picks. The pipeline includes promotion risk scoring, author concentration penalties, and vampire detection, but no automated system is a substitute for your own due diligence.

**Author identity persistence** — The thesis confirmation layer currently cannot distinguish new authors discovering a stock from existing authors reposting. Cross-day author set tracking is a known gap on the roadmap.

**Catalyst classification** — LLM-based catalyst extraction can be overly generous on speculative framing. "Reportedly exploring" and "selected for evaluation" are not the same as a signed contract, but both can trigger high `catalyst_confidence` scores. Manual review of catalyst reasoning is recommended for any confirmed watchlist name.

**OTC data gaps** — Some penny stocks trade OTC and may have incomplete or delayed price data via yfinance.

---

## Disclaimer

Signar is not financial advice. This tool is for informational and research purposes only. Penny stocks are highly speculative. Never invest money you cannot afford to lose. Always conduct your own due diligence before making any investment decision.

---

*Built by Ashish — automating a manual workflow for discovering penny stock opportunities from Reddit sentiment, and building an ML portfolio project around measurable signal quality.*
