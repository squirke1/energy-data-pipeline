import logging
import sys

import pandas as pd

from config import LOG_DATE_FORMAT, LOG_FORMAT, LOG_LEVEL
from ingest_eirgrid import (
    EirGridIngestionError,
    fetch_eirgrid_data,
)
from ingest_eirgrid import (
    generate_mock_data as eirgrid_mock,
)
from ingest_entsoe import (
    EntsoeIngestionError,
    fetch_generation,
)
from ingest_entsoe import (
    generate_mock_data as entsoe_mock,
)
from load_db import (
    init_db,
    load_generation_fact,
    load_generation_summary,
    log_pipeline_run,
)
from transform_energy import transform_eirgrid_generation, transform_entsoe_generation
from validate import validate_eirgrid_response, validate_generation_df

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


def run_eirgrid_pipeline(mock: bool = False) -> dict:
    logger.info(f"Starting EirGrid pipeline (mock={mock})")
    init_db()

    try:
        raw_data = eirgrid_mock() if mock else fetch_eirgrid_data("generation")

        validation = validate_eirgrid_response(raw_data)
        if not validation.passed:
            raise ValueError(f"Validation failed: {validation.errors}")

        long_df, summary_df = transform_eirgrid_generation(raw_data)

        fact_rows = load_generation_fact(long_df)
        summary_rows = load_generation_summary(summary_df)

        log_pipeline_run("eirgrid", fact_rows, "success")
        result = {
            "status": "success",
            "source": "eirgrid",
            "fact_rows": fact_rows,
            "summary_rows": summary_rows,
            "validation": validation.summary(),
        }
        logger.info(f"EirGrid pipeline complete: {result}")
        return result

    except (EirGridIngestionError, ValueError) as e:
        log_pipeline_run("eirgrid", 0, "failed", str(e))
        logger.error(f"EirGrid pipeline failed: {e}")
        raise


if __name__ == "__main__":
    use_mock = "--mock" in sys.argv
    source = "both"
    for arg in sys.argv[1:]:
        if arg in ("entsoe", "eirgrid", "both"):
            source = arg

    if source in ("entsoe", "both"):
        try:
            result = run_entsoe_pipeline(mock=use_mock)
            print(f"ENTSOE: {result}")
        except Exception as e:  # noqa: BLE001 - top-level CLI catch-all so eirgrid can still run
            print(f"ENTSOE failed: {e}")

    if source in ("eirgrid", "both"):
        try:
            result = run_eirgrid_pipeline(mock=use_mock)
            print(f"EirGrid: {result}")
        except Exception as e:  # noqa: BLE001 - top-level CLI catch-all
            print(f"EirGrid failed: {e}")
