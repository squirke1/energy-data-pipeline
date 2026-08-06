import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ingest_carbon_intensity import CarbonIntensitySource
from src.base_source import IngestionError
from src.raw_store import RawStoreError


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


class TestFetch:
    @patch("ingest_carbon_intensity.requests.get")
    def test_successful_fetch(self, mock_get, mock_response):
        mock_get.return_value = mock_response
        result = CarbonIntensitySource().fetch(hours_back=24)
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
        with pytest.raises(IngestionError):
            CarbonIntensitySource().fetch()

    @patch("ingest_carbon_intensity.requests.get")
    def test_missing_data_key_raises(self, mock_get):
        mock_resp = Mock()
        mock_resp.json.return_value = {}
        mock_get.return_value = mock_resp
        with pytest.raises(IngestionError, match="Unexpected response shape"):
            CarbonIntensitySource().fetch()


class TestSave:
    def test_saves_to_raw_store(self):
        mock_raw_store = Mock()
        mock_raw_store.save_raw.return_value = "abc123"
        source = CarbonIntensitySource(raw_store=mock_raw_store)
        df = source.generate_mock_data(hours=4)

        raw_id = source.save(df)

        mock_raw_store.save_raw.assert_called_once_with("carbon_intensity", df)
        assert raw_id == "abc123"

    def test_raw_store_error_wrapped(self):
        mock_raw_store = Mock()
        mock_raw_store.save_raw.side_effect = RawStoreError("connection refused")
        source = CarbonIntensitySource(raw_store=mock_raw_store)
        df = source.generate_mock_data(hours=4)

        with pytest.raises(IngestionError, match="Failed to save data"):
            source.save(df)


class TestIngest:
    def test_successful_ingestion(self):
        source = CarbonIntensitySource()
        mock_df = source.generate_mock_data(hours=4)
        source.fetch = Mock(return_value=mock_df)
        source.save = Mock(return_value="abc123")

        result = source.ingest(hours_back=24)

        source.fetch.assert_called_once_with(24)
        source.save.assert_called_once()
        assert result == "abc123"

    def test_ingestion_failure_propagates(self):
        source = CarbonIntensitySource()
        source.fetch = Mock(side_effect=IngestionError("API down"))
        with pytest.raises(IngestionError):
            source.ingest()


class TestGenerateMockData:
    def test_shape_and_columns(self):
        df = CarbonIntensitySource().generate_mock_data(hours=24)
        assert "country_code" in df.columns
        assert (df["country_code"] == "GB").all()
        for col in ["gas", "wind", "nuclear", "solar", "coal", "biomass", "hydro", "imports", "other"]:
            assert col in df.columns

    def test_half_hourly_frequency(self):
        df = CarbonIntensitySource().generate_mock_data(hours=5)
        assert len(df) == 11
