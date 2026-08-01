import os
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent


def data_dir():
    # Priority:
    # 1. explicit override for tests/local jobs,
    # 2. Railway's persistent volume when mounted,
    # 3. backend/ for normal local development.
    configured = os.getenv("THREADRADAR_DATA_DIR")
    if configured:
        return Path(configured)

    railway_volume = Path("/data")
    if railway_volume.exists():
        return railway_volume

    return BACKEND_DIR


def data_path(filename):
    return data_dir() / filename


def raw_data_path():
    return Path(os.getenv("THREADRADAR_RAW_DATA_PATH", data_path("raw_data.json")))


def output_json_path():
    return Path(os.getenv("THREADRADAR_OUTPUT_JSON_PATH", data_path("output.json")))


def output_txt_path():
    return Path(os.getenv("THREADRADAR_OUTPUT_TXT_PATH", data_path("output.txt")))


def output_archive_dir():
    return Path(os.getenv("THREADRADAR_OUTPUT_ARCHIVE_DIR", data_path("output")))


def run_summaries_path():
    return Path(
        os.getenv(
            "THREADRADAR_RUN_SUMMARIES_PATH",
            data_path("run_summaries.jsonl"),
        )
    )


def analysis_lock_path():
    return Path(os.getenv("THREADRADAR_ANALYSIS_LOCK_PATH", data_path("analysis.lock")))
