import json
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, mock_open
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ingest_eirgrid import (
    fetch_eirgrid_data,
    save_raw_data,
    ingest_generation_data,
    ingest_all_endpoints,
    EirGridIngestionError,
)


@pytest.fixture
def mock_response():
    mock_resp = Mock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "Rows": [
            {"FieldName": "Wind", "Value": "1234"},
            {"FieldName": "Gas", "Value": "5678"},
        ]
    }
    return mock_resp


@pytest.fixture
def sample_data():
    return {
        "Rows": [
            {"FieldName": "Wind", "Value": "1234"},
            {"FieldName": "Gas", "Value": "5678"},
        ]
    }


class TestFetchEirGridData:
    @patch("ingest_eirgrid.requests.get")
    def test_successful_fetch(self, mock_get, mock_response):
        mock_get.return_value = mock_response
        result = fetch_eirgrid_data("generation")
        assert result == mock_response.json.return_value
        mock_get.assert_called_once()
    
    def test_invalid_endpoint(self):
        with pytest.raises(EirGridIngestionError, match="Unknown endpoint"):
            fetch_eirgrid_data("invalid_endpoint")
    
    @patch("ingest_eirgrid.requests.get")
    def test_http_error(self, mock_get):
        import requests
        mock_get.side_effect = requests.exceptions.HTTPError("HTTP 404")
        with pytest.raises(EirGridIngestionError):
            fetch_eirgrid_data("generation")
    
    @patch("ingest_eirgrid.requests.get")
    @patch("ingest_eirgrid.time.sleep")
    def test_retry_on_timeout(self, mock_sleep, mock_get):
        import requests
        mock_get.side_effect = requests.exceptions.Timeout("Timeout")
        with pytest.raises(EirGridIngestionError, match="Timeout after"):
            fetch_eirgrid_data("generation")
        assert mock_get.call_count == 4


class TestSaveRawData:
    @patch("ingest_eirgrid.open", new_callable=mock_open)
    @patch("ingest_eirgrid.json.dump")
    def test_save_json(self, mock_dump, mock_file, sample_data):
        filepath = save_raw_data(sample_data, "generation", format="json")
        assert filepath.name.startswith("generation_")
        assert filepath.name.endswith(".json")
        mock_dump.assert_called_once()
    
    @patch("ingest_eirgrid.pd.json_normalize")
    def test_save_csv(self, mock_normalize, sample_data):
        mock_df = Mock()
        mock_normalize.return_value = mock_df
        filepath = save_raw_data(sample_data, "generation", format="csv")
        assert filepath.name.startswith("generation_")
        assert filepath.name.endswith(".csv")
        mock_df.to_csv.assert_called_once()
    
    def test_invalid_format(self, sample_data):
        with pytest.raises(EirGridIngestionError, match="Failed to save data"):
            save_raw_data(sample_data, "generation", format="xml")


class TestIngestGenerationData:
    @patch("ingest_eirgrid.save_raw_data")
    @patch("ingest_eirgrid.fetch_eirgrid_data")
    def test_successful_ingestion(self, mock_fetch, mock_save, sample_data):
        mock_fetch.return_value = sample_data
        mock_save.return_value = Path("/data/raw/generation_20250111.json")
        result = ingest_generation_data()
        mock_fetch.assert_called_once_with("generation", None)
        mock_save.assert_called_once()
        assert isinstance(result, Path)


class TestIngestAllEndpoints:
    @patch("ingest_eirgrid.save_raw_data")
    @patch("ingest_eirgrid.fetch_eirgrid_data")
    def test_ingest_all(self, mock_fetch, mock_save, sample_data):
        mock_fetch.return_value = sample_data
        mock_save.return_value = Path("/data/raw/test.json")
        results = ingest_all_endpoints()
        assert len(results) == 4
        assert all(isinstance(v, Path) for v in results.values() if v)
