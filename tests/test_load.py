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


@pytest.fixture
def tmp_db(tmp_path):
    db_path = tmp_path / "test_energy.db"
    init_db(db_path)
    return db_path


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


class TestInitDb:
    def test_creates_all_tables(self, tmp_db):
        with get_connection(tmp_db) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        assert {"generation_fact", "generation_summary", "pipeline_runs"} <= tables

    def test_idempotent(self, tmp_db):
        init_db(tmp_db)
        init_db(tmp_db)
        with get_connection(tmp_db) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        assert {"generation_fact", "generation_summary", "pipeline_runs"} <= tables


class TestLoadGenerationFact:
    def test_loads_correct_row_count(self, tmp_db, sample_fact_df):
        rows = load_generation_fact(sample_fact_df, tmp_db)
        assert rows == 3

    def test_data_persisted(self, tmp_db, sample_fact_df):
        load_generation_fact(sample_fact_df, tmp_db)
        with get_connection(tmp_db) as conn:
            count = conn.execute("SELECT COUNT(*) FROM generation_fact").fetchone()[0]
        assert count == 3

    def test_upsert_deduplicates(self, tmp_db, sample_fact_df):
        load_generation_fact(sample_fact_df, tmp_db)
        load_generation_fact(sample_fact_df, tmp_db)
        with get_connection(tmp_db) as conn:
            count = conn.execute("SELECT COUNT(*) FROM generation_fact").fetchone()[0]
        assert count == 3

    def test_missing_required_columns_raises(self, tmp_db):
        bad_df = pd.DataFrame({"timestamp": ["2024-01-01"], "country_code": ["IE"]})
        with pytest.raises(ValueError, match="Missing columns"):
            load_generation_fact(bad_df, tmp_db)

    def test_works_without_optional_columns(self, tmp_db):
        df = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(["2024-01-01"]),
                "country_code": ["IE"],
                "fuel_type": ["Wind Onshore"],
                "generation_mw": [500.0],
            }
        )
        rows = load_generation_fact(df, tmp_db)
        assert rows == 1

    def test_is_renewable_stored_as_int(self, tmp_db, sample_fact_df):
        load_generation_fact(sample_fact_df, tmp_db)
        with get_connection(tmp_db) as conn:
            rows = conn.execute(
                "SELECT is_renewable FROM generation_fact"
            ).fetchall()
        for (val,) in rows:
            assert val in (0, 1)


class TestLoadGenerationSummary:
    def test_loads_correct_row_count(self, tmp_db, sample_summary_df):
        rows = load_generation_summary(sample_summary_df, tmp_db)
        assert rows == 2

    def test_upsert_deduplicates(self, tmp_db, sample_summary_df):
        load_generation_summary(sample_summary_df, tmp_db)
        load_generation_summary(sample_summary_df, tmp_db)
        with get_connection(tmp_db) as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM generation_summary"
            ).fetchone()[0]
        assert count == 2

    def test_missing_required_columns_raises(self, tmp_db):
        bad_df = pd.DataFrame({"timestamp": ["2024-01-01"]})
        with pytest.raises(ValueError, match="Missing columns"):
            load_generation_summary(bad_df, tmp_db)

    def test_partial_columns_accepted(self, tmp_db):
        df = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(["2024-01-01"]),
                "country_code": ["IE"],
                "total_generation_mw": [1300.0],
            }
        )
        rows = load_generation_summary(df, tmp_db)
        assert rows == 1


class TestLogPipelineRun:
    def test_creates_run_record(self, tmp_db):
        log_pipeline_run("entsoe", 100, "success", db_path=tmp_db)
        with get_connection(tmp_db) as conn:
            row = conn.execute("SELECT source, rows_loaded, status FROM pipeline_runs").fetchone()
        assert row == ("entsoe", 100, "success")

    def test_failure_run_recorded(self, tmp_db):
        log_pipeline_run("eirgrid", 0, "failed", message="API timeout", db_path=tmp_db)
        with get_connection(tmp_db) as conn:
            row = conn.execute(
                "SELECT status, message FROM pipeline_runs"
            ).fetchone()
        assert row == ("failed", "API timeout")

    def test_multiple_runs_stored(self, tmp_db):
        log_pipeline_run("entsoe", 10, "success", db_path=tmp_db)
        log_pipeline_run("entsoe", 20, "success", db_path=tmp_db)
        with get_connection(tmp_db) as conn:
            count = conn.execute("SELECT COUNT(*) FROM pipeline_runs").fetchone()[0]
        assert count == 2


class TestQueryGenerationSummary:
    def test_returns_dataframe(self, tmp_db, sample_summary_df):
        load_generation_summary(sample_summary_df, tmp_db)
        result = query_generation_summary("IE", db_path=tmp_db)
        assert isinstance(result, pd.DataFrame)

    def test_correct_row_count(self, tmp_db, sample_summary_df):
        load_generation_summary(sample_summary_df, tmp_db)
        result = query_generation_summary("IE", db_path=tmp_db)
        assert len(result) == 2

    def test_limit_respected(self, tmp_db, sample_summary_df):
        load_generation_summary(sample_summary_df, tmp_db)
        result = query_generation_summary("IE", limit=1, db_path=tmp_db)
        assert len(result) == 1

    def test_empty_for_unknown_country(self, tmp_db, sample_summary_df):
        load_generation_summary(sample_summary_df, tmp_db)
        result = query_generation_summary("DE", db_path=tmp_db)
        assert result.empty


class TestQueryGenerationFact:
    def test_returns_dataframe(self, tmp_db, sample_fact_df):
        load_generation_fact(sample_fact_df, tmp_db)
        result = query_generation_fact("IE", db_path=tmp_db)
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 3
