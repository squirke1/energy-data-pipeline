import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from raw_store import get_collection, get_recent_raw, save_raw


@pytest.fixture(autouse=True)
def clean_collection():
    """Runs against the real local MongoDB (docker-compose) - same
    reasoning as test_load.py's clean_db: real integration confidence
    over mocking pymongo internals, isolated by clearing before each test.
    """
    get_collection().delete_many({})


class TestSaveRaw:
    def test_saves_dataframe(self):
        df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        raw_id = save_raw("test_source", df)
        assert isinstance(raw_id, str)
        assert len(raw_id) == 24  # Mongo ObjectId hex length

    def test_saves_dict(self):
        raw_id = save_raw("test_source", {"foo": "bar"})
        assert isinstance(raw_id, str)

    def test_document_has_expected_fields(self):
        df = pd.DataFrame({"a": [1, 2]})
        save_raw("test_source", df)
        doc = get_collection().find_one({"source": "test_source"})
        assert doc["source"] == "test_source"
        assert "ingested_at" in doc
        assert doc["payload"] == [{"index": 0, "a": 1}, {"index": 1, "a": 2}]

    def test_dataframe_columns_become_payload_fields(self):
        df = pd.DataFrame({"temperature_2m": [5.1], "location": ["Dublin"]})
        save_raw("weather", df)
        doc = get_collection().find_one({"source": "weather"})
        assert doc["payload"][0]["temperature_2m"] == 5.1
        assert doc["payload"][0]["location"] == "Dublin"


class TestGetRecentRaw:
    def test_returns_matching_source_only(self):
        save_raw("entsoe", {"a": 1})
        save_raw("weather", {"b": 2})
        results = get_recent_raw("weather")
        assert len(results) == 1
        assert results[0]["source"] == "weather"

    def test_orders_most_recent_first(self):
        save_raw("weather", {"seq": 1})
        save_raw("weather", {"seq": 2})
        results = get_recent_raw("weather")
        assert results[0]["payload"]["seq"] == 2
        assert results[1]["payload"]["seq"] == 1

    def test_limit_respected(self):
        for i in range(5):
            save_raw("weather", {"seq": i})
        results = get_recent_raw("weather", limit=2)
        assert len(results) == 2

    def test_empty_for_unknown_source(self):
        results = get_recent_raw("nonexistent_source")
        assert results == []
