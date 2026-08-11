import logging
import sys

from base_source import BaseSource, IngestionError
from config import LOG_DATE_FORMAT, LOG_FORMAT, LOG_LEVEL
from ingest_carbon_intensity import CarbonIntensitySource
from ingest_entsoe import EntsoeSource
from ingest_weather import WeatherSource
from load_db import PostgresDatabase
from transform_energy import GenerationTransformer
from validate import GenerationValidator

logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(
        self,
        db: PostgresDatabase | None = None,
        validator: GenerationValidator | None = None,
        transformer: GenerationTransformer | None = None,
    ):
        self.db = db or PostgresDatabase()
        self.validator = validator or GenerationValidator()
        self.transformer = transformer or GenerationTransformer()

    def run_entsoe(
        self,
        hours_back: int = 24,
        country_code: str = "IE",
        mock: bool = False,
        source: EntsoeSource | None = None,
    ) -> dict:
        source = source or EntsoeSource(country_code=country_code)
        logger.info(f"Starting ENTSOE pipeline (mock={mock}, hours_back={hours_back})")
        self.db.init_db()

        try:
            raw_df = source.generate_mock_data(hours_back) if mock else source.fetch(hours_back)

            validation = self.validator.validate(raw_df)
            if not validation.passed:
                raise ValueError(f"Validation failed: {validation.errors}")

            long_df, summary_df = self.transformer.transform_entsoe_generation(raw_df)

            fact_rows = self.db.load_generation_fact(long_df)
            summary_rows = self.db.load_generation_summary(summary_df)

            self.db.log_pipeline_run("entsoe", fact_rows, "success")
            run_summary = {
                "status": "success",
                "source": "entsoe",
                "fact_rows": fact_rows,
                "summary_rows": summary_rows,
                "validation": validation.summary(),
            }
            logger.info(f"ENTSOE pipeline complete: {run_summary}")
            return run_summary

        except (IngestionError, ValueError) as e:
            self.db.log_pipeline_run("entsoe", 0, "failed", str(e))
            logger.error(f"ENTSOE pipeline failed: {e}")
            raise

    def _run_raw_only_pipeline(self, source: BaseSource, hours_back: int, mock: bool) -> dict:
        """Shared shape for sources with no fuel_type/MW data to validate or
        transform - fetch, save raw, log. Both current raw-only sources
        (weather, carbon intensity) are otherwise identical here.
        """
        logger.info(
            f"Starting {source.source_name} pipeline (mock={mock}, hours_back={hours_back})"
        )
        self.db.init_db()

        try:
            df = source.generate_mock_data(hours_back) if mock else source.fetch(hours_back)
            raw_id = source.save(df)

            self.db.log_pipeline_run(source.source_name, len(df), "success")
            run_summary = {
                "status": "success",
                "source": source.source_name,
                "rows": len(df),
                "raw_id": raw_id,
            }
            logger.info(f"{source.source_name} pipeline complete: {run_summary}")
            return run_summary

        except IngestionError as e:
            self.db.log_pipeline_run(source.source_name, 0, "failed", str(e))
            logger.error(f"{source.source_name} pipeline failed: {e}")
            raise

    def run_weather(
        self, hours_back: int = 24, mock: bool = False, source: WeatherSource | None = None
    ) -> dict:
        return self._run_raw_only_pipeline(source or WeatherSource(), hours_back, mock)

    def run_carbon_intensity(
        self, hours_back: int = 24, mock: bool = False, source: CarbonIntensitySource | None = None
    ) -> dict:
        return self._run_raw_only_pipeline(source or CarbonIntensitySource(), hours_back, mock)


if __name__ == "__main__":
    use_mock = "--mock" in sys.argv
    selected_source = "all"
    for arg in sys.argv[1:]:
        if arg in ("entsoe", "carbon_intensity", "weather", "all"):
            selected_source = arg

    orchestrator = Orchestrator()

    if selected_source in ("entsoe", "all"):
        try:
            print(f"ENTSOE: {orchestrator.run_entsoe(mock=use_mock)}")
        except Exception as e:  # noqa: BLE001 - top-level CLI catch-all so other sources can still run
            print(f"ENTSOE failed: {e}")

    if selected_source in ("carbon_intensity", "all"):
        try:
            print(f"Carbon intensity: {orchestrator.run_carbon_intensity(mock=use_mock)}")
        except Exception as e:  # noqa: BLE001 - top-level CLI catch-all
            print(f"Carbon intensity failed: {e}")

    if selected_source in ("weather", "all"):
        try:
            print(f"Weather: {orchestrator.run_weather(mock=use_mock)}")
        except Exception as e:  # noqa: BLE001 - top-level CLI catch-all
            print(f"Weather failed: {e}")
