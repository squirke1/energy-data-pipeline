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

_client: MongoClient | None = None


class RawStoreError(Exception):
    pass


def get_client() -> MongoClient:
    global _client
    if _client is None:
        uri = f"mongodb://{MONGO_USER}:{MONGO_PASSWORD}@{MONGO_HOST}:{MONGO_PORT}/"
        _client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        atexit.register(_client.close)
    return _client


def get_collection() -> Collection:
    return get_client()[MONGO_DB][MONGO_RAW_COLLECTION]


def save_raw(source: str, data: pd.DataFrame | dict | list, format_hint: str = "records") -> str:
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
        result = get_collection().insert_one(document)
        logger.info(f"Saved raw {source} document {result.inserted_id}")
        return str(result.inserted_id)
    except Exception as e:
        logger.error(f"Failed to save raw {source} document: {e}")
        raise RawStoreError(str(e)) from e


def get_recent_raw(source: str, limit: int = 10) -> list[dict[str, Any]]:
    # Sort by _id, not ingested_at: BSON dates are millisecond-precision,
    # so rapid successive inserts can tie on ingested_at. ObjectIds are
    # monotonically increasing and unique, so they sort reliably.
    cursor = get_collection().find({"source": source}).sort("_id", -1).limit(limit)
    return list(cursor)
