from datetime import datetime, timezone
from fastapi import BackgroundTasks, FastAPI, HTTPException, File, Header, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
import json
import shutil
import os
from fastapi.responses import FileResponse
from runtime_paths import output_json_path, raw_data_path, data_path

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Runtime artifacts live on Railway's mounted /data volume in production.
# Locally these helpers fall back to backend/, unless THREADRADAR_* path envs are set.
DATA_PATH = output_json_path()
RAW_DATA_PATH = raw_data_path()
DB_PATH = data_path("threadradar.db")
MIN_RAW_POSTS = int(os.getenv("THREADRADAR_MIN_RAW_POSTS", "25"))
analysis_state = {
    "running": False,
    "last_started_at": None,
    "last_finished_at": None,
    "last_status": None,
    "last_error": None,
}


def load_data():
    if not DATA_PATH.exists():
        return {}
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def iter_tickers(data):
    if isinstance(data, list):
        yield from data
        return

    if isinstance(data, dict):
        for key in (
            "best_trade_candidates",
            "radar_watchlist",
            "avoid_high_risk",
            "near_miss_candidates",
        ):
            for item in data.get(key, []):
                yield item


@app.get("/api/tickers")
def get_tickers():
    return load_data()


@app.get("/api/tickers/{symbol}")  # pyright: ignore[reportUndefinedVariable]
def get_ticker(symbol: str):
    data = load_data()
    result = next(
        (r for r in iter_tickers(data) if r["ticker"] == symbol.upper()),
        None,
    )
    if not result:
        return {"error": "Ticker not found"}
    return result


@app.get("/health")
def health():
    return {"status": "ok"}


def authorize_upload_key(x_api_key):
    expected = os.getenv("UPLOAD_API_KEY")
    if not expected or x_api_key != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")


def parse_iso_datetime(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def validate_raw_data_payload(payload):
    """Reject stale/corrupt raw snapshots before they can mutate DB state."""
    errors = []
    if not isinstance(payload, dict):
        return ["raw_data must be a JSON object"]

    posts = payload.get("posts")
    if not isinstance(posts, list):
        errors.append("missing_or_invalid_posts")
        posts = []

    fetched_at = parse_iso_datetime(payload.get("fetched_at"))
    if fetched_at is None:
        errors.append("missing_or_invalid_fetched_at")
    elif fetched_at.astimezone(timezone.utc).date() != datetime.now(timezone.utc).date():
        errors.append("stale_fetched_at")

    if len(posts) < MIN_RAW_POSTS:
        errors.append(f"too_few_posts:{len(posts)}<{MIN_RAW_POSTS}")

    missing_subreddit = sum(
        1 for post in posts if not isinstance(post, dict) or not post.get("subreddit")
    )
    if missing_subreddit:
        errors.append(f"missing_subreddit:{missing_subreddit}")

    return errors


def load_raw_data_for_analysis(raw_path):
    try:
        with open(raw_path, "r", encoding="utf-8") as file:
            payload = json.load(file)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="raw_data.json not found")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"invalid_json:{exc}") from exc

    validation_errors = validate_raw_data_payload(payload)
    if validation_errors:
        print(f"Raw data validation failed: {validation_errors}")
        raise HTTPException(status_code=422, detail=validation_errors)

    return payload


def save_raw_data_payload(payload):
    RAW_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp_path = RAW_DATA_PATH.with_name(f"{RAW_DATA_PATH.name}.tmp")
    with open(temp_path, "w", encoding="utf-8") as buffer:
        json.dump(payload, buffer, indent=2, ensure_ascii=False)
    os.replace(temp_path, RAW_DATA_PATH)


def run_analysis_job(raw_path):
    analysis_state["running"] = True
    analysis_state["last_started_at"] = datetime.now().isoformat()
    analysis_state["last_status"] = "running"
    analysis_state["last_error"] = None
    try:
        from main import run_pipeline

        output_payload = run_pipeline(raw_data_file=str(raw_path))
        # Keep performance-price maintenance outside run_pipeline so raw snapshots
        # can be replayed/debugged without mutating historical return tracking.
        # The Railway webhook still chains it after a successful trading-day run.
        if os.getenv("THREADRADAR_RUN_PRICE_UPDATER", "1") == "1":
            if output_payload.get("market_session") == "closed":
                print("Price updater skipped after analysis: market is closed")
            else:
                from price_updater import update_performance_prices

                update_performance_prices()
        analysis_state["last_status"] = "ok"
    except Exception as exc:
        analysis_state["last_status"] = "failed"
        analysis_state["last_error"] = str(exc)
        print(f"Analysis job failed at {datetime.now()}: {exc}")
    finally:
        analysis_state["running"] = False
        analysis_state["last_finished_at"] = datetime.now().isoformat()


def enqueue_analysis(background_tasks, raw_path):
    if analysis_state["running"]:
        raise HTTPException(status_code=409, detail="Analysis already running")
    load_raw_data_for_analysis(raw_path)
    analysis_state["running"] = True
    analysis_state["last_status"] = "queued"
    analysis_state["last_error"] = None
    background_tasks.add_task(run_analysis_job, raw_path)
    return {
        "analysis": "queued",
        "raw_data_path": str(raw_path),
    }


@app.post("/api/upload-output")
async def upload_output(file: UploadFile = File(...), x_api_key: str = Header(None)):
    authorize_upload_key(x_api_key)

    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DATA_PATH, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    print(f"output.json updated at {datetime.now()}")
    return {"status": "ok", "message": "output.json updated successfully"}


@app.post("/api/upload-db")
async def upload_database(file: UploadFile = File(...), x_api_key: str = Header(None)):
    authorize_upload_key(x_api_key)

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DB_PATH, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    print(f"Database updated at {datetime.now()}")
    return {"status": "ok", "message": "Database updated successfully"}


@app.get("/api/download-db")
async def download_database(x_api_key: str = Header(None)):
    authorize_upload_key(x_api_key)

    if not DB_PATH.exists():
        raise HTTPException(status_code=404, detail="Database not found")

    return FileResponse(
        DB_PATH, media_type="application/octet-stream", filename="threadradar.db"
    )


@app.post("/api/upload-raw-data")
async def upload_raw_data(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    x_api_key: str = Header(None),
    trigger_analysis: bool = Query(False),
):
    authorize_upload_key(x_api_key)

    try:
        payload = json.load(file.file)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"invalid_json:{exc}") from exc

    validation_errors = validate_raw_data_payload(payload)
    if validation_errors:
        analysis_state["last_status"] = "raw_validation_failed"
        analysis_state["last_error"] = ", ".join(validation_errors)
        print(f"Raw data upload rejected: {validation_errors}")
        raise HTTPException(status_code=422, detail=validation_errors)

    save_raw_data_payload(payload)

    response = {
        "status": "ok",
        "message": "raw_data.json updated successfully",
        "raw_data_path": str(RAW_DATA_PATH),
        "updated_at": datetime.now().isoformat(),
    }
    if trigger_analysis:
        response.update(enqueue_analysis(background_tasks, RAW_DATA_PATH))
    return response


@app.post("/api/run-analysis")
async def run_analysis(background_tasks: BackgroundTasks, x_api_key: str = Header(None)):
    authorize_upload_key(x_api_key)
    return enqueue_analysis(background_tasks, RAW_DATA_PATH)


@app.get("/api/analysis-status")
def get_analysis_status(x_api_key: str = Header(None)):
    authorize_upload_key(x_api_key)
    return analysis_state
