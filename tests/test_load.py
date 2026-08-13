import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from load_db import PostgresDatabase


@pytest.fixture
def db():
    return PostgresDatabase()


@pytest.fixture(autouse=True)
def clean_db(db):
    """Run against the real local Postgres (docker-compose). Truncating
    before each test gives isolation without needing a separate database
    per test - simpler than that, and still exercises real constraints
    (UNIQUE, NOT NULL) that a mocked connection never would.
    """
    db.init_db()
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            "TRUNCATE generation_fact, generation_summary, pipeline_runs, raw_ingestions "
            "RESTART IDENTITY CASCADE"
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


def _table_names(db) -> set:
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
        return {row[0] for row in cur.fetchall()}


class TestInitDb:
    def test_creates_all_tables(self, db):
        assert {
            "generation_fact",
            "generation_summary",
            "pipeline_runs",
            "raw_ingestions",
        } <= _table_names(db)

    def test_idempotent(self, db):
        db.init_db()
        db.init_db()
        assert {
            "generation_fact",
            "generation_summary",
            "pipeline_runs",
            "raw_ingestions",
        } <= _table_names(db)


class TestLoadGenerationFact:
    def test_loads_correct_row_count(self, db, sample_fact_df):
        rows = db.load_generation_fact(sample_fact_df)
        assert rows == 3

    def test_data_persisted(self, db, sample_fact_df):
        db.load_generation_fact(sample_fact_df)
        with db.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM generation_fact")
            count = cur.fetchone()[0]
        assert count == 3

    def test_upsert_deduplicates(self, db, sample_fact_df):
        db.load_generation_fact(sample_fact_df)
        db.load_generation_fact(sample_fact_df)
        with db.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM generation_fact")
            count = cur.fetchone()[0]
        assert count == 3

    def test_missing_required_columns_raises(self, db):
        bad_df = pd.DataFrame({"timestamp": ["2024-01-01"], "country_code": ["IE"]})
        with pytest.raises(ValueError, match="Missing columns"):
            db.load_generation_fact(bad_df)

    def test_works_without_optional_columns(self, db):
        df = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(["2024-01-01"]),
                "country_code": ["IE"],
                "fuel_type": ["Wind Onshore"],
                "generation_mw": [500.0],
            }
        )
        rows = db.load_generation_fact(df)
        assert rows == 1

    def test_is_renewable_stored_as_boolean(self, db, sample_fact_df):
        db.load_generation_fact(sample_fact_df)
        with db.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT is_renewable FROM generation_fact")
            rows = cur.fetchall()
        for (val,) in rows:
            assert isinstance(val, bool)


class TestLoadGenerationSummary:
    def test_loads_correct_row_count(self, db, sample_summary_df):
        rows = db.load_generation_summary(sample_summary_df)
        assert rows == 2

    def test_upsert_deduplicates(self, db, sample_summary_df):
        db.load_generation_summary(sample_summary_df)
        db.load_generation_summary(sample_summary_df)
        with db.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM generation_summary")
            count = cur.fetchone()[0]
        assert count == 2

    def test_missing_required_columns_raises(self, db):
        bad_df = pd.DataFrame({"timestamp": ["2024-01-01"]})
        with pytest.raises(ValueError, match="Missing columns"):
            db.load_generation_summary(bad_df)

    def test_partial_columns_accepted(self, db):
        df = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(["2024-01-01"]),
                "country_code": ["IE"],
                "total_generation_mw": [1300.0],
            }
        )
        rows = db.load_generation_summary(df)
        assert rows == 1


class TestLogPipelineRun:
    def test_creates_run_record(self, db):
        db.log_pipeline_run("entsoe", 100, "success")
        with db.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT source, rows_loaded, status FROM pipeline_runs")
            row = cur.fetchone()
        assert row == ("entsoe", 100, "success")

    def test_failure_run_recorded(self, db):
        db.log_pipeline_run("carbon_intensity", 0, "failed", message="API timeout")
        with db.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT status, message FROM pipeline_runs")
            row = cur.fetchone()
        assert row == ("failed", "API timeout")

    def test_multiple_runs_stored(self, db):
        db.log_pipeline_run("entsoe", 10, "success")
        db.log_pipeline_run("entsoe", 20, "success")
        with db.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM pipeline_runs")
            count = cur.fetchone()[0]
        assert count == 2


class TestQueryGenerationSummary:
    def test_returns_dataframe(self, db, sample_summary_df):
        db.load_generation_summary(sample_summary_df)
        result = db.query_generation_summary("IE")
        assert isinstance(result, pd.DataFrame)

    def test_correct_row_count(self, db, sample_summary_df):
        db.load_generation_summary(sample_summary_df)
        result = db.query_generation_summary("IE")
        assert len(result) == 2

    def test_limit_respected(self, db, sample_summary_df):
        db.load_generation_summary(sample_summary_df)
        result = db.query_generation_summary("IE", limit=1)
        assert len(result) == 1

    def test_empty_for_unknown_country(self, db, sample_summary_df):
        db.load_generation_summary(sample_summary_df)
        result = db.query_generation_summary("DE")
        assert result.empty


class TestQueryGenerationFact:
    def test_returns_dataframe(self, db, sample_fact_df):
        db.load_generation_fact(sample_fact_df)
        result = db.query_generation_fact("IE")
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 3


class TestSaveRaw:
    def test_saves_dataframe(self, db):
        df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        raw_id = db.save_raw("test_source", df)
        assert isinstance(raw_id, str)
        assert raw_id.isdigit()

    def test_saves_dict(self, db):
        raw_id = db.save_raw("test_source", {"foo": "bar"})
        assert isinstance(raw_id, str)

    def test_document_has_expected_fields(self, db):
        df = pd.DataFrame({"a": [1, 2]})
        db.save_raw("test_source", df)
        doc = db.get_recent_raw("test_source", limit=1)[0]
        assert doc["source"] == "test_source"
        assert "ingested_at" in doc
        assert doc["payload"] == [{"index": 0, "a": 1}, {"index": 1, "a": 2}]

    def test_dataframe_columns_become_payload_fields(self, db):
        df = pd.DataFrame({"temperature_2m": [5.1], "location": ["Dublin"]})
        db.save_raw("weather", df)
        doc = db.get_recent_raw("weather", limit=1)[0]
        assert doc["payload"][0]["temperature_2m"] == 5.1
        assert doc["payload"][0]["location"] == "Dublin"


class TestGetRecentRaw:
    def test_returns_matching_source_only(self, db):
        db.save_raw("entsoe", {"a": 1})
        db.save_raw("weather", {"b": 2})
        results = db.get_recent_raw("weather")
        assert len(results) == 1
        assert results[0]["source"] == "weather"

    def test_orders_most_recent_first(self, db):
        db.save_raw("weather", {"seq": 1})
        db.save_raw("weather", {"seq": 2})
        results = db.get_recent_raw("weather")
        assert results[0]["payload"]["seq"] == 2
        assert results[1]["payload"]["seq"] == 1

    def test_limit_respected(self, db):
        for i in range(5):
            db.save_raw("weather", {"seq": i})
        results = db.get_recent_raw("weather", limit=2)
        assert len(results) == 2

    def test_empty_for_unknown_source(self, db):
        results = db.get_recent_raw("nonexistent_source")
        assert results == []
