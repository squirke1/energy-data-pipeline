import logging
import math
from typing import ClassVar

import pandas as pd
import requests

try:
    from src.base_source import BaseSource, IngestionError
    from src.config import (
        LOG_DATE_FORMAT,
        LOG_FORMAT,
        LOG_LEVEL,
        MAX_RETRIES,
        OPEN_METEO_BASE_URL,
        REQUEST_TIMEOUT,
        RETRY_DELAY,
        WEATHER_LATITUDE,
        WEATHER_LOCATION_NAME,
        WEATHER_LONGITUDE,
    )
    from src.retry import is_retryable_request_error, retry_with_backoff
except ImportError:
    from base_source import BaseSource, IngestionError
    from config import (
        LOG_DATE_FORMAT,
        LOG_FORMAT,
        LOG_LEVEL,
        MAX_RETRIES,
        OPEN_METEO_BASE_URL,
        REQUEST_TIMEOUT,
        RETRY_DELAY,
        WEATHER_LATITUDE,
        WEATHER_LOCATION_NAME,
        WEATHER_LONGITUDE,
    )
    from retry import is_retryable_request_error, retry_with_backoff

logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
logger = logging.getLogger(__name__)


class WeatherSource(BaseSource):
    source_name = "weather"
    HOURLY_VARIABLES: ClassVar[list[str]] = ["temperature_2m", "wind_speed_10m", "shortwave_radiation"]

    @retry_with_backoff(MAX_RETRIES, RETRY_DELAY, is_retryable_request_error)
    def _fetch_raw(self, params: dict) -> dict:
        response = requests.get(OPEN_METEO_BASE_URL, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json()

    def fetch(self, hours_back: int = 24) -> pd.DataFrame:
        past_days = max(1, math.ceil(hours_back / 24))  # Open-Meteo minimum is 1
        params = {
            "latitude": WEATHER_LATITUDE,
            "longitude": WEATHER_LONGITUDE,
            "hourly": ",".join(self.HOURLY_VARIABLES),
            "timezone": "Europe/Dublin",
            "past_days": past_days,
            "forecast_days": 1,
        }
        logger.info(f"Fetching weather for {WEATHER_LOCATION_NAME} (past_days={past_days})")

        try:
            payload = self._fetch_raw(params)
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch weather: {e}")
            raise IngestionError(str(e)) from e

        hourly = payload.get("hourly")
        if not hourly or "time" not in hourly:
            raise IngestionError("Unexpected response shape: missing 'hourly' data")

        df = pd.DataFrame(hourly)
        df["time"] = pd.to_datetime(df["time"]).dt.tz_localize("Europe/Dublin")
        df = df.set_index("time")
        df["location"] = WEATHER_LOCATION_NAME

        logger.info(f"Fetched {len(df)} rows")
        return df

    def generate_mock_data(self, hours: int = 24) -> pd.DataFrame:
        end = pd.Timestamp.now(tz="Europe/Dublin")
        start = end - pd.Timedelta(hours=hours)
        date_range = pd.date_range(start=start, end=end, freq="1h")

        readings = {
            "temperature_2m": [8 + (i % 6) * 0.5 for i in range(len(date_range))],
            "wind_speed_10m": [15 + (i * 3 % 25) for i in range(len(date_range))],
            "shortwave_radiation": [
                max(0, 400 - abs(12 - i % 24) * 40) for i in range(len(date_range))
            ],
        }

        df = pd.DataFrame(readings, index=date_range)
        df["location"] = WEATHER_LOCATION_NAME
        return df


if __name__ == "__main__":
    import sys

    source = WeatherSource()

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
            print("Tip: Open-Meteo needs no API key - if this failed, check network access")
