import os
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd
from entsoe.entsoe import EntsoePandasClient
from dotenv import load_dotenv

from config import (
    RAW_DATA_DIR,
    LOG_FORMAT,
    LOG_DATE_FORMAT,
    LOG_LEVEL,
)

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
        df["country_code"] = country_code
        logger.info(f"Fetched {len(df)} rows")
        return df
    except Exception as e:
        logger.error(f"Failed to fetch generation: {e}")
        raise EntsoeIngestionError(str(e)) from e


def save_generation_data(df: pd.DataFrame, format: str = "csv") -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"entsoe_generation_{timestamp}.{format}"
    filepath = RAW_DATA_DIR / filename
    
    try:
        if format == "csv":
            df.to_csv(filepath)
        elif format == "json":
            df.to_json(filepath, orient="records", date_format="iso")
        else:
            raise EntsoeIngestionError(f"Unsupported format: {format}")
        
        logger.info(f"Saved to {filepath}")
        return filepath
    except Exception as e:
        logger.error(f"Save failed: {e}")
        raise EntsoeIngestionError("Failed to save data") from e


def ingest_generation_data(
    hours_back: int = 24,
    country_code: str = "IE",
    save_format: str = "csv"
) -> Path:
    end = pd.Timestamp.now(tz="Europe/Dublin")
    start = end - pd.Timedelta(hours=hours_back)
    
    try:
        df = fetch_generation(start, end, country_code)
        filepath = save_generation_data(df, save_format)
        return filepath
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
        filepath = save_generation_data(df, "csv")
        print(f"Saved to: {filepath}")
    else:
        try:
            filepath = ingest_generation_data(hours_back=24, save_format="csv")
            print(f"Saved to: {filepath}")
        except EntsoeIngestionError as e:
            print(f"Failed: {e}")
            print("Tip: Set ENTSOE_API_KEY environment variable or use --mock flag")
            print("Get API key from: https://transparency.entsoe.eu")