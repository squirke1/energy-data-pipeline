import logging
import sys

import pandas as pd

from config import LOG_DATE_FORMAT, LOG_FORMAT, LOG_LEVEL
from ingest_carbon_intensity import (
    CarbonIntensityIngestionError,
    fetch_generation_mix,
    save_generation_mix_data,
)
from ingest_carbon_intensity import (
    generate_mock_data as carbon_intensity_mock,
)
from ingest_entsoe import (
    EntsoeIngestionError,
    fetch_generation,
)
from ingest_entsoe import (
    generate_mock_data as entsoe_mock,
)
from ingest_weather import WeatherIngestionError, fetch_weather, save_weather_data
from ingest_weather import (
    generate_mock_data as weather_mock,
)
from load_db import (
    init_db,
    load_generation_fact,
    load_generation_summary,
    log_pipeline_run,
)
from transform_energy import transform_entsoe_generation
from validate import validate_generation_df

logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
logger = logging.getLogger(__name__)


def run_entsoe_pipeline(
    hours_back: int = 24,
    country_code: str = "IE",
    mock: bool = False,
) -> dict:
    logger.info(f"Starting ENTSOE pipeline (mock={mock}, hours_back={hours_back})")
    init_db()

    try:
        if mock:
            raw_df = entsoe_mock(hours=hours_back)
        else:
            end = pd.Timestamp.now(tz="Europe/Dublin")
            start = end - pd.Timedelta(hours=hours_back)
            raw_df = fetch_generation(start, end, country_code)

        validation = validate_generation_df(raw_df)
        if not validation.passed:
            raise ValueError(f"Validation failed: {validation.errors}")

        long_df, summary_df = transform_entsoe_generation(raw_df)

        fact_rows = load_generation_fact(long_df)
        summary_rows = load_generation_summary(summary_df)

        log_pipeline_run("entsoe", fact_rows, "success")
        result = {
            "status": "success",
            "source": "entsoe",
            "fact_rows": fact_rows,
            "summary_rows": summary_rows,
            "validation": validation.summary(),
        }
        logger.info(f"ENTSOE pipeline complete: {result}")
        return result

    except (EntsoeIngestionError, ValueError) as e:
        log_pipeline_run("entsoe", 0, "failed", str(e))
        logger.error(f"ENTSOE pipeline failed: {e}")
        raise


def run_weather_pipeline(hours_back: int = 24, mock: bool = False) -> dict:
    logger.info(f"Starting weather pipeline (mock={mock}, hours_back={hours_back})")
    init_db()

    try:
        df = weather_mock(hours=hours_back) if mock else fetch_weather(hours_back)
        raw_id = save_weather_data(df)

        log_pipeline_run("weather", len(df), "success")
        result = {
            "status": "success",
            "source": "weather",
            "rows": len(df),
            "raw_id": raw_id,
        }
        logger.info(f"Weather pipeline complete: {result}")
        return result

    except WeatherIngestionError as e:
        log_pipeline_run("weather", 0, "failed", str(e))
        logger.error(f"Weather pipeline failed: {e}")
        raise


def run_carbon_intensity_pipeline(hours_back: int = 24, mock: bool = False) -> dict:
    logger.info(f"Starting carbon intensity pipeline (mock={mock}, hours_back={hours_back})")
    init_db()

    try:
        df = (
            carbon_intensity_mock(hours=hours_back)
            if mock
            else fetch_generation_mix(hours_back)
        )
        raw_id = save_generation_mix_data(df)

        log_pipeline_run("carbon_intensity", len(df), "success")
        result = {
            "status": "success",
            "source": "carbon_intensity",
            "rows": len(df),
            "raw_id": raw_id,
        }
        logger.info(f"Carbon intensity pipeline complete: {result}")
        return result

    except CarbonIntensityIngestionError as e:
        log_pipeline_run("carbon_intensity", 0, "failed", str(e))
        logger.error(f"Carbon intensity pipeline failed: {e}")
        raise


if __name__ == "__main__":
    use_mock = "--mock" in sys.argv
    source = "all"
    for arg in sys.argv[1:]:
        if arg in ("entsoe", "carbon_intensity", "weather", "all"):
            source = arg

    if source in ("entsoe", "all"):
        try:
            result = run_entsoe_pipeline(mock=use_mock)
            print(f"ENTSOE: {result}")
        except Exception as e:  # noqa: BLE001 - top-level CLI catch-all so other sources can still run
            print(f"ENTSOE failed: {e}")

    if source in ("carbon_intensity", "all"):
        try:
            result = run_carbon_intensity_pipeline(mock=use_mock)
            print(f"Carbon intensity: {result}")
        except Exception as e:  # noqa: BLE001 - top-level CLI catch-all
            print(f"Carbon intensity failed: {e}")

    if source in ("weather", "all"):
        try:
            result = run_weather_pipeline(mock=use_mock)
            print(f"Weather: {result}")
        except Exception as e:  # noqa: BLE001 - top-level CLI catch-all
            print(f"Weather failed: {e}")
