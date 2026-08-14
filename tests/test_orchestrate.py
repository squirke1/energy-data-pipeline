import sys
import time
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from orchestrate import Orchestrator, main


@pytest.fixture
def orchestrator():
    return Orchestrator(db=Mock(), validator=Mock(), transformer=Mock())


class TestRunAll:
    def test_calls_all_three_sources(self, orchestrator):
        orchestrator.run_entsoe = Mock(return_value={"status": "success", "source": "entsoe"})
        orchestrator.run_carbon_intensity = Mock(
            return_value={"status": "success", "source": "carbon_intensity"}
        )
        orchestrator.run_weather = Mock(return_value={"status": "success", "source": "weather"})

        results = orchestrator.run_all(hours_back=24, mock=True)

        orchestrator.run_entsoe.assert_called_once_with(hours_back=24, mock=True)
        orchestrator.run_carbon_intensity.assert_called_once_with(hours_back=24, mock=True)
        orchestrator.run_weather.assert_called_once_with(hours_back=24, mock=True)
        assert set(results.keys()) == {"entsoe", "carbon_intensity", "weather"}

    def test_result_order_is_deterministic(self, orchestrator):
        orchestrator.run_entsoe = Mock(return_value={"status": "success"})
        orchestrator.run_carbon_intensity = Mock(return_value={"status": "success"})
        orchestrator.run_weather = Mock(return_value={"status": "success"})

        results = orchestrator.run_all(mock=True)

        # Fixed output order regardless of which source actually finishes
        # first - see run_all()'s docstring for why.
        assert list(results.keys()) == ["entsoe", "carbon_intensity", "weather"]

    def test_one_source_failure_does_not_block_others(self, orchestrator):
        orchestrator.run_entsoe = Mock(side_effect=ValueError("validation failed"))
        orchestrator.run_carbon_intensity = Mock(
            return_value={"status": "success", "source": "carbon_intensity"}
        )
        orchestrator.run_weather = Mock(return_value={"status": "success", "source": "weather"})

        results = orchestrator.run_all(mock=True)

        assert results["entsoe"]["status"] == "failed"
        assert "validation failed" in results["entsoe"]["error"]
        assert results["carbon_intensity"]["status"] == "success"
        assert results["weather"]["status"] == "success"

    def test_init_db_called_once_not_per_source(self, orchestrator):
        orchestrator.run_entsoe = Mock(return_value={"status": "success"})
        orchestrator.run_carbon_intensity = Mock(return_value={"status": "success"})
        orchestrator.run_weather = Mock(return_value={"status": "success"})

        orchestrator.run_all(mock=True)

        # init_db() runs once up front, not once per thread - see
        # run_all()'s docstring for the concurrent-CREATE-TABLE race this
        # avoids.
        orchestrator.db.init_db.assert_called_once()

    def test_sources_run_concurrently_not_sequentially(self, orchestrator):
        sleep_seconds = 0.2

        def slow_run(*args, **kwargs):
            time.sleep(sleep_seconds)
            return {"status": "success"}

        orchestrator.run_entsoe = Mock(side_effect=slow_run)
        orchestrator.run_carbon_intensity = Mock(side_effect=slow_run)
        orchestrator.run_weather = Mock(side_effect=slow_run)

        start = time.monotonic()
        orchestrator.run_all(mock=True)
        elapsed = time.monotonic() - start

        # Sequential would take ~3x sleep_seconds; concurrent should take
        # close to 1x. A 2x threshold clearly distinguishes the two without
        # being flaky on a loaded CI runner.
        assert elapsed < sleep_seconds * 2


class TestMain:
    @patch("orchestrate.Orchestrator")
    def test_all_sources_succeed_returns_zero(self, mock_orchestrator_cls):
        mock_orchestrator_cls.return_value.run_all.return_value = {
            "entsoe": {"status": "success"},
            "carbon_intensity": {"status": "success"},
            "weather": {"status": "success"},
        }

        exit_code = main(["--mock"])

        assert exit_code == 0

    @patch("orchestrate.Orchestrator")
    def test_one_source_failing_returns_nonzero(self, mock_orchestrator_cls):
        # This is the exact gap that would make failure-based alerting on
        # the scheduled workflow silently never fire: run_all() catches
        # each source's exceptions and reports "failed" in its dict instead
        # of raising, so main() has to check that dict itself.
        mock_orchestrator_cls.return_value.run_all.return_value = {
            "entsoe": {"status": "failed", "error": "API down"},
            "carbon_intensity": {"status": "success"},
            "weather": {"status": "success"},
        }

        exit_code = main(["--mock"])

        assert exit_code == 1

    @patch("orchestrate.Orchestrator")
    def test_single_source_success_returns_zero(self, mock_orchestrator_cls):
        mock_orchestrator_cls.return_value.run_entsoe.return_value = {"status": "success"}

        exit_code = main(["--mock", "entsoe"])

        assert exit_code == 0

    @patch("orchestrate.Orchestrator")
    def test_single_source_failure_returns_nonzero(self, mock_orchestrator_cls):
        mock_orchestrator_cls.return_value.run_entsoe.side_effect = ValueError("validation failed")

        exit_code = main(["--mock", "entsoe"])

        assert exit_code == 1
