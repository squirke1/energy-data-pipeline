import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd
import pytest
import requests

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ingest_entsoe import EntsoeSource
from src.base_source import IngestionError
from src.load_db import RawStoreError


@pytest.fixture
def sample_df():
    index = pd.date_range("2026-01-01", periods=4, freq="15min", tz="UTC")
    return pd.DataFrame(
        {"Fossil Gas": [100, 110, 120, 130], "Wind Onshore": [200, 210, 220, 230]},
        index=index,
    )


class TestGetClient:
    def test_missing_api_key(self, monkeypatch):
        monkeypatch.delenv("ENTSOE_API_KEY", raising=False)
        with pytest.raises(IngestionError, match="ENTSOE_API_KEY not set"):
            EntsoeSource().get_client()

    @patch("ingest_entsoe.EntsoePandasClient")
    def test_success(self, mock_client_cls, monkeypatch):
        monkeypatch.setenv("ENTSOE_API_KEY", "fake_key")
        mock_instance = Mock()
        mock_client_cls.return_value = mock_instance
        client = EntsoeSource().get_client()
        mock_client_cls.assert_called_once_with(api_key="fake_key")
        assert client is mock_instance


class TestFetch:
    @patch("ingest_entsoe.EntsoeSource.get_client")
    def test_successful_fetch(self, mock_get_client, sample_df):
        mock_client = Mock()
        mock_client.query_generation.return_value = sample_df
        mock_get_client.return_value = mock_client

        result = EntsoeSource(country_code="IE").fetch(hours_back=24)

        _, kwargs = mock_client.query_generation.call_args
        assert kwargs["country_code"] == "IE"
        assert "country_code" in result.columns
        assert (result["country_code"] == "IE").all()
        assert str(result.index.tz) == "Europe/Dublin"

    @patch("ingest_entsoe.EntsoeSource.get_client")
    def test_fetch_failure_wrapped(self, mock_get_client):
        mock_get_client.side_effect = IngestionError("no key")
        with pytest.raises(IngestionError):
            EntsoeSource().fetch()

    @patch("ingest_entsoe.EntsoeSource.get_client")
    def test_fetch_failure_strips_api_key_from_url(self, mock_get_client):
        # entsoe-py sends the API key as a `securityToken` query param on
        # every request, and re-raises requests.HTTPError unchanged for
        # unrecognised error responses. Build a *real* Response and call its
        # actual raise_for_status() - a hand-rolled HTTPError message would
        # sidestep the exact bug this test guards against, since requests
        # itself is what embeds the full URL (key included) into the
        # exception's default string form.
        response = requests.Response()
        response.status_code = 400
        response.reason = "Bad Request"
        response.url = (
            "https://web-api.tp.entsoe.eu/api?securityToken=super-secret-key&documentType=A75"
        )

        mock_client = Mock()

        def raise_http_error(*args, **kwargs):
            response.raise_for_status()

        mock_client.query_generation.side_effect = raise_http_error
        mock_get_client.return_value = mock_client

        with pytest.raises(IngestionError) as exc_info:
            EntsoeSource().fetch()

        assert "super-secret-key" not in str(exc_info.value)
        assert "securityToken" not in str(exc_info.value)

    @patch("ingest_entsoe.EntsoeSource.get_client")
    def test_multiindex_columns_flattened(self, mock_get_client):
        # Real ENTSO-E responses use MultiIndex columns when a fuel type
        # reports both generation and consumption (e.g. pumped storage) -
        # mock data never exercised this shape, which let a live-only bug
        # through validate.py's plain-string "country_code" check.
        index = pd.date_range("2026-01-01", periods=2, freq="15min", tz="UTC")
        columns = pd.MultiIndex.from_tuples(
            [
                ("Fossil Gas", "Actual Aggregated"),
                ("Hydro Pumped Storage", "Actual Aggregated"),
                ("Hydro Pumped Storage", "Actual Consumption"),
            ]
        )
        multiindex_df = pd.DataFrame([[100, 50, 10], [110, 55, 12]], index=index, columns=columns)

        mock_client = Mock()
        mock_client.query_generation.return_value = multiindex_df
        mock_get_client.return_value = mock_client

        result = EntsoeSource().fetch()

        assert not isinstance(result.columns, pd.MultiIndex)
        assert list(result.columns) == ["Fossil Gas", "Hydro Pumped Storage", "country_code"]


class TestSave:
    def test_saves_to_raw_store(self, sample_df):
        mock_db = Mock()
        mock_db.save_raw.return_value = "abc123"
        source = EntsoeSource(db=mock_db)

        raw_id = source.save(sample_df)

        mock_db.save_raw.assert_called_once_with("entsoe", sample_df)
        assert raw_id == "abc123"

    def test_raw_store_error_wrapped(self, sample_df):
        mock_db = Mock()
        mock_db.save_raw.side_effect = RawStoreError("connection refused")
        source = EntsoeSource(db=mock_db)

        with pytest.raises(IngestionError, match="Failed to save data"):
            source.save(sample_df)


class TestIngest:
    def test_successful_ingestion(self, sample_df):
        source = EntsoeSource()
        source.fetch = Mock(return_value=sample_df)
        source.save = Mock(return_value="abc123")

        result = source.ingest(hours_back=24)

        source.fetch.assert_called_once_with(24)
        source.save.assert_called_once_with(sample_df)
        assert result == "abc123"

    def test_ingestion_failure_propagates(self):
        source = EntsoeSource()
        source.fetch = Mock(side_effect=IngestionError("API down"))
        with pytest.raises(IngestionError):
            source.ingest()


class TestGenerateMockData:
    def test_shape_and_columns(self):
        df = EntsoeSource().generate_mock_data(hours=24)
        assert "country_code" in df.columns
        assert (df["country_code"] == "IE").all()
        for col in ["Fossil Gas", "Wind Onshore", "Hydro Run-of-river", "Other"]:
            assert col in df.columns

    def test_15_minute_frequency(self):
        df = EntsoeSource().generate_mock_data(hours=1)
        assert len(df) == 5
        deltas = df.index.to_series().diff().dropna().unique()
        assert len(deltas) == 1
        assert deltas[0] == pd.Timedelta(minutes=15)
