import sys
import threading
import time
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from raw_store import RawStore


@pytest.fixture
def store():
    return RawStore()


@pytest.fixture(autouse=True)
def clean_collection(store):
    """Runs against the real local MongoDB (docker-compose) - same
    reasoning as test_load.py's clean_db: real integration confidence
    over mocking pymongo internals, isolated by clearing before each test.
    """
    store._get_collection().delete_many({})


class TestSaveRaw:
    def test_saves_dataframe(self, store):
        df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        raw_id = store.save_raw("test_source", df)
        assert isinstance(raw_id, str)
        assert len(raw_id) == 24  # Mongo ObjectId hex length

    def test_saves_dict(self, store):
        raw_id = store.save_raw("test_source", {"foo": "bar"})
        assert isinstance(raw_id, str)

    def test_document_has_expected_fields(self, store):
        df = pd.DataFrame({"a": [1, 2]})
        store.save_raw("test_source", df)
        doc = store._get_collection().find_one({"source": "test_source"})
        assert doc["source"] == "test_source"
        assert "ingested_at" in doc
        assert doc["payload"] == [{"index": 0, "a": 1}, {"index": 1, "a": 2}]

    def test_dataframe_columns_become_payload_fields(self, store):
        df = pd.DataFrame({"temperature_2m": [5.1], "location": ["Dublin"]})
        store.save_raw("weather", df)
        doc = store._get_collection().find_one({"source": "weather"})
        assert doc["payload"][0]["temperature_2m"] == 5.1
        assert doc["payload"][0]["location"] == "Dublin"


class TestClientThreadSafety:
    def test_concurrent_first_access_creates_only_one_client(self):
        """Orchestrator.run_all() constructs sources (each with their own
        RawStore()) concurrently across threads. All of them read/write the
        shared RawStore._client class attribute, so first-time creation
        needs to be race-safe - without the lock in _get_client(), threads
        can all see _client as None and each construct a MongoClient,
        leaking every one after the first.
        """
        original_client = RawStore._client
        RawStore._client = None
        try:
            with patch("raw_store.MongoClient") as mock_mongo_client_cls:
                # A fast in-process mock call might not force a thread
                # switch between the None-check and the assignment even
                # without the lock, making the race unreliable to observe.
                # A small sleep widens that window so this test is a
                # trustworthy regression guard, not a GIL-timing gamble.
                def slow_construct(*args, **kwargs):
                    time.sleep(0.01)
                    return Mock()

                mock_mongo_client_cls.side_effect = slow_construct

                # Line every thread up to hit the None-check at the same
                # instant, maximising the race window the lock has to close.
                thread_count = 10
                barrier = threading.Barrier(thread_count)

                def get_client():
                    barrier.wait()
                    RawStore()._get_client()

                threads = [threading.Thread(target=get_client) for _ in range(thread_count)]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()

                assert mock_mongo_client_cls.call_count == 1
        finally:
            RawStore._client = original_client


class TestGetRecentRaw:
    def test_returns_matching_source_only(self, store):
        store.save_raw("entsoe", {"a": 1})
        store.save_raw("weather", {"b": 2})
        results = store.get_recent_raw("weather")
        assert len(results) == 1
        assert results[0]["source"] == "weather"

    def test_orders_most_recent_first(self, store):
        store.save_raw("weather", {"seq": 1})
        store.save_raw("weather", {"seq": 2})
        results = store.get_recent_raw("weather")
        assert results[0]["payload"]["seq"] == 2
        assert results[1]["payload"]["seq"] == 1

    def test_limit_respected(self, store):
        for i in range(5):
            store.save_raw("weather", {"seq": i})
        results = store.get_recent_raw("weather", limit=2)
        assert len(results) == 2

    def test_empty_for_unknown_source(self, store):
        results = store.get_recent_raw("nonexistent_source")
        assert results == []
