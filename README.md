# 📡 ThreadRadar

> Automated Reddit sentiment analysis for penny stock discovery

ThreadRadar scrapes penny stock subreddits, extracts ticker mentions, and runs financial sentiment analysis using AI ( FinBERT + Groq ) — turning hours of manual Reddit browsing into a ranked daily dashboard.

---

## The Problem

Finding promising penny stocks on Reddit means manually reading through hundreds of posts and comments across multiple subreddits like r/pennystocks, r/Pennystock, r/smallstreetbets etc. A single post can have 200+ comments, many of which contain counter-arguments, DD (due diligence), or warnings that completely change the picture. Doing this manually takes hours.

ThreadRadar automates the entire pipeline and surfaces the top picks in seconds.

---

## How It Works

<img width="1819" height="795" alt="image" src="https://github.com/user-attachments/assets/baead758-a788-442a-a4e4-7d444a222d60" />


The sentiment score reflects the **full conversation** — not just the original post. A bullish post with bearish comments will score lower than a bullish post with supporting comments. This is the key insight: Reddit counters matter along with the upvote score for the comment. We take the aggregate sentiment of the reddit comment tree to get the full score for a stock pick. Context inheritance is also considered, whenever a comment is taken it need not mention a ticker or stock. 

---

## Demo

> Screenshot coming soon — UI in progress

---

## Tech Stack

| Layer              | Technology                                                                            |
| ------------------ | ------------------------------------------------------------------------------------- |
| Reddit Data        | Reddit Public JSON API (no auth required)                                             |
| Ticker Extraction  | Regex + NASDAQ/NYSE ticker blacklist + Common words                                   |
| Sentiment Analysis | [FinBERT](https://huggingface.co/ProsusAI/finbert) (financial domain BERT) + Groq API |
| Backend            | Python — `requests`, `transformers`, `torch`                                          |
| Frontend           | React + Tailwind CSS                                                                  |
| Scheduling         | Runs every 24 hours ( github actions )                                                |

**Why FinBERT over VADER?**
General sentiment models don't understand financial language. VADER scores "this stock is going to the moon" as neutral. FinBERT was trained on financial news and analyst reports — it correctly understands terms like "bullish", "FDA approval", "short squeeze", and "dilution".

---

## Project Structure

```
threadradar/
  backend/
      constants/
            config.py
            exclusion.py
      integrations/
            yahooFn.py
            google_sheets_integration.py
            
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
# Run every day at 3 PM
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
| r/RobinHoodPennyStocks |                                             |
| r/10xPennyStocks       |                                             | 
| r/Shortsqueeze         |                                             |
| r/SqueezePlays         |                                             |
| r/wallstreetbets       | Only penny stocks                           |

---

## Scoring Algorithm

Each ticker's final score is calculated as:

```
final_score = avg_sentiment × (1 + log(1 + mentions) * 0.3) × engagement_multiplier | This formula is development in progress |
```

Where:

- `avg_sentiment` — weighted average FinBERT score across all mentions (-1 to +1)
- `mentions` — total number of times the ticker appeared across posts and comments
- `engagement_multiplier` — indicator for engagement weighting

Tickers with fewer than 2 mentions are filtered out to reduce noise.

---

## Known Limitations

- **Pump-and-dump risk** — Reddit penny stock communities are susceptible to coordinated pumping. High sentiment scores do not guarantee legitimate picks. Always do your own research.
- **OTC stock data gaps** — Some penny stocks trade OTC and may not have full price data available via Yahoo Finance.
- **Float data are not obtainable through yahoo finance, we are bypassing the stocks with a warning.
  <!-- - **Rate limiting** — Reddit's unauthenticated API limits requests. The pipeline includes automatic retry logic but the `top` category is sometimes unavailable. -->
  <!-- - **FinBERT and Reddit slang** — FinBERT was trained on formal financial text. Reddit slang like "to the moon 🚀" scores as neutral rather than positive. This is intentional conservatism — we prefer false negatives over false positives. -->

---

## Roadmap

### V1 (Completed)

- [x] Reddit scraper with recursive comment fetching
- [x] Ticker extraction with blacklist filtering
- [x] FinBERT sentiment analysis
- [x] Ranked output (JSON + TXT)
- [x] React dashboard UI
- [x] Yahoo Finance price integration
- [x] Groq API integration
- [x] React ticker page
- [x] Google Sheets API integration

### V2 (Current)

- [x] Historical data storage (sqlite)
- [x] Scheduler
- [x] Performance tracking — did the picks actually move?
- [x] Pump-and-dump detection (sudden mention spikes)
- [ ] Search functionality for past picks
- [ ] Subreddit weighting (r/pennystocks > r/smallstreetbets)
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
