import logging
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

try:
    from src.config import (
        LOG_DATE_FORMAT,
        LOG_FORMAT,
        LOG_LEVEL,
        OPEN_METEO_BASE_URL,
        RAW_DATA_DIR,
        REQUEST_TIMEOUT,
        WEATHER_LATITUDE,
        WEATHER_LOCATION_NAME,
        WEATHER_LONGITUDE,
    )
except ImportError:
    from config import (
        LOG_DATE_FORMAT,
        LOG_FORMAT,
        LOG_LEVEL,
        OPEN_METEO_BASE_URL,
        RAW_DATA_DIR,
        REQUEST_TIMEOUT,
        WEATHER_LATITUDE,
        WEATHER_LOCATION_NAME,
        WEATHER_LONGITUDE,
    )

logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
logger = logging.getLogger(__name__)

HOURLY_VARIABLES = ["temperature_2m", "wind_speed_10m", "shortwave_radiation"]


class WeatherIngestionError(Exception):
    pass


def fetch_weather(hours_back: int = 24) -> pd.DataFrame:
    past_days = max(1, -(-hours_back // 24))  # ceil division, Open-Meteo min is 1
    params = {
        "latitude": WEATHER_LATITUDE,
        "longitude": WEATHER_LONGITUDE,
        "hourly": ",".join(HOURLY_VARIABLES),
        "timezone": "Europe/Dublin",
        "past_days": past_days,
        "forecast_days": 1,
    }
    logger.info(f"Fetching weather for {WEATHER_LOCATION_NAME} (past_days={past_days})")

    try:
        response = requests.get(OPEN_METEO_BASE_URL, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch weather: {e}")
        raise WeatherIngestionError(str(e)) from e

    hourly = payload.get("hourly")
    if not hourly or "time" not in hourly:
        raise WeatherIngestionError("Unexpected response shape: missing 'hourly' data")

    df = pd.DataFrame(hourly)
    df["time"] = pd.to_datetime(df["time"]).dt.tz_localize("Europe/Dublin")
    df = df.set_index("time")
    df["location"] = WEATHER_LOCATION_NAME

    logger.info(f"Fetched {len(df)} rows")
    return df


def save_weather_data(df: pd.DataFrame, format: str = "csv") -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")  # noqa: DTZ005 - local time is fine for a filename
    filename = f"weather_{timestamp}.{format}"
    filepath = RAW_DATA_DIR / filename

    try:
        if format == "csv":
            df.to_csv(filepath)
        elif format == "json":
            df.to_json(filepath, orient="records", date_format="iso")
        else:
            raise WeatherIngestionError(f"Unsupported format: {format}")

        logger.info(f"Saved to {filepath}")
        return filepath
    except Exception as e:
        logger.error(f"Save failed: {e}")
        raise WeatherIngestionError("Failed to save data") from e


def ingest_weather_data(hours_back: int = 24, save_format: str = "csv") -> Path:
    try:
        df = fetch_weather(hours_back)
        filepath = save_weather_data(df, save_format)
        return filepath
    except WeatherIngestionError:
        logger.error("Ingestion failed")
        raise


def generate_mock_data(hours: int = 24) -> pd.DataFrame:
    end = pd.Timestamp.now(tz="Europe/Dublin")
    start = end - pd.Timedelta(hours=hours)
    date_range = pd.date_range(start=start, end=end, freq="1h")

    data = {
        "temperature_2m": [8 + (i % 6) * 0.5 for i in range(len(date_range))],
        "wind_speed_10m": [15 + (i * 3 % 25) for i in range(len(date_range))],
        "shortwave_radiation": [
            max(0, 400 - abs(12 - i % 24) * 40) for i in range(len(date_range))
        ],
    }

    df = pd.DataFrame(data, index=date_range)
    df["location"] = WEATHER_LOCATION_NAME
    return df


if __name__ == "__main__":
    import sys

    if "--mock" in sys.argv:
        logger.info("Using mock data")
        df = generate_mock_data(hours=24)
        filepath = save_weather_data(df, "csv")
        print(f"Saved to: {filepath}")
    else:
        try:
            filepath = ingest_weather_data(hours_back=24, save_format="csv")
            print(f"Saved to: {filepath}")
        except WeatherIngestionError as e:
            print(f"Failed: {e}")
            print("Tip: Open-Meteo needs no API key - if this failed, check network access")
