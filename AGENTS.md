# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Project Overview

ThreadRadar scrapes Reddit penny stock subreddits, extracts ticker mentions, performs sentiment analysis, enriches with Yahoo Finance data, and outputs top 10 stocks ($0.01–$15) to `output.json`, `output.txt`, and a Google Sheet.

## Commands

### Backend (Python)
```bash
# Run the full pipeline (scrape → analyze → enrich → output)
cd backend && python main.py

# Run the FastAPI server (serves output.json to the frontend)
cd backend && uvicorn api:app --reload

# Test individual modules
cd backend && python sentiment.py
cd backend && python scraper.py
cd backend && python extractor.py
```

### Frontend (React + TypeScript + Vite)
```bash
cd frontend && npm install
cd frontend && npm run dev       # dev server at http://localhost:5173
cd frontend && npm run build
cd frontend && npm run lint
```

## Environment / Secrets

Backend requires a `.env` file in `backend/`:
- `GROQ_API_KEY` — for Groq LLM sentiment fallback (llama-3.1-8b-instant)
- `GOOGLE_CREDENTIALS` — JSON string of Google service account credentials (falls back to `credentials.json` file)

Google Sheets target is hardcoded as `"Stock Trajectory"` in `google_sheets_integration.py`.

## Architecture

### Pipeline Flow (`main.py`)
1. **Scrape** (`scraper.py`) — fetches `hot`/`top`/`new` posts from `r/pennystocks`, `r/smallstreetbets`, `r/Pennystock` via Reddit JSON API (no auth). Comments are fetched per-post with recursive threading; comment depth reduces mention weight.
2. **Extract** (`extractor.py`) — identifies tickers via `$TICKER` dollar-sign patterns and bare `UPPERCASE` words, validated against `tickers.py` (VALID_TICKERS set) and filtered through `exclusion.py` (LARGE_CAP_EXCLUDE). `comparison.py` detects comparative mentions ("next $AAPL") to avoid false positives.
3. **Analyze** (`sentiment.py`) — two-tier: FinBERT (local HuggingFace model `ProsusAI/finbert`) runs first; if not confident (|score| ≤ 0.7), falls back to Groq API. Rate limiting is managed in-process with a sliding window (20 req/min, 5000 tokens/min).
4. **Score** — `final_score = avg_sentiment × (1 + mentions × 0.1) × (1 + avg_post_score × 0.01)`. Tickers need ≥5 mentions to be analyzed, ≥2 to appear in results.
5. **Enrich** (`yahooFn.py`) — pulls price + metadata from yfinance. Price filter: $0.01–$15 only.
6. **Output** — writes `output.json` (top 10) and `output.txt`, then syncs to Google Sheets.

### API (`api.py`)
Minimal FastAPI app with two endpoints:
- `GET /api/tickers` — returns full `output.json`
- `GET /api/tickers/{symbol}` — returns single ticker from `output.json`

The API reads `output.json` on every request (no caching). CORS is open to `localhost:5173` and `localhost:5174`.

### Frontend (`frontend/src/`)
React + TypeScript SPA with React Router:
- `Dashboard` — fetches `/api/tickers`, maps through `DashboardMapper.ts`, renders top 10 table with click-to-detail navigation
- `TickerDetails` — ticker detail view (navigated to via router state, not a fresh API call)
- `types/Dashboard.ts` — canonical frontend type for ticker data
- `helpers/DashboardMapper.ts` — transforms backend JSON field names to frontend `TickerData` shape
- UI components under `components/ui/` are shadcn/ui primitives

### Key Data Contracts
The backend `output.json` shape (produced by `main.py` + `yahooFn.py`) is the contract between backend and frontend. The `DashboardMapper` in the frontend maps backend snake_case fields to camelCase `TickerData`. Any new fields added to the pipeline must be reflected in both `yahooFn.py` (enrich) and `DashboardMapper.ts` to appear in the UI.
