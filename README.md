# 📡 ThreadRadar

> Automated Reddit sentiment analysis for penny stock discovery

ThreadRadar scrapes penny stock subreddits, extracts ticker mentions, and runs financial sentiment analysis using FinBERT — turning hours of manual Reddit browsing into a ranked daily dashboard.

---

## The Problem

Finding promising penny stocks on Reddit means manually reading through hundreds of posts and comments across multiple subreddits like r/pennystocks, r/Pennystock, and r/smallstreetbets. A single post can have 200+ comments, many of which contain counter-arguments, DD (due diligence), or warnings that completely change the picture. Doing this manually takes hours.

ThreadRadar automates the entire pipeline and surfaces the top picks in seconds.

---

## How It Works

```
Reddit JSON API
      ↓
  scraper.py          → Fetches posts + all nested comments (hot & new)
      ↓
  extractor.py        → Extracts ticker symbols using regex + blacklist filtering
      ↓
  sentiment.py        → Scores each mention using FinBERT (financial BERT model)
      ↓
  main.py             → Aggregates scores, weights by upvotes, ranks tickers
      ↓
  output.json         → Consumed by React frontend dashboard
```

The sentiment score reflects the **full conversation** — not just the original post. A bullish post with bearish comments will score lower than a bullish post with supporting comments. This is the key insight: Reddit counters matter. We take the aggregate sentiment of the reddit comment tree to get the full score for a stock pick.

---

## Demo

> Screenshot coming soon — UI in progress

---

## Tech Stack

| Layer              | Technology                                                                 |
| ------------------ | -------------------------------------------------------------------------- |
| Reddit Data        | Reddit Public JSON API (no auth required)                                  |
| Ticker Extraction  | Regex + NASDAQ/NYSE ticker blacklist                                       |
| Sentiment Analysis | [FinBERT](https://huggingface.co/ProsusAI/finbert) (financial domain BERT) + Groq API |
| Backend            | Python — `requests`, `transformers`, `torch`                               |
| Frontend           | React + Tailwind CSS                                                       |
| Scheduling         | Runs every 24 hours (cron / task scheduler)                                |

**Why FinBERT over VADER?**
General sentiment models don't understand financial language. VADER scores "this stock is going to the moon" as neutral. FinBERT was trained on financial news and analyst reports — it correctly understands terms like "bullish", "FDA approval", "short squeeze", and "dilution".

---

## Project Structure

```
threadradar/
  backend/
    scraper.py        # Fetches posts and nested comments from Reddit
    extractor.py      # Extracts and filters ticker symbols from text
    sentiment.py      # FinBERT sentiment scoring
    main.py           # Pipeline orchestration + ranking + output
    output.json       # Generated output consumed by frontend
    output.txt        # Human-readable version of output
  frontend/
    src/
      App.jsx
      components/
        <!-- Dashboard.jsx
        TickerCard.jsx
        DetailPage.jsx -->
  README.md
```

---

## Getting Started

### Prerequisites

- Python 3.9+
- Node.js 18+
- ~500MB disk space for FinBERT model (downloaded automatically on first run)

### Backend Setup

```bash
# Clone the repo
git clone https://github.com/yourusername/threadradar.git
cd threadradar/backend

# Install dependencies
pip install requests transformers torch yfinance

# Run the analysis pipeline
python main.py
```

The first run will download the FinBERT model (~500MB). Subsequent runs use the cached model and take 15–30 minutes depending on Reddit rate limits. 

Output is written to `output.json` and `output.txt`.

### Frontend Setup

```bash
cd threadradar/frontend

npm install
npm run dev
```

Open `http://localhost:5173` in your browser.

### Running on a Schedule

**Linux/Mac (cron):**

```bash
# Run every day at 6 AM
0 6 * * * cd /path/to/threadradar/backend && python main.py
```

**Windows (Task Scheduler):**
Create a basic task that runs `python main.py` from the backend directory daily.

---

## Subreddits Monitored

| Subreddit              | Focus                                       |
| ---------------------- | ------------------------------------------- |
| r/pennystocks          | Primary — most active penny stock community |
| r/Pennystock           | Secondary — additional coverage             |
| r/smallstreetbets      | Tertiary — broader retail sentiment         |
| r/RobinHoodPennyStocks | Less traffic subreddit will add in future   |

---

## Scoring Algorithm

Each ticker's final score is calculated as:

```
final_score = avg_sentiment × (1 + mentions × 0.1) × (1 + avg_post_score × 0.01) | This formula is development in progress |
```

Where:

- `avg_sentiment` — weighted average FinBERT score across all mentions (-1 to +1)
- `mentions` — total number of times the ticker appeared across posts and comments
- `avg_post_score` — average Reddit upvote score of posts containing the ticker

Tickers with fewer than 2 mentions are filtered out to reduce noise.

---

## Known Limitations

- **Pump-and-dump risk** — Reddit penny stock communities are susceptible to coordinated pumping. High sentiment scores do not guarantee legitimate picks. Always do your own research.
- **OTC stock data gaps** — Some penny stocks trade OTC and may not have full price data available via Yahoo Finance.
- **Rate limiting** — Reddit's unauthenticated API limits requests. The pipeline includes automatic retry logic but the `top` category is sometimes unavailable.
- **FinBERT and Reddit slang** — FinBERT was trained on formal financial text. Reddit slang like "to the moon 🚀" scores as neutral rather than positive. This is intentional conservatism — we prefer false negatives over false positives.

---

## Roadmap

### V1 (Current)

- [x] Reddit scraper with recursive comment fetching
- [x] Ticker extraction with blacklist filtering
- [x] FinBERT sentiment analysis
- [x] Ranked output (JSON + TXT)
- [x] React dashboard UI
- [x] Yahoo Finance price integration
- [ ] Groq API integration
- [ ] React ticker page
- [ ] Scheduler
- [ ] Google Sheets API integration

### V2 (Planned)

- [ ] Historical data storage (PostgreSQL)
- [ ] Search functionality for past picks
- [ ] Performance tracking — did the picks actually move?
- [ ] Subreddit weighting (r/pennystocks > r/smallstreetbets)
- [ ] Pump-and-dump detection (sudden mention spikes)
- [ ] Reddit OAuth for higher rate limits
- [ ] Stock specific subreddit to be analyzed for more data

---

## Disclaimer

> **ThreadRadar is not financial advice.** This tool is for informational and educational purposes only. Penny stocks are highly speculative investments. Never invest money you cannot afford to lose. Always conduct your own due diligence before making any investment decisions.

---

## Author

Built by Ashish — a project to automate a manual workflow for discovering penny stock opportunities from Reddit sentiment.

---

_If this helped you, consider starring the repo ⭐_
