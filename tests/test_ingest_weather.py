import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ingest_weather import (
    WeatherIngestionError,
    fetch_weather,
    generate_mock_data,
    ingest_weather_data,
    save_weather_data,
)


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


class TestFetchWeather:
    @patch("ingest_weather.requests.get")
    def test_successful_fetch(self, mock_get, mock_response):
        mock_get.return_value = mock_response
        result = fetch_weather(hours_back=24)
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
        with pytest.raises(WeatherIngestionError):
            fetch_weather()

    @patch("ingest_weather.requests.get")
    def test_missing_hourly_key_raises(self, mock_get):
        mock_resp = Mock()
        mock_resp.json.return_value = {"latitude": 53.35, "longitude": -6.26}
        mock_get.return_value = mock_resp
        with pytest.raises(WeatherIngestionError, match="Unexpected response shape"):
            fetch_weather()

    @patch("ingest_weather.requests.get")
    def test_past_days_scales_with_hours_back(self, mock_get, mock_response):
        mock_get.return_value = mock_response
        fetch_weather(hours_back=50)
        _, kwargs = mock_get.call_args
        assert kwargs["params"]["past_days"] == 3


class TestSaveWeatherData:
    def test_save_csv(self, tmp_path, mock_response, monkeypatch):
        monkeypatch.setattr("ingest_weather.RAW_DATA_DIR", tmp_path)
        df = generate_mock_data(hours=4)
        filepath = save_weather_data(df, format="csv")
        assert filepath.exists()
        assert filepath.name.startswith("weather_")
        assert filepath.suffix == ".csv"

    def test_save_json(self, tmp_path, monkeypatch):
        monkeypatch.setattr("ingest_weather.RAW_DATA_DIR", tmp_path)
        df = generate_mock_data(hours=4)
        filepath = save_weather_data(df, format="json")
        assert filepath.exists()
        assert filepath.suffix == ".json"

    def test_invalid_format(self, tmp_path, monkeypatch):
        monkeypatch.setattr("ingest_weather.RAW_DATA_DIR", tmp_path)
        df = generate_mock_data(hours=4)
        with pytest.raises(WeatherIngestionError, match="Failed to save data"):
            save_weather_data(df, format="xml")


class TestIngestWeatherData:
    @patch("ingest_weather.save_weather_data")
    @patch("ingest_weather.fetch_weather")
    def test_successful_ingestion(self, mock_fetch, mock_save):
        mock_fetch.return_value = generate_mock_data(hours=4)
        mock_save.return_value = Path("/data/raw/weather_test.csv")
        result = ingest_weather_data(hours_back=24)
        mock_fetch.assert_called_once_with(24)
        mock_save.assert_called_once()
        assert isinstance(result, Path)

    @patch("ingest_weather.fetch_weather")
    def test_ingestion_failure_propagates(self, mock_fetch):
        mock_fetch.side_effect = WeatherIngestionError("API down")
        with pytest.raises(WeatherIngestionError):
            ingest_weather_data()


class TestGenerateMockData:
    def test_shape_and_columns(self):
        df = generate_mock_data(hours=24)
        assert "location" in df.columns
        assert (df["location"] == "Dublin").all()
        for col in ["temperature_2m", "wind_speed_10m", "shortwave_radiation"]:
            assert col in df.columns

    def test_hourly_frequency(self):
        df = generate_mock_data(hours=5)
        assert len(df) == 6
