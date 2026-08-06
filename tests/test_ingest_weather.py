import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ingest_weather import WeatherSource
from src.base_source import IngestionError
from src.raw_store import RawStoreError


@pytest.fixture
def mock_response():
    mock_resp = Mock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "latitude": 53.35,
        "longitude": -6.26,
        "hourly": {
            "time": [
                "2026-01-01T00:00",
                "2026-01-01T01:00",
                "2026-01-01T02:00",
                "2026-01-01T03:00",
            ],
            "temperature_2m": [5.1, 4.8, 4.6, 4.5],
            "wind_speed_10m": [18.2, 20.1, 22.5, 19.8],
            "shortwave_radiation": [0.0, 0.0, 0.0, 0.0],
        },
    }
    return mock_resp


class TestFetch:
    @patch("ingest_weather.requests.get")
    def test_successful_fetch(self, mock_get, mock_response):
        mock_get.return_value = mock_response
        result = WeatherSource().fetch(hours_back=24)
        assert len(result) == 4
        assert "location" in result.columns
        assert (result["location"] == "Dublin").all()
        for col in ["temperature_2m", "wind_speed_10m", "shortwave_radiation"]:
            assert col in result.columns
        mock_get.assert_called_once()

    @patch("ingest_weather.requests.get")
    def test_http_error_wrapped(self, mock_get):
        import requests

        mock_get.side_effect = requests.exceptions.HTTPError("HTTP 500")
        with pytest.raises(IngestionError):
            WeatherSource().fetch()

    @patch("ingest_weather.requests.get")
    def test_missing_hourly_key_raises(self, mock_get):
        mock_resp = Mock()
        mock_resp.json.return_value = {"latitude": 53.35, "longitude": -6.26}
        mock_get.return_value = mock_resp
        with pytest.raises(IngestionError, match="Unexpected response shape"):
            WeatherSource().fetch()

    @patch("ingest_weather.requests.get")
    def test_past_days_scales_with_hours_back(self, mock_get, mock_response):
        mock_get.return_value = mock_response
        WeatherSource().fetch(hours_back=50)
        _, kwargs = mock_get.call_args
        assert kwargs["params"]["past_days"] == 3


class TestSave:
    def test_saves_to_raw_store(self):
        mock_raw_store = Mock()
        mock_raw_store.save_raw.return_value = "abc123"
        source = WeatherSource(raw_store=mock_raw_store)
        df = source.generate_mock_data(hours=4)

        raw_id = source.save(df)

        mock_raw_store.save_raw.assert_called_once_with("weather", df)
        assert raw_id == "abc123"

    def test_raw_store_error_wrapped(self):
        mock_raw_store = Mock()
        mock_raw_store.save_raw.side_effect = RawStoreError("connection refused")
        source = WeatherSource(raw_store=mock_raw_store)
        df = source.generate_mock_data(hours=4)

        with pytest.raises(IngestionError, match="Failed to save data"):
            source.save(df)


class TestIngest:
    def test_successful_ingestion(self):
        source = WeatherSource()
        mock_df = source.generate_mock_data(hours=4)
        source.fetch = Mock(return_value=mock_df)
        source.save = Mock(return_value="abc123")

        result = source.ingest(hours_back=24)

        source.fetch.assert_called_once_with(24)
        source.save.assert_called_once()
        assert result == "abc123"

    def test_ingestion_failure_propagates(self):
        source = WeatherSource()
        source.fetch = Mock(side_effect=IngestionError("API down"))
        with pytest.raises(IngestionError):
            source.ingest()


class TestGenerateMockData:
    def test_shape_and_columns(self):
        df = WeatherSource().generate_mock_data(hours=24)
        assert "location" in df.columns
        assert (df["location"] == "Dublin").all()
        for col in ["temperature_2m", "wind_speed_10m", "shortwave_radiation"]:
            assert col in df.columns

    def test_hourly_frequency(self):
        df = WeatherSource().generate_mock_data(hours=5)
        assert len(df) == 6
