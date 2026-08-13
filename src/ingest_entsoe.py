import logging
import os
from urllib.parse import urlsplit

import pandas as pd
from dotenv import load_dotenv
from entsoe.entsoe import EntsoePandasClient

try:
    from src.base_source import BaseSource, IngestionError
    from src.config import LOG_DATE_FORMAT, LOG_FORMAT, LOG_LEVEL
except ImportError:
    from base_source import BaseSource, IngestionError
    from config import LOG_DATE_FORMAT, LOG_FORMAT, LOG_LEVEL

load_dotenv()

logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
logger = logging.getLogger(__name__)


def _sanitize_fetch_error(e: Exception) -> str:
    """ENTSO-E sends the API key as a `securityToken` query param on every
    request, and entsoe-py lets requests.HTTPError's default message through
    unchanged on unrecognised error responses - that message embeds the full
    request URL, key included. Strip the query string so the key can't end
    up in logs, stdout, or the pipeline_runs table.
    """
    response = getattr(e, "response", None)
    url = getattr(response, "url", None)
    if response is not None and url:
        clean_url = urlsplit(url)._replace(query="").geturl()
        return f"{response.status_code} error for url: {clean_url}"
    return str(e)


class EntsoeSource(BaseSource):
    source_name = "entsoe"

    def __init__(self, country_code: str = "IE", db=None):
        super().__init__(db)
        self.country_code = country_code

    def get_client(self) -> EntsoePandasClient:
        api_key = os.getenv("ENTSOE_API_KEY")
        if not api_key:
            raise IngestionError(
                "ENTSOE_API_KEY not set. Get your key from https://transparency.entsoe.eu"
            )
        return EntsoePandasClient(api_key=api_key)

    def fetch(self, hours_back: int = 24) -> pd.DataFrame:
        end = pd.Timestamp.now(tz="Europe/Dublin")
        start = end - pd.Timedelta(hours=hours_back)
        logger.info(f"Fetching generation data for {self.country_code} from {start} to {end}")

        try:
            client = self.get_client()
            df = client.query_generation(country_code=self.country_code, start=start, end=end)
            df.index = df.index.tz_convert("Europe/Dublin")  # type: ignore[attr-defined]

            if isinstance(df.columns, pd.MultiIndex):
                # Some fuel types (e.g. pumped storage) report both "Actual
                # Aggregated" (generation) and "Actual Consumption" columns.
                # Only generation output belongs in this pipeline's fuel_type
                # rows, so keep the aggregated level and flatten it away.
                selected = df.xs("Actual Aggregated", axis=1, level=1)
                # .xs() can collapse to a Series if only one column remains -
                # assert rather than trust the type hint, since this exact
                # method already exists because ENTSO-E's real response
                # shape once surprised this pipeline.
                assert isinstance(selected, pd.DataFrame), (
                    f"Expected DataFrame after .xs(), got {type(selected).__name__}"
                )
                df = selected

            df["country_code"] = self.country_code
            logger.info(f"Fetched {len(df)} rows")
            return df
        except Exception as e:
            message = _sanitize_fetch_error(e)
            logger.error(f"Failed to fetch generation: {message}")
            raise IngestionError(message) from e

    def generate_mock_data(self, hours: int = 24) -> pd.DataFrame:
        end = pd.Timestamp.now(tz="Europe/Dublin")
        start = end - pd.Timedelta(hours=hours)

        date_range = pd.date_range(start=start, end=end, freq="15min")

        generation_by_fuel = {
            "Fossil Gas": [800 + i * 10 % 200 for i in range(len(date_range))],
            "Wind Onshore": [500 + i * 15 % 600 for i in range(len(date_range))],
            "Hydro Run-of-river": [50 + i * 2 % 30 for i in range(len(date_range))],
            "Other": [100 + i * 5 % 50 for i in range(len(date_range))],
        }

        df = pd.DataFrame(generation_by_fuel, index=date_range)
        df["country_code"] = self.country_code
        return df


if __name__ == "__main__":
    import sys

    source = EntsoeSource()

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
            print("Tip: Set ENTSOE_API_KEY environment variable or use --mock flag")
            print("Get API key from: https://transparency.entsoe.eu")
