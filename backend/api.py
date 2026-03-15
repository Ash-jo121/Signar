from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import json

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/tickers")
def get_tickers():
    with open("output.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    return data


@app.get("/api/tickers/{symbol}")  # pyright: ignore[reportUndefinedVariable]
def get_ticker(symbol: str):
    with open("output.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    result = next((r for r in data if r["ticker"] == symbol.upper()), None)
    if not result:
        return {"error": "Ticker not found"}
    return result
