import logging
from collections.abc import Generator
from contextlib import contextmanager

import pandas as pd
import psycopg2
import psycopg2.extensions
from psycopg2.extras import execute_values

try:
    from src.config import (
        LOG_DATE_FORMAT,
        LOG_FORMAT,
        LOG_LEVEL,
        POSTGRES_DB,
        POSTGRES_HOST,
        POSTGRES_PASSWORD,
        POSTGRES_PORT,
        POSTGRES_USER,
    )
except ImportError:
    from config import (
        LOG_DATE_FORMAT,
        LOG_FORMAT,
        LOG_LEVEL,
        POSTGRES_DB,
        POSTGRES_HOST,
        POSTGRES_PASSWORD,
        POSTGRES_PORT,
        POSTGRES_USER,
    )

logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
logger = logging.getLogger(__name__)

_CREATE_GENERATION_FACT = """
CREATE TABLE IF NOT EXISTS generation_fact (
    id            SERIAL PRIMARY KEY,
    timestamp     TIMESTAMPTZ NOT NULL,
    country_code  TEXT NOT NULL,
    fuel_type     TEXT NOT NULL,
    generation_mw DOUBLE PRECISION NOT NULL,
    is_renewable  BOOLEAN NOT NULL DEFAULT FALSE,
    processed_at  TIMESTAMPTZ,
    UNIQUE (timestamp, country_code, fuel_type)
)
"""

_CREATE_GENERATION_SUMMARY = """
CREATE TABLE IF NOT EXISTS generation_summary (
    id                          SERIAL PRIMARY KEY,
    timestamp                   TIMESTAMPTZ NOT NULL,
    country_code                TEXT NOT NULL,
    total_generation_mw         DOUBLE PRECISION,
    renewable_mw                DOUBLE PRECISION,
    renewable_pct                DOUBLE PRECISION,
    carbon_intensity_g_per_kwh   DOUBLE PRECISION,
    processed_at                 TIMESTAMPTZ,
    UNIQUE (timestamp, country_code)
)
"""

_CREATE_PIPELINE_RUNS = """
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id          SERIAL PRIMARY KEY,
    run_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    source      TEXT NOT NULL,
    rows_loaded INTEGER,
    status      TEXT NOT NULL,
    message     TEXT
)
"""


@contextmanager
def get_connection() -> Generator[psycopg2.extensions.connection, None, None]:
    conn = psycopg2.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        dbname=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
    )
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    logger.info(f"Initialising database at {POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}")
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(_CREATE_GENERATION_FACT)
        cur.execute(_CREATE_GENERATION_SUMMARY)
        cur.execute(_CREATE_PIPELINE_RUNS)
    logger.info("Database initialised")


def load_generation_fact(df: pd.DataFrame) -> int:
    required = {"timestamp", "country_code", "fuel_type", "generation_mw"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns: {missing}")

    records = df.copy()
    records["timestamp"] = records["timestamp"].astype(str)
    records["is_renewable"] = records.get(
        "is_renewable", pd.Series(False, index=records.index)
    ).astype(bool)
    records["processed_at"] = (
        records["processed_at"].astype(str) if "processed_at" in records.columns else None
    )

    cols = ["timestamp", "country_code", "fuel_type", "generation_mw", "is_renewable", "processed_at"]
    rows = records[cols].values.tolist()

    with get_connection() as conn, conn.cursor() as cur:
        execute_values(
            cur,
            """
            INSERT INTO generation_fact
                (timestamp, country_code, fuel_type, generation_mw, is_renewable, processed_at)
            VALUES %s
            ON CONFLICT (timestamp, country_code, fuel_type) DO UPDATE SET
                generation_mw = EXCLUDED.generation_mw,
                is_renewable  = EXCLUDED.is_renewable,
                processed_at  = EXCLUDED.processed_at
            """,
            rows,
        )

    logger.info(f"Loaded {len(rows)} rows into generation_fact")
    return len(rows)


def load_generation_summary(df: pd.DataFrame) -> int:
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
    records = df.copy()
    records["timestamp"] = records["timestamp"].astype(str)
    if "processed_at" in records.columns:
        records["processed_at"] = records["processed_at"].astype(str)

    for col in optional:
        if col not in records.columns:
            records[col] = None

    optional_cols = sorted(optional)
    cols = ["timestamp", "country_code"] + optional_cols
    rows = records[cols].values.tolist()

    with get_connection() as conn, conn.cursor() as cur:
        execute_values(
            cur,
            f"""
            INSERT INTO generation_summary
                (timestamp, country_code, {", ".join(optional_cols)})
            VALUES %s
            ON CONFLICT (timestamp, country_code) DO UPDATE SET
                {", ".join(f"{c} = EXCLUDED.{c}" for c in optional_cols)}
            """,
            rows,
        )

    logger.info(f"Loaded {len(rows)} rows into generation_summary")
    return len(rows)


def log_pipeline_run(
    source: str,
    rows_loaded: int,
    status: str,
    message: str | None = None,
) -> None:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO pipeline_runs (run_at, source, rows_loaded, status, message)
            VALUES (now(), %s, %s, %s, %s)
            """,
            (source, rows_loaded, status, message),
        )
    logger.info(f"Logged pipeline run: source={source}, status={status}, rows={rows_loaded}")


def query_generation_summary(country_code: str = "IE", limit: int = 100) -> pd.DataFrame:
    with get_connection() as conn:
        return pd.read_sql_query(
            """
            SELECT * FROM generation_summary
            WHERE country_code = %s
            ORDER BY timestamp DESC
            LIMIT %s
            """,
            conn,
            params=(country_code, limit),
        )


def query_generation_fact(country_code: str = "IE", limit: int = 500) -> pd.DataFrame:
    with get_connection() as conn:
        return pd.read_sql_query(
            """
            SELECT * FROM generation_fact
            WHERE country_code = %s
            ORDER BY timestamp DESC
            LIMIT %s
            """,
            conn,
            params=(country_code, limit),
        )
