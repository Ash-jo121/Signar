from datetime import datetime
from fastapi import FastAPI, HTTPException, File, Header, UploadFile
from fastapi.middleware.cors import CORSMiddleware
import json
import shutil
import os
from fastapi.responses import FileResponse

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


@app.post("/api/upload-db")
async def upload_database(file: UploadFile = File(...), x_api_key: str = Header(None)):
    # Simple secret key auth so random people can't overwrite your DB
    if x_api_key != os.getenv("UPLOAD_API_KEY"):
        raise HTTPException(status_code=401, detail="Unauthorized")

    db_path = "threadradar.db"

    # Write the uploaded file to disk
    with open(db_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    print(f"Database updated at {datetime.now()}")
    return {"status": "ok", "message": "Database updated successfully"}


@app.get("/api/download-db")
async def download_database(x_api_key: str = Header(None)):
    if x_api_key != os.getenv("UPLOAD_API_KEY"):
        raise HTTPException(status_code=401, detail="Unauthorized")

    db_path = "threadradar.db"
    if not os.path.exists(db_path):
        raise HTTPException(status_code=404, detail="Database not found")

    return FileResponse(
        db_path, media_type="application/octet-stream", filename="threadradar.db"
    )
