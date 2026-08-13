import json
import logging
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

import pandas as pd
import psycopg2
import psycopg2.extensions
from psycopg2.extras import Json, RealDictCursor, execute_values

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


class RawStoreError(Exception):
    pass


class PostgresDatabase:
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

    _CREATE_RAW_INGESTIONS = """
    CREATE TABLE IF NOT EXISTS raw_ingestions (
        id          SERIAL PRIMARY KEY,
        source      TEXT NOT NULL,
        ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        format      TEXT NOT NULL,
        payload     JSONB NOT NULL
    )
    """

    # No UNIQUE constraint on raw_ingestions (unlike the other three tables)
    # to create one implicitly, so get_recent_raw()'s
    # WHERE source = %s ORDER BY id DESC needs this explicitly.
    _CREATE_RAW_INGESTIONS_INDEX = """
    CREATE INDEX IF NOT EXISTS idx_raw_ingestions_source_id
        ON raw_ingestions (source, id DESC)
    """

    def __init__(
        self,
        host: str = POSTGRES_HOST,
        port: int = POSTGRES_PORT,
        dbname: str = POSTGRES_DB,
        user: str = POSTGRES_USER,
        password: str = POSTGRES_PASSWORD,
    ):
        self.host = host
        self.port = port
        self.dbname = dbname
        self.user = user
        self.password = password

    @contextmanager
    def connection(self) -> Generator[psycopg2.extensions.connection, None, None]:
        conn = psycopg2.connect(
            host=self.host,
            port=self.port,
            dbname=self.dbname,
            user=self.user,
            password=self.password,
        )
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_db(self) -> None:
        logger.info(f"Initialising database at {self.host}:{self.port}/{self.dbname}")
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute(self._CREATE_GENERATION_FACT)
            cur.execute(self._CREATE_GENERATION_SUMMARY)
            cur.execute(self._CREATE_PIPELINE_RUNS)
            cur.execute(self._CREATE_RAW_INGESTIONS)
            cur.execute(self._CREATE_RAW_INGESTIONS_INDEX)
        logger.info("Database initialised")

    def load_generation_fact(self, df: pd.DataFrame) -> int:
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

        cols = [
            "timestamp",
            "country_code",
            "fuel_type",
            "generation_mw",
            "is_renewable",
            "processed_at",
        ]
        rows = records[cols].values.tolist()

        with self.connection() as conn, conn.cursor() as cur:
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

    def load_generation_summary(self, df: pd.DataFrame) -> int:
        required = {"timestamp", "country_code"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"Missing columns: {missing}")

        optional_columns = {
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

        for col in optional_columns:
            if col not in records.columns:
                records[col] = None

        optional_cols = sorted(optional_columns)
        cols = ["timestamp", "country_code"] + optional_cols
        rows = records[cols].values.tolist()

        with self.connection() as conn, conn.cursor() as cur:
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
        self,
        source: str,
        rows_loaded: int,
        status: str,
        message: str | None = None,
    ) -> None:
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO pipeline_runs (run_at, source, rows_loaded, status, message)
                VALUES (now(), %s, %s, %s, %s)
                """,
                (source, rows_loaded, status, message),
            )
        logger.info(f"Logged pipeline run: source={source}, status={status}, rows={rows_loaded}")

    def query_generation_summary(self, country_code: str = "IE", limit: int = 100) -> pd.DataFrame:
        with self.connection() as conn:
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

    def query_generation_fact(self, country_code: str = "IE", limit: int = 500) -> pd.DataFrame:
        with self.connection() as conn:
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

    def save_raw(
        self, source: str, data: pd.DataFrame | dict | list, format_hint: str = "records"
    ) -> str:
        """Store a raw ingested payload as-is. Returns the new row's id as a string.

        DataFrames are stored via to_dict("records") - one JSONB field per
        column, matching how each source's JSON naturally varies rather than
        forcing a fixed schema across sources.
        """
        if isinstance(data, pd.DataFrame):
            payload = data.reset_index().to_dict(orient="records")
        else:
            payload = data

        try:
            with self.connection() as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO raw_ingestions (source, format, payload)
                    VALUES (%s, %s, %s)
                    RETURNING id
                    """,
                    (
                        source,
                        format_hint,
                        # DataFrame indexes (e.g. pandas Timestamps) aren't
                        # JSON-serializable by stdlib json, which Json() uses
                        # by default - stringify anything it doesn't know
                        # instead of failing the save.
                        Json(payload, dumps=lambda obj: json.dumps(obj, default=str)),
                    ),
                )
                raw_id = cur.fetchone()[0]
            logger.info(f"Saved raw {source} row {raw_id}")
            return str(raw_id)
        except Exception as e:
            logger.error(f"Failed to save raw {source} row: {e}")
            raise RawStoreError(str(e)) from e

    def get_recent_raw(self, source: str, limit: int = 10) -> list[dict[str, Any]]:
        # Sort by id, not ingested_at: rapid successive inserts can tie on
        # ingested_at. A SERIAL id is monotonically increasing and unique,
        # so it sorts reliably.
        with self.connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, source, ingested_at, format, payload
                FROM raw_ingestions
                WHERE source = %s
                ORDER BY id DESC
                LIMIT %s
                """,
                (source, limit),
            )
            return [dict(row) for row in cur.fetchall()]
