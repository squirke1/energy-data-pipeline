import pytest
from pathlib import Path
from unittest.mock import Mock, patch
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ingest_entsoe import (
    get_entsoe_client,
    fetch_generation,
    save_generation_data,
    ingest_generation_data,
    generate_mock_data,
    EntsoeIngestionError,
)


@pytest.fixture
def sample_df():
    index = pd.date_range("2026-01-01", periods=4, freq="15min", tz="UTC")
    return pd.DataFrame(
        {"Fossil Gas": [100, 110, 120, 130], "Wind Onshore": [200, 210, 220, 230]},
        index=index,
    )


class TestGetEntsoeClient:
    def test_missing_api_key(self, monkeypatch):
        monkeypatch.delenv("ENTSOE_API_KEY", raising=False)
        with pytest.raises(EntsoeIngestionError, match="ENTSOE_API_KEY not set"):
            get_entsoe_client()

    @patch("ingest_entsoe.EntsoePandasClient")
    def test_success(self, mock_client_cls, monkeypatch):
        monkeypatch.setenv("ENTSOE_API_KEY", "fake_key")
        mock_instance = Mock()
        mock_client_cls.return_value = mock_instance
        client = get_entsoe_client()
        mock_client_cls.assert_called_once_with(api_key="fake_key")
        assert client is mock_instance


class TestFetchGeneration:
    @patch("ingest_entsoe.get_entsoe_client")
    def test_successful_fetch(self, mock_get_client, sample_df):
        mock_client = Mock()
        mock_client.query_generation.return_value = sample_df
        mock_get_client.return_value = mock_client

        start = pd.Timestamp("2026-01-01", tz="UTC")
        end = pd.Timestamp("2026-01-02", tz="UTC")
        result = fetch_generation(start, end, country_code="IE")

        mock_client.query_generation.assert_called_once_with(
            country_code="IE", start=start, end=end
        )
        assert "country_code" in result.columns
        assert (result["country_code"] == "IE").all()
        assert str(result.index.tz) == "Europe/Dublin"

    @patch("ingest_entsoe.get_entsoe_client")
    def test_fetch_failure_wrapped(self, mock_get_client):
        mock_get_client.side_effect = EntsoeIngestionError("no key")
        with pytest.raises(EntsoeIngestionError):
            fetch_generation(pd.Timestamp.now(tz="UTC"), pd.Timestamp.now(tz="UTC"))


class TestSaveGenerationData:
    def test_save_csv(self, tmp_path, sample_df, monkeypatch):
        monkeypatch.setattr("ingest_entsoe.RAW_DATA_DIR", tmp_path)
        filepath = save_generation_data(sample_df, format="csv")
        assert filepath.exists()
        assert filepath.name.startswith("entsoe_generation_")
        assert filepath.suffix == ".csv"

    def test_save_json(self, tmp_path, sample_df, monkeypatch):
        monkeypatch.setattr("ingest_entsoe.RAW_DATA_DIR", tmp_path)
        filepath = save_generation_data(sample_df, format="json")
        assert filepath.exists()
        assert filepath.suffix == ".json"

    def test_invalid_format(self, tmp_path, sample_df, monkeypatch):
        monkeypatch.setattr("ingest_entsoe.RAW_DATA_DIR", tmp_path)
        with pytest.raises(EntsoeIngestionError, match="Failed to save data"):
            save_generation_data(sample_df, format="xml")


class TestIngestGenerationData:
    @patch("ingest_entsoe.save_generation_data")
    @patch("ingest_entsoe.fetch_generation")
    def test_successful_ingestion(self, mock_fetch, mock_save, sample_df):
        mock_fetch.return_value = sample_df
        mock_save.return_value = Path("/data/raw/entsoe_generation_test.csv")
        result = ingest_generation_data(hours_back=24, country_code="IE")
        mock_fetch.assert_called_once()
        mock_save.assert_called_once_with(sample_df, "csv")
        assert isinstance(result, Path)

    @patch("ingest_entsoe.fetch_generation")
    def test_ingestion_failure_propagates(self, mock_fetch):
        mock_fetch.side_effect = EntsoeIngestionError("API down")
        with pytest.raises(EntsoeIngestionError):
            ingest_generation_data()


class TestGenerateMockData:
    def test_shape_and_columns(self):
        df = generate_mock_data(hours=24)
        assert "country_code" in df.columns
        assert (df["country_code"] == "IE").all()
        for col in ["Fossil Gas", "Wind Onshore", "Hydro Run-of-river", "Other"]:
            assert col in df.columns

    def test_15_minute_frequency(self):
        df = generate_mock_data(hours=1)
        assert len(df) == 5
        deltas = df.index.to_series().diff().dropna().unique()
        assert len(deltas) == 1
        assert deltas[0] == pd.Timedelta(minutes=15)
