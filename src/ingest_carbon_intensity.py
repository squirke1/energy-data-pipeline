import logging
from datetime import datetime, timedelta, timezone
from typing import ClassVar

import pandas as pd
import requests

try:
    from src.base_source import BaseSource, IngestionError
    from src.config import (
        CARBON_INTENSITY_BASE_URL,
        CARBON_INTENSITY_COUNTRY_CODE,
        LOG_DATE_FORMAT,
        LOG_FORMAT,
        LOG_LEVEL,
        MAX_RETRIES,
        REQUEST_TIMEOUT,
        RETRY_DELAY,
    )
    from src.retry import is_retryable_request_error, retry_with_backoff
except ImportError:
    from base_source import BaseSource, IngestionError
    from config import (
        CARBON_INTENSITY_BASE_URL,
        CARBON_INTENSITY_COUNTRY_CODE,
        LOG_DATE_FORMAT,
        LOG_FORMAT,
        LOG_LEVEL,
        MAX_RETRIES,
        REQUEST_TIMEOUT,
        RETRY_DELAY,
    )
    from retry import is_retryable_request_error, retry_with_backoff

logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
logger = logging.getLogger(__name__)


class CarbonIntensitySource(BaseSource):
    source_name = "carbon_intensity"
    FUEL_TYPES: ClassVar[list[str]] = [
        "gas", "coal", "biomass", "nuclear", "hydro", "imports", "other", "wind", "solar",
    ]
    ISO_FORMAT = "%Y-%m-%dT%H:%MZ"

    @retry_with_backoff(MAX_RETRIES, RETRY_DELAY, is_retryable_request_error)
    def _fetch_raw(self, url: str) -> dict:
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json()

    def fetch(self, hours_back: int = 24) -> pd.DataFrame:
        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=hours_back)
        url = f"{CARBON_INTENSITY_BASE_URL}/generation/{start.strftime(self.ISO_FORMAT)}/{end.strftime(self.ISO_FORMAT)}"
        logger.info(f"Fetching {CARBON_INTENSITY_COUNTRY_CODE} generation mix from {start} to {end}")

        try:
            payload = self._fetch_raw(url)
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch generation mix: {e}")
            raise IngestionError(str(e)) from e

        periods = payload.get("data")
        if not periods:
            raise IngestionError("Unexpected response shape: missing 'data'")

        records = []
        for period in periods:
            row = {"timestamp": period["from"]}
            for entry in period["generationmix"]:
                row[entry["fuel"]] = entry["perc"]
            records.append(row)

        df = pd.DataFrame(records)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.set_index("timestamp")
        df["country_code"] = CARBON_INTENSITY_COUNTRY_CODE

        logger.info(f"Fetched {len(df)} rows")
        return df

    def generate_mock_data(self, hours: int = 24) -> pd.DataFrame:
        end = pd.Timestamp.now(tz="UTC")
        start = end - pd.Timedelta(hours=hours)
        date_range = pd.date_range(start=start, end=end, freq="30min")

        # Roughly realistic GB mix (sums to 100), with wind share oscillating
        # over the window and gas absorbing the difference.
        base_mix = {"gas": 15, "coal": 0, "biomass": 5, "nuclear": 15, "hydro": 3,
                    "imports": 12, "other": 5, "wind": 35, "solar": 10}

        rows = []
        for i in range(len(date_range)):
            wind_shift = (i % 20) - 10
            row = dict(base_mix)
            row["wind"] = max(0, row["wind"] + wind_shift)
            row["gas"] = max(0, row["gas"] - wind_shift)
            rows.append(row)

        df = pd.DataFrame(rows, columns=self.FUEL_TYPES, index=date_range)
        df["country_code"] = CARBON_INTENSITY_COUNTRY_CODE
        return df


if __name__ == "__main__":
    import sys

    source = CarbonIntensitySource()

    if "--mock" in sys.argv:
        logger.info("Using mock data")
        mock_df = source.generate_mock_data(hours=24)
        mock_raw_id = source.save(mock_df)
        print(f"Saved to raw store: {mock_raw_id}")
    else:
        try:
            live_raw_id = source.ingest(hours_back=24)
            print(f"Saved to raw store: {live_raw_id}")
        except IngestionError as e:
            print(f"Failed: {e}")
