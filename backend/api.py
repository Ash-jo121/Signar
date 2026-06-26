from datetime import datetime, timezone
from pathlib import Path
from fastapi import (
    BackgroundTasks,
    FastAPI,
    HTTPException,
    File,
    Header,
    Query,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
import json
import shutil
import os
import subprocess
import sys
from fastapi.responses import FileResponse
from database import BACKTEST_COLLECTION_START_DATE, get_ticker_history
from runtime_paths import (
    analysis_lock_path,
    data_dir,
    output_json_path,
    raw_data_path,
    data_path,
)

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
LOCK_PATH = analysis_lock_path()
DATA_ROOT = data_dir()
MIN_RAW_POSTS = int(os.getenv("THREADRADAR_MIN_RAW_POSTS", "200"))
LOCK_STALE_SECONDS = int(os.getenv("THREADRADAR_ANALYSIS_LOCK_STALE_SECONDS", "21600"))
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


@app.get("/api/tickers/{symbol}/history")
def get_ticker_analysis_history(
    symbol: str,
    days: int = Query(30, ge=2, le=365),
):
    """Return daily pipeline snapshots for a ticker in chronological order."""
    ticker = symbol.upper()
    return {
        "ticker": ticker,
        "days": days,
        "start_date": BACKTEST_COLLECTION_START_DATE,
        "history": get_ticker_history(ticker, days),
    }


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


def resolve_data_file(requested_path=""):
    data_root = DATA_ROOT.resolve()
    candidate = (data_root / requested_path).resolve()
    try:
        candidate.relative_to(data_root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Path escapes data directory") from exc
    return candidate


def data_file_metadata(path):
    stat = path.stat()
    return {
        "name": path.name,
        "path": str(path.relative_to(DATA_ROOT.resolve())).replace("\\", "/"),
        "type": "directory" if path.is_dir() else "file",
        "size_bytes": stat.st_size if path.is_file() else None,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
    }


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
    elif (
        fetched_at.astimezone(timezone.utc).date() != datetime.now(timezone.utc).date()
    ):
        errors.append("stale_fetched_at")

    if len(posts) < MIN_RAW_POSTS:
        print(f"Fetch errors: {json.dumps(errors, indent=2)}")
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


def remove_stale_analysis_lock():
    if not LOCK_PATH.exists():
        return

    age_seconds = datetime.now().timestamp() - LOCK_PATH.stat().st_mtime
    if age_seconds <= LOCK_STALE_SECONDS:
        return

    print(f"Removing stale analysis lock: {LOCK_PATH}")
    LOCK_PATH.unlink(missing_ok=True)


def acquire_analysis_lock():
    remove_stale_analysis_lock()
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "pid": os.getpid(),
        "status": "queued",
    }

    try:
        fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise HTTPException(
            status_code=409,
            detail=f"Analysis already locked at {LOCK_PATH}",
        )

    with os.fdopen(fd, "w", encoding="utf-8") as lock_file:
        json.dump(payload, lock_file)


def release_analysis_lock():
    LOCK_PATH.unlink(missing_ok=True)


def run_backend_command(args):
    command = [sys.executable, *args]
    print(f"Running backend subprocess: {' '.join(command)}")
    completed = subprocess.run(
        command,
        cwd=str(Path(__file__).resolve().parent),
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"Backend subprocess failed with exit code {completed.returncode}: "
            f"{' '.join(command)}"
        )


def run_analysis_job(raw_path):
    analysis_state["running"] = True
    analysis_state["last_started_at"] = datetime.now().isoformat()
    analysis_state["last_status"] = "running"
    analysis_state["last_error"] = None
    try:
        run_backend_command(
            [
                "main.py",
                "--raw-data",
                str(raw_path),
                "--require-raw-data",
            ]
        )
        # Keep performance-price maintenance outside run_pipeline so raw snapshots
        # can be replayed/debugged without mutating historical return tracking.
        # The Railway webhook still chains it after a successful trading-day run.
        if os.getenv("THREADRADAR_RUN_PRICE_UPDATER", "1") == "1":
            output_payload = load_data()
            if output_payload.get("market_session") == "closed":
                print("Price updater skipped after analysis: market is closed")
            else:
                run_backend_command(["price_updater.py"])
        analysis_state["last_status"] = "ok"
    except Exception as exc:
        analysis_state["last_status"] = "failed"
        analysis_state["last_error"] = str(exc)
        print(f"Analysis job failed at {datetime.now()}: {exc}")
    finally:
        analysis_state["running"] = False
        analysis_state["last_finished_at"] = datetime.now().isoformat()
        release_analysis_lock()


def enqueue_analysis(background_tasks, raw_path, lock_acquired=False):
    try:
        if analysis_state["running"]:
            raise HTTPException(status_code=409, detail="Analysis already running")
        load_raw_data_for_analysis(raw_path)
        if not lock_acquired:
            acquire_analysis_lock()
    except Exception:
        if lock_acquired:
            release_analysis_lock()
        raise

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


@app.get("/api/data-files")
def list_data_files(
    path: str = Query("", description="Directory path relative to the data volume"),
    recursive: bool = Query(False),
    x_api_key: str = Header(None),
):
    authorize_upload_key(x_api_key)

    target = resolve_data_file(path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="Path not found")
    if target.is_file():
        return {
            "data_root": str(DATA_ROOT),
            "path": data_file_metadata(target)["path"],
            "entries": [data_file_metadata(target)],
        }
    if not target.is_dir():
        raise HTTPException(status_code=400, detail="Path is not listable")

    children = target.rglob("*") if recursive else target.iterdir()
    entries = sorted(
        (data_file_metadata(child) for child in children),
        key=lambda item: (item["type"] != "directory", item["path"]),
    )
    return {
        "data_root": str(DATA_ROOT),
        "path": str(target.relative_to(DATA_ROOT.resolve())).replace("\\", "/"),
        "recursive": recursive,
        "entries": entries,
    }


@app.get("/api/data-files/preview")
def preview_data_file(
    path: str = Query(..., description="File path relative to the data volume"),
    max_bytes: int = Query(200_000, ge=1, le=2_000_000),
    x_api_key: str = Header(None),
):
    authorize_upload_key(x_api_key)

    target = resolve_data_file(path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")
    if not target.is_file():
        raise HTTPException(status_code=400, detail="Path is not a file")

    with open(target, "rb") as file:
        content = file.read(max_bytes + 1)
    truncated = len(content) > max_bytes
    content = content[:max_bytes]
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=415,
            detail="File is not UTF-8 text; use /api/data-files/download",
        ) from exc

    payload = {
        **data_file_metadata(target),
        "truncated": truncated,
        "content": text,
    }
    if target.suffix.lower() == ".json" and not truncated:
        try:
            payload["json"] = json.loads(text)
        except json.JSONDecodeError:
            pass
    return payload


@app.get("/api/data-files/download")
def download_data_file(
    path: str = Query(..., description="File path relative to the data volume"),
    x_api_key: str = Header(None),
):
    authorize_upload_key(x_api_key)

    target = resolve_data_file(path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")
    if not target.is_file():
        raise HTTPException(status_code=400, detail="Path is not a file")

    return FileResponse(
        target,
        media_type="application/octet-stream",
        filename=target.name,
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

    lock_acquired = False
    if trigger_analysis:
        acquire_analysis_lock()
        lock_acquired = True

    try:
        save_raw_data_payload(payload)
    except Exception:
        if lock_acquired:
            release_analysis_lock()
        raise

    response = {
        "status": "ok",
        "message": "raw_data.json updated successfully",
        "raw_data_path": str(RAW_DATA_PATH),
        "updated_at": datetime.now().isoformat(),
    }
    if trigger_analysis:
        response.update(
            enqueue_analysis(
                background_tasks,
                RAW_DATA_PATH,
                lock_acquired=lock_acquired,
            )
        )
    return response


@app.post("/api/run-analysis")
async def run_analysis(
    background_tasks: BackgroundTasks, x_api_key: str = Header(None)
):
    authorize_upload_key(x_api_key)
    return enqueue_analysis(background_tasks, RAW_DATA_PATH)


@app.get("/api/analysis-status")
def get_analysis_status(x_api_key: str = Header(None)):
    authorize_upload_key(x_api_key)
    return {
        **analysis_state,
        "lock_exists": LOCK_PATH.exists(),
        "lock_path": str(LOCK_PATH),
    }
