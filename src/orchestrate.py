import logging
import sys
from concurrent.futures import ThreadPoolExecutor

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

    def run_all(self, hours_back: int = 24, mock: bool = False) -> dict[str, dict]:
        """Run all three sources concurrently instead of one after another.

        They're independent I/O-bound calls (HTTP fetch + DB write) with no
        shared state between them, so threads - not processes - are the
        right tool: requests/psycopg2 both release the GIL during I/O
        waits, so three threads genuinely overlap their waiting time
        instead of contending for a CPU nothing here is bottlenecked on.
        Wall-clock time drops to roughly the slowest source instead of the
        sum of all three.

        init_db() runs once here, up front, rather than once per thread
        inside each run_*() call: concurrent first-time "CREATE TABLE IF
        NOT EXISTS" calls from separate Postgres connections can race and
        raise a duplicate-key error, since the existence check and the
        creation aren't atomic across sessions.
        """
        self.db.init_db()

        jobs = {
            "entsoe": lambda: self.run_entsoe(hours_back=hours_back, mock=mock),
            "carbon_intensity": lambda: self.run_carbon_intensity(hours_back=hours_back, mock=mock),
            "weather": lambda: self.run_weather(hours_back=hours_back, mock=mock),
        }

        with ThreadPoolExecutor(max_workers=len(jobs)) as executor:
            # Submitting all three up front starts them concurrently; the
            # dict below is iterated in a fixed order purely so results
            # come back in a predictable order, regardless of which source
            # actually finishes first.
            futures = {source_name: executor.submit(job) for source_name, job in jobs.items()}

            run_summaries: dict[str, dict] = {}
            for source_name, future in futures.items():
                try:
                    run_summaries[source_name] = future.result()
                except Exception as e:  # noqa: BLE001 - isolate one source's failure from the others
                    logger.error(f"{source_name} pipeline failed: {e}")
                    run_summaries[source_name] = {
                        "status": "failed",
                        "source": source_name,
                        "error": str(e),
                    }

        return run_summaries


DISPLAY_LABELS = {"entsoe": "ENTSOE", "carbon_intensity": "Carbon intensity", "weather": "Weather"}


def main(argv: list[str]) -> int:
    """Returns a process exit code rather than calling sys.exit() directly,
    so this is callable/testable without subprocess. run_all() catches each
    source's exceptions internally and reports them in its returned dict
    instead of raising - without checking that dict here, a routine source
    failure (an API outage, a validation error) would print "failed" but
    still exit 0, which would make the scheduled workflow's failure-based
    alerting silently never fire for anything but a total crash.
    """
    use_mock = "--mock" in argv
    selected_source = "all"
    for arg in argv:
        if arg in ("entsoe", "carbon_intensity", "weather", "all"):
            selected_source = arg

    orchestrator = Orchestrator()

    if selected_source == "all":
        # run_all() runs all three sources concurrently (see its docstring)
        run_summaries = orchestrator.run_all(mock=use_mock)
        for source_name, run_summary in run_summaries.items():
            print(f"{DISPLAY_LABELS[source_name]}: {run_summary}")
        any_failed = any(summary["status"] == "failed" for summary in run_summaries.values())
        return 1 if any_failed else 0

    run_method = getattr(orchestrator, f"run_{selected_source}")
    try:
        print(f"{DISPLAY_LABELS[selected_source]}: {run_method(mock=use_mock)}")
        return 0
    except Exception as e:  # noqa: BLE001 - top-level CLI catch-all
        print(f"{DISPLAY_LABELS[selected_source]} failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
