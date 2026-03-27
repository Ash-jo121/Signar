from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import json
import os

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DATA_PATH = os.path.join(os.path.dirname(__file__), "output.json")


def load_data():
    if not os.path.exists(DATA_PATH):
        return []
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


@app.get("/api/tickers")
def get_tickers():
    return load_data()


@app.get("/api/tickers/{symbol}")  # pyright: ignore[reportUndefinedVariable]
def get_ticker(symbol: str):
    data = load_data()
    result = next((r for r in data if r["ticker"] == symbol.upper()), None)
    if not result:
        return {"error": "Ticker not found"}
    return result


@app.get("/health")
def health():
    return {"status": "ok"}
