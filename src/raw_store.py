import atexit
import logging
from datetime import datetime, timezone
from typing import Any

import pandas as pd
from pymongo import MongoClient
from pymongo.collection import Collection

try:
    from src.config import (
        LOG_DATE_FORMAT,
        LOG_FORMAT,
        LOG_LEVEL,
        MONGO_DB,
        MONGO_HOST,
        MONGO_PASSWORD,
        MONGO_PORT,
        MONGO_RAW_COLLECTION,
        MONGO_USER,
    )
except ImportError:
    from config import (
        LOG_DATE_FORMAT,
        LOG_FORMAT,
        LOG_LEVEL,
        MONGO_DB,
        MONGO_HOST,
        MONGO_PASSWORD,
        MONGO_PORT,
        MONGO_RAW_COLLECTION,
        MONGO_USER,
    )

logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
logger = logging.getLogger(__name__)


class RawStoreError(Exception):
    pass


class RawStore:
    """MongoDB-backed store for raw ingested payloads, one collection
    shared by every source. The underlying MongoClient is pooled at the
    class level - Mongo connections are meant to be long-lived and reused,
    not recreated per RawStore instance.
    """

    _client: MongoClient | None = None

    def _get_client(self) -> MongoClient:
        cls = type(self)
        if cls._client is None:
            uri = f"mongodb://{MONGO_USER}:{MONGO_PASSWORD}@{MONGO_HOST}:{MONGO_PORT}/"
            cls._client = MongoClient(uri, serverSelectionTimeoutMS=5000)
            atexit.register(cls._client.close)
        return cls._client

    def _get_collection(self) -> Collection:
        return self._get_client()[MONGO_DB][MONGO_RAW_COLLECTION]

    def save_raw(
        self, source: str, data: pd.DataFrame | dict | list, format_hint: str = "records"
    ) -> str:
        """Store a raw ingested payload as-is. Returns the Mongo document id as a string.

        DataFrames are stored via to_dict("records") - one document field per
        column, matching how each source's JSON naturally varies rather than
        forcing a fixed schema across sources.
        """
        if isinstance(data, pd.DataFrame):
            payload = data.reset_index().to_dict(orient="records")
        else:
            payload = data

        document = {
            "source": source,
            "ingested_at": datetime.now(timezone.utc),
            "format": format_hint,
            "payload": payload,
        }

        try:
            insert_result = self._get_collection().insert_one(document)
            logger.info(f"Saved raw {source} document {insert_result.inserted_id}")
            return str(insert_result.inserted_id)
        except Exception as e:
            logger.error(f"Failed to save raw {source} document: {e}")
            raise RawStoreError(str(e)) from e

    def get_recent_raw(self, source: str, limit: int = 10) -> list[dict[str, Any]]:
        # Sort by _id, not ingested_at: BSON dates are millisecond-precision,
        # so rapid successive inserts can tie on ingested_at. ObjectIds are
        # monotonically increasing and unique, so they sort reliably.
        cursor = self._get_collection().find({"source": source}).sort("_id", -1).limit(limit)
        return list(cursor)
