import logging
from abc import ABC, abstractmethod

import pandas as pd

try:
    from src.raw_store import RawStore, RawStoreError
except ImportError:
    from raw_store import RawStore, RawStoreError

logger = logging.getLogger(__name__)


class IngestionError(Exception):
    """Raised by any DataSource for fetch, save, or ingest failures.

    One shared type (instead of one per source) lets Orchestrator catch
    failures polymorphically without knowing which concrete source it's
    running.
    """


class BaseSource(ABC):
    source_name: str

    def __init__(self, raw_store: RawStore | None = None):
        self.raw_store = raw_store or RawStore()

    @abstractmethod
    def fetch(self, hours_back: int = 24) -> pd.DataFrame:
        """Fetch live data from the external API."""

    @abstractmethod
    def generate_mock_data(self, hours: int = 24) -> pd.DataFrame:
        """Produce synthetic data with the same shape as fetch()."""

    def save(self, df: pd.DataFrame) -> str:
        try:
            raw_id = self.raw_store.save_raw(self.source_name, df)
            logger.info(f"Saved to raw store: {raw_id}")
            return raw_id
        except RawStoreError as e:
            logger.error(f"Save failed: {e}")
            raise IngestionError("Failed to save data") from e

    def ingest(self, hours_back: int = 24) -> str:
        try:
            df = self.fetch(hours_back)
            return self.save(df)
        except IngestionError:
            logger.error("Ingestion failed")
            raise
