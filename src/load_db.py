import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

import pandas as pd

from config import DATA_DIR, LOG_FORMAT, LOG_DATE_FORMAT, LOG_LEVEL

logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
logger = logging.getLogger(__name__)

DB_PATH = DATA_DIR / "energy.db"

_CREATE_GENERATION_FACT = """
CREATE TABLE IF NOT EXISTS generation_fact (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT    NOT NULL,
    country_code TEXT   NOT NULL,
    fuel_type   TEXT    NOT NULL,
    generation_mw REAL  NOT NULL,
    is_renewable  INTEGER NOT NULL DEFAULT 0,
    processed_at  TEXT,
    UNIQUE(timestamp, country_code, fuel_type)
)
"""

_CREATE_GENERATION_SUMMARY = """
CREATE TABLE IF NOT EXISTS generation_summary (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp                TEXT    NOT NULL,
    country_code             TEXT    NOT NULL,
    total_generation_mw      REAL,
    renewable_mw             REAL,
    renewable_pct            REAL,
    carbon_intensity_g_per_kwh REAL,
    processed_at             TEXT,
    UNIQUE(timestamp, country_code)
)
"""

_CREATE_PIPELINE_RUNS = """
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at      TEXT    NOT NULL,
    source      TEXT    NOT NULL,
    rows_loaded INTEGER,
    status      TEXT    NOT NULL,
    message     TEXT
)
"""


@contextmanager
def get_connection(db_path: Path = DB_PATH) -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path = DB_PATH) -> None:
    logger.info(f"Initialising database at {db_path}")
    with get_connection(db_path) as conn:
        conn.execute(_CREATE_GENERATION_FACT)
        conn.execute(_CREATE_GENERATION_SUMMARY)
        conn.execute(_CREATE_PIPELINE_RUNS)
    logger.info("Database initialised")


def load_generation_fact(df: pd.DataFrame, db_path: Path = DB_PATH) -> int:
    required = {"timestamp", "country_code", "fuel_type", "generation_mw"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns: {missing}")

    optional = {"is_renewable", "processed_at"}
    cols = list(required | (optional & set(df.columns)))
    records = df[cols].copy()

    records["timestamp"] = records["timestamp"].astype(str)
    records["is_renewable"] = records.get("is_renewable", pd.Series(0, index=records.index)).astype(int)
    records["processed_at"] = records["processed_at"].astype(str) if "processed_at" in records.columns else None

    with get_connection(db_path) as conn:
        cursor = conn.executemany(
            """
            INSERT OR REPLACE INTO generation_fact
                (timestamp, country_code, fuel_type, generation_mw, is_renewable, processed_at)
            VALUES (:timestamp, :country_code, :fuel_type, :generation_mw,
                    :is_renewable, :processed_at)
            """,
            records.to_dict("records"),
        )
        rows = cursor.rowcount

    logger.info(f"Loaded {rows} rows into generation_fact")
    return rows


def load_generation_summary(df: pd.DataFrame, db_path: Path = DB_PATH) -> int:
    required = {"timestamp", "country_code"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns: {missing}")

    optional = {
        "total_generation_mw",
        "renewable_mw",
        "renewable_pct",
        "carbon_intensity_g_per_kwh",
        "processed_at",
    }
    cols = list(required | (optional & set(df.columns)))
    records = df[cols].copy()

    records["timestamp"] = records["timestamp"].astype(str)
    if "processed_at" in records.columns:
        records["processed_at"] = records["processed_at"].astype(str)

    for col in optional:
        if col not in records.columns:
            records[col] = None

    with get_connection(db_path) as conn:
        cursor = conn.executemany(
            """
            INSERT OR REPLACE INTO generation_summary
                (timestamp, country_code, total_generation_mw, renewable_mw,
                 renewable_pct, carbon_intensity_g_per_kwh, processed_at)
            VALUES (:timestamp, :country_code, :total_generation_mw, :renewable_mw,
                    :renewable_pct, :carbon_intensity_g_per_kwh, :processed_at)
            """,
            records.to_dict("records"),
        )
        rows = cursor.rowcount

    logger.info(f"Loaded {rows} rows into generation_summary")
    return rows


def log_pipeline_run(
    source: str,
    rows_loaded: int,
    status: str,
    message: Optional[str] = None,
    db_path: Path = DB_PATH,
) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO pipeline_runs (run_at, source, rows_loaded, status, message)
            VALUES (datetime('now'), ?, ?, ?, ?)
            """,
            (source, rows_loaded, status, message),
        )
    logger.info(f"Logged pipeline run: source={source}, status={status}, rows={rows_loaded}")


def query_generation_summary(
    country_code: str = "IE",
    limit: int = 100,
    db_path: Path = DB_PATH,
) -> pd.DataFrame:
    with get_connection(db_path) as conn:
        return pd.read_sql_query(
            """
            SELECT * FROM generation_summary
            WHERE country_code = ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            conn,
            params=(country_code, limit),
        )


def query_generation_fact(
    country_code: str = "IE",
    limit: int = 500,
    db_path: Path = DB_PATH,
) -> pd.DataFrame:
    with get_connection(db_path) as conn:
        return pd.read_sql_query(
            """
            SELECT * FROM generation_fact
            WHERE country_code = ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            conn,
            params=(country_code, limit),
        )
