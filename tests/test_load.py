import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from load_db import (
    get_connection,
    init_db,
    load_generation_fact,
    load_generation_summary,
    log_pipeline_run,
    query_generation_fact,
    query_generation_summary,
)


@pytest.fixture(autouse=True)
def clean_db():
    """Run against the real local Postgres (docker-compose). Truncating
    before each test gives isolation without needing a separate database
    per test - simpler than that, and still exercises real constraints
    (UNIQUE, NOT NULL) that a mocked connection never would.
    """
    init_db()
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "TRUNCATE generation_fact, generation_summary, pipeline_runs RESTART IDENTITY CASCADE"
        )


@pytest.fixture
def sample_fact_df():
    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                ["2024-01-01 00:00", "2024-01-01 00:00", "2024-01-01 00:15"]
            ),
            "country_code": ["IE", "IE", "IE"],
            "fuel_type": ["Fossil Gas", "Wind Onshore", "Fossil Gas"],
            "generation_mw": [800.0, 500.0, 820.0],
            "is_renewable": [False, True, False],
            "processed_at": pd.to_datetime(
                ["2024-01-01 01:00", "2024-01-01 01:00", "2024-01-01 01:00"]
            ),
        }
    )


@pytest.fixture
def sample_summary_df():
    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2024-01-01 00:00", "2024-01-01 00:15"]),
            "country_code": ["IE", "IE"],
            "total_generation_mw": [1300.0, 820.0],
            "renewable_mw": [500.0, 0.0],
            "renewable_pct": [38.46, 0.0],
            "carbon_intensity_g_per_kwh": [301.5, 490.0],
            "processed_at": pd.to_datetime(["2024-01-01 01:00", "2024-01-01 01:00"]),
        }
    )


def _table_names() -> set:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
        return {row[0] for row in cur.fetchall()}


class TestInitDb:
    def test_creates_all_tables(self):
        assert {"generation_fact", "generation_summary", "pipeline_runs"} <= _table_names()

    def test_idempotent(self):
        init_db()
        init_db()
        assert {"generation_fact", "generation_summary", "pipeline_runs"} <= _table_names()


class TestLoadGenerationFact:
    def test_loads_correct_row_count(self, sample_fact_df):
        rows = load_generation_fact(sample_fact_df)
        assert rows == 3

    def test_data_persisted(self, sample_fact_df):
        load_generation_fact(sample_fact_df)
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM generation_fact")
            count = cur.fetchone()[0]
        assert count == 3

    def test_upsert_deduplicates(self, sample_fact_df):
        load_generation_fact(sample_fact_df)
        load_generation_fact(sample_fact_df)
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM generation_fact")
            count = cur.fetchone()[0]
        assert count == 3

    def test_missing_required_columns_raises(self):
        bad_df = pd.DataFrame({"timestamp": ["2024-01-01"], "country_code": ["IE"]})
        with pytest.raises(ValueError, match="Missing columns"):
            load_generation_fact(bad_df)

    def test_works_without_optional_columns(self):
        df = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(["2024-01-01"]),
                "country_code": ["IE"],
                "fuel_type": ["Wind Onshore"],
                "generation_mw": [500.0],
            }
        )
        rows = load_generation_fact(df)
        assert rows == 1

    def test_is_renewable_stored_as_boolean(self, sample_fact_df):
        load_generation_fact(sample_fact_df)
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT is_renewable FROM generation_fact")
            rows = cur.fetchall()
        for (val,) in rows:
            assert isinstance(val, bool)


class TestLoadGenerationSummary:
    def test_loads_correct_row_count(self, sample_summary_df):
        rows = load_generation_summary(sample_summary_df)
        assert rows == 2

    def test_upsert_deduplicates(self, sample_summary_df):
        load_generation_summary(sample_summary_df)
        load_generation_summary(sample_summary_df)
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM generation_summary")
            count = cur.fetchone()[0]
        assert count == 2

    def test_missing_required_columns_raises(self):
        bad_df = pd.DataFrame({"timestamp": ["2024-01-01"]})
        with pytest.raises(ValueError, match="Missing columns"):
            load_generation_summary(bad_df)

    def test_partial_columns_accepted(self):
        df = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(["2024-01-01"]),
                "country_code": ["IE"],
                "total_generation_mw": [1300.0],
            }
        )
        rows = load_generation_summary(df)
        assert rows == 1


class TestLogPipelineRun:
    def test_creates_run_record(self):
        log_pipeline_run("entsoe", 100, "success")
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT source, rows_loaded, status FROM pipeline_runs")
            row = cur.fetchone()
        assert row == ("entsoe", 100, "success")

    def test_failure_run_recorded(self):
        log_pipeline_run("carbon_intensity", 0, "failed", message="API timeout")
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT status, message FROM pipeline_runs")
            row = cur.fetchone()
        assert row == ("failed", "API timeout")

    def test_multiple_runs_stored(self):
        log_pipeline_run("entsoe", 10, "success")
        log_pipeline_run("entsoe", 20, "success")
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM pipeline_runs")
            count = cur.fetchone()[0]
        assert count == 2


class TestQueryGenerationSummary:
    def test_returns_dataframe(self, sample_summary_df):
        load_generation_summary(sample_summary_df)
        result = query_generation_summary("IE")
        assert isinstance(result, pd.DataFrame)

    def test_correct_row_count(self, sample_summary_df):
        load_generation_summary(sample_summary_df)
        result = query_generation_summary("IE")
        assert len(result) == 2

    def test_limit_respected(self, sample_summary_df):
        load_generation_summary(sample_summary_df)
        result = query_generation_summary("IE", limit=1)
        assert len(result) == 1

    def test_empty_for_unknown_country(self, sample_summary_df):
        load_generation_summary(sample_summary_df)
        result = query_generation_summary("DE")
        assert result.empty


class TestQueryGenerationFact:
    def test_returns_dataframe(self, sample_fact_df):
        load_generation_fact(sample_fact_df)
        result = query_generation_fact("IE")
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 3
