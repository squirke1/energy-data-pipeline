import logging
import os

import pandas as pd
from dotenv import load_dotenv
from entsoe.entsoe import EntsoePandasClient

try:
    from src.config import LOG_DATE_FORMAT, LOG_FORMAT, LOG_LEVEL
    from src.raw_store import RawStoreError, save_raw
except ImportError:
    from config import LOG_DATE_FORMAT, LOG_FORMAT, LOG_LEVEL
    from raw_store import RawStoreError, save_raw

load_dotenv()

logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
logger = logging.getLogger(__name__)


class EntsoeIngestionError(Exception):
    pass


def get_entsoe_client() -> EntsoePandasClient:
    api_key = os.getenv("ENTSOE_API_KEY")
    if not api_key:
        raise EntsoeIngestionError(
            "ENTSOE_API_KEY not set. Get your key from https://transparency.entsoe.eu"
        )
    return EntsoePandasClient(api_key=api_key)


def fetch_generation(
    start: pd.Timestamp,
    end: pd.Timestamp,
    country_code: str = "IE"
) -> pd.DataFrame:
    logger.info(f"Fetching generation data for {country_code} from {start} to {end}")
    
    try:
        client = get_entsoe_client()
        df = client.query_generation(country_code=country_code, start=start, end=end)
        df.index = df.index.tz_convert("Europe/Dublin")  # type: ignore[attr-defined]

        if isinstance(df.columns, pd.MultiIndex):
            # Some fuel types (e.g. pumped storage) report both "Actual
            # Aggregated" (generation) and "Actual Consumption" columns.
            # Only generation output belongs in this pipeline's fuel_type
            # rows, so keep the aggregated level and flatten it away.
            df = df.xs("Actual Aggregated", axis=1, level=1)

        df["country_code"] = country_code
        logger.info(f"Fetched {len(df)} rows")
        return df
    except Exception as e:
        logger.error(f"Failed to fetch generation: {e}")
        raise EntsoeIngestionError(str(e)) from e


def save_generation_data(df: pd.DataFrame) -> str:
    try:
        raw_id = save_raw("entsoe", df)
        logger.info(f"Saved to raw store: {raw_id}")
        return raw_id
    except RawStoreError as e:
        logger.error(f"Save failed: {e}")
        raise EntsoeIngestionError("Failed to save data") from e


def ingest_generation_data(hours_back: int = 24, country_code: str = "IE") -> str:
    end = pd.Timestamp.now(tz="Europe/Dublin")
    start = end - pd.Timedelta(hours=hours_back)

    try:
        df = fetch_generation(start, end, country_code)
        raw_id = save_generation_data(df)
        return raw_id
    except EntsoeIngestionError:
        logger.error("Ingestion failed")
        raise


def generate_mock_data(hours: int = 24) -> pd.DataFrame:
    end = pd.Timestamp.now(tz="Europe/Dublin")
    start = end - pd.Timedelta(hours=hours)
    
    date_range = pd.date_range(start=start, end=end, freq="15min")
    
    data = {
        "Fossil Gas": [800 + i * 10 % 200 for i in range(len(date_range))],
        "Wind Onshore": [500 + i * 15 % 600 for i in range(len(date_range))],
        "Hydro Run-of-river": [50 + i * 2 % 30 for i in range(len(date_range))],
        "Other": [100 + i * 5 % 50 for i in range(len(date_range))],
    }
    
    df = pd.DataFrame(data, index=date_range)
    df["country_code"] = "IE"
    return df


if __name__ == "__main__":
    import sys
    
    if "--mock" in sys.argv:
        logger.info("Using mock data")
        df = generate_mock_data(hours=24)
        raw_id = save_generation_data(df)
        print(f"Saved to raw store: {raw_id}")
    else:
        try:
            raw_id = ingest_generation_data(hours_back=24)
            print(f"Saved to raw store: {raw_id}")
        except EntsoeIngestionError as e:
            print(f"Failed: {e}")
            print("Tip: Set ENTSOE_API_KEY environment variable or use --mock flag")
            print("Get API key from: https://transparency.entsoe.eu")