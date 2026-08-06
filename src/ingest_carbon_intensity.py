import logging
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

try:
    from src.config import (
        CARBON_INTENSITY_BASE_URL,
        CARBON_INTENSITY_COUNTRY_CODE,
        LOG_DATE_FORMAT,
        LOG_FORMAT,
        LOG_LEVEL,
        REQUEST_TIMEOUT,
    )
    from src.raw_store import RawStoreError, save_raw
except ImportError:
    from config import (
        CARBON_INTENSITY_BASE_URL,
        CARBON_INTENSITY_COUNTRY_CODE,
        LOG_DATE_FORMAT,
        LOG_FORMAT,
        LOG_LEVEL,
        REQUEST_TIMEOUT,
    )
    from raw_store import RawStoreError, save_raw

logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
logger = logging.getLogger(__name__)

FUEL_TYPES = ["gas", "coal", "biomass", "nuclear", "hydro", "imports", "other", "wind", "solar"]
ISO_FORMAT = "%Y-%m-%dT%H:%MZ"


class CarbonIntensityIngestionError(Exception):
    pass


def fetch_generation_mix(hours_back: int = 24) -> pd.DataFrame:
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=hours_back)
    url = f"{CARBON_INTENSITY_BASE_URL}/generation/{start.strftime(ISO_FORMAT)}/{end.strftime(ISO_FORMAT)}"
    logger.info(f"Fetching {CARBON_INTENSITY_COUNTRY_CODE} generation mix from {start} to {end}")

    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch generation mix: {e}")
        raise CarbonIntensityIngestionError(str(e)) from e

    periods = payload.get("data")
    if not periods:
        raise CarbonIntensityIngestionError("Unexpected response shape: missing 'data'")

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


def save_generation_mix_data(df: pd.DataFrame) -> str:
    try:
        raw_id = save_raw("carbon_intensity", df)
        logger.info(f"Saved to raw store: {raw_id}")
        return raw_id
    except RawStoreError as e:
        logger.error(f"Save failed: {e}")
        raise CarbonIntensityIngestionError("Failed to save data") from e


def ingest_generation_mix_data(hours_back: int = 24) -> str:
    try:
        df = fetch_generation_mix(hours_back)
        raw_id = save_generation_mix_data(df)
        return raw_id
    except CarbonIntensityIngestionError:
        logger.error("Ingestion failed")
        raise


def generate_mock_data(hours: int = 24) -> pd.DataFrame:
    end = pd.Timestamp.now(tz="UTC")
    start = end - pd.Timedelta(hours=hours)
    date_range = pd.date_range(start=start, end=end, freq="30min")

    # Roughly realistic GB mix (sums to 100), with wind share oscillating
    # over the window and gas absorbing the difference.
    base = {"gas": 15, "coal": 0, "biomass": 5, "nuclear": 15, "hydro": 3,
            "imports": 12, "other": 5, "wind": 35, "solar": 10}

    rows = []
    for i in range(len(date_range)):
        wind_shift = (i % 20) - 10
        row = dict(base)
        row["wind"] = max(0, row["wind"] + wind_shift)
        row["gas"] = max(0, row["gas"] - wind_shift)
        rows.append(row)

    df = pd.DataFrame(rows, columns=FUEL_TYPES, index=date_range)
    df["country_code"] = CARBON_INTENSITY_COUNTRY_CODE
    return df


if __name__ == "__main__":
    import sys

    if "--mock" in sys.argv:
        logger.info("Using mock data")
        df = generate_mock_data(hours=24)
        raw_id = save_generation_mix_data(df)
        print(f"Saved to raw store: {raw_id}")
    else:
        try:
            raw_id = ingest_generation_mix_data(hours_back=24)
            print(f"Saved to raw store: {raw_id}")
        except CarbonIntensityIngestionError as e:
            print(f"Failed: {e}")
