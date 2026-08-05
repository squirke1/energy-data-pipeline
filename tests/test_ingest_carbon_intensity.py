import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ingest_carbon_intensity import (
    CarbonIntensityIngestionError,
    fetch_generation_mix,
    generate_mock_data,
    ingest_generation_mix_data,
    save_generation_mix_data,
)


@pytest.fixture
def mock_response():
    mock_resp = Mock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": [
            {
                "from": "2026-08-05T16:00Z",
                "to": "2026-08-05T16:30Z",
                "generationmix": [
                    {"fuel": "gas", "perc": 20.0},
                    {"fuel": "wind", "perc": 45.0},
                    {"fuel": "nuclear", "perc": 15.0},
                    {"fuel": "solar", "perc": 10.0},
                    {"fuel": "coal", "perc": 0.0},
                ],
            },
            {
                "from": "2026-08-05T16:30Z",
                "to": "2026-08-05T17:00Z",
                "generationmix": [
                    {"fuel": "gas", "perc": 22.0},
                    {"fuel": "wind", "perc": 40.0},
                    {"fuel": "nuclear", "perc": 15.0},
                    {"fuel": "solar", "perc": 12.0},
                    {"fuel": "coal", "perc": 0.0},
                ],
            },
        ]
    }
    return mock_resp


class TestFetchGenerationMix:
    @patch("ingest_carbon_intensity.requests.get")
    def test_successful_fetch(self, mock_get, mock_response):
        mock_get.return_value = mock_response
        result = fetch_generation_mix(hours_back=24)
        assert len(result) == 2
        assert "country_code" in result.columns
        assert (result["country_code"] == "GB").all()
        for col in ["gas", "wind", "nuclear", "solar", "coal"]:
            assert col in result.columns
        mock_get.assert_called_once()

    @patch("ingest_carbon_intensity.requests.get")
    def test_http_error_wrapped(self, mock_get):
        import requests

        mock_get.side_effect = requests.exceptions.HTTPError("HTTP 500")
        with pytest.raises(CarbonIntensityIngestionError):
            fetch_generation_mix()

    @patch("ingest_carbon_intensity.requests.get")
    def test_missing_data_key_raises(self, mock_get):
        mock_resp = Mock()
        mock_resp.json.return_value = {}
        mock_get.return_value = mock_resp
        with pytest.raises(CarbonIntensityIngestionError, match="Unexpected response shape"):
            fetch_generation_mix()


class TestSaveGenerationMixData:
    def test_save_csv(self, tmp_path, monkeypatch):
        monkeypatch.setattr("ingest_carbon_intensity.RAW_DATA_DIR", tmp_path)
        df = generate_mock_data(hours=4)
        filepath = save_generation_mix_data(df, format="csv")
        assert filepath.exists()
        assert filepath.name.startswith("carbon_intensity_")
        assert filepath.suffix == ".csv"

    def test_save_json(self, tmp_path, monkeypatch):
        monkeypatch.setattr("ingest_carbon_intensity.RAW_DATA_DIR", tmp_path)
        df = generate_mock_data(hours=4)
        filepath = save_generation_mix_data(df, format="json")
        assert filepath.exists()
        assert filepath.suffix == ".json"

    def test_invalid_format(self, tmp_path, monkeypatch):
        monkeypatch.setattr("ingest_carbon_intensity.RAW_DATA_DIR", tmp_path)
        df = generate_mock_data(hours=4)
        with pytest.raises(CarbonIntensityIngestionError, match="Failed to save data"):
            save_generation_mix_data(df, format="xml")


class TestIngestGenerationMixData:
    @patch("ingest_carbon_intensity.save_generation_mix_data")
    @patch("ingest_carbon_intensity.fetch_generation_mix")
    def test_successful_ingestion(self, mock_fetch, mock_save):
        mock_fetch.return_value = generate_mock_data(hours=4)
        mock_save.return_value = Path("/data/raw/carbon_intensity_test.csv")
        result = ingest_generation_mix_data(hours_back=24)
        mock_fetch.assert_called_once_with(24)
        mock_save.assert_called_once()
        assert isinstance(result, Path)

    @patch("ingest_carbon_intensity.fetch_generation_mix")
    def test_ingestion_failure_propagates(self, mock_fetch):
        mock_fetch.side_effect = CarbonIntensityIngestionError("API down")
        with pytest.raises(CarbonIntensityIngestionError):
            ingest_generation_mix_data()


class TestGenerateMockData:
    def test_shape_and_columns(self):
        df = generate_mock_data(hours=24)
        assert "country_code" in df.columns
        assert (df["country_code"] == "GB").all()
        for col in ["gas", "wind", "nuclear", "solar", "coal", "biomass", "hydro", "imports", "other"]:
            assert col in df.columns

    def test_half_hourly_frequency(self):
        df = generate_mock_data(hours=5)
        assert len(df) == 11
