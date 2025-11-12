import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Any

import requests
import pandas as pd

from config import (
    EIRGRID_ENDPOINTS,
    RAW_DATA_DIR,
    REQUEST_TIMEOUT,
    MAX_RETRIES,
    RETRY_DELAY,
    LOG_FORMAT,
    LOG_DATE_FORMAT,
    LOG_LEVEL,
)

logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
logger = logging.getLogger(__name__)


class EirGridIngestionError(Exception):
    pass


def fetch_eirgrid_data(endpoint_name: str, params: Optional[Dict[str, Any]] = None, 
                       retry_count: int = 0) -> Dict[str, Any]:
    if endpoint_name not in EIRGRID_ENDPOINTS:
        raise EirGridIngestionError(
            f"Unknown endpoint: {endpoint_name}. "
            f"Available: {list(EIRGRID_ENDPOINTS.keys())}"
        )
    
    url = EIRGRID_ENDPOINTS[endpoint_name]
    logger.info(f"Fetching {endpoint_name}: {url}")
    
    try:
        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        logger.info(f"Fetched {endpoint_name} successfully")
        return data
        
    except requests.exceptions.Timeout as e:
        if retry_count < MAX_RETRIES:
            logger.warning(f"Timeout, retrying {retry_count + 1}/{MAX_RETRIES}")
            time.sleep(RETRY_DELAY)
            return fetch_eirgrid_data(endpoint_name, params, retry_count + 1)
        raise EirGridIngestionError(f"Timeout after {MAX_RETRIES} retries") from e
        
    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP error: {e}")
        raise EirGridIngestionError(str(e)) from e
        
    except requests.exceptions.RequestException as e:
        if retry_count < MAX_RETRIES:
            logger.warning(f"Request failed, retrying {retry_count + 1}/{MAX_RETRIES}")
            time.sleep(RETRY_DELAY)
            return fetch_eirgrid_data(endpoint_name, params, retry_count + 1)
        raise EirGridIngestionError(f"Failed after {MAX_RETRIES} retries") from e
        
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON: {e}")
        raise EirGridIngestionError("Invalid JSON response") from e


def save_raw_data(data: Dict[str, Any], endpoint_name: str, format: str = "json") -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{endpoint_name}_{timestamp}.{format}"
    filepath = RAW_DATA_DIR / filename
    
    try:
        if format == "json":
            with open(filepath, "w") as f:
                json.dump(data, f, indent=2)
        elif format == "csv":
            df = pd.json_normalize(data)
            df.to_csv(filepath, index=False)
        else:
            raise EirGridIngestionError(f"Unsupported format: {format}")
        
        logger.info(f"Saved to {filepath}")
        return filepath
        
    except Exception as e:
        logger.error(f"Save failed: {e}")
        raise EirGridIngestionError("Failed to save data") from e


def ingest_generation_data(save_format: str = "json", 
                          params: Optional[Dict[str, Any]] = None) -> Path:
    try:
        data = fetch_eirgrid_data("generation", params)
        
        if isinstance(data, dict) and data.get("Status") == "Error":
            logger.warning(f"API error: {data.get('ErrorMessage', 'Unknown')}")
        
        filepath = save_raw_data(data, "generation", save_format)
        
        if isinstance(data, dict) and data.get("Rows"):
            logger.info(f"Ingested {len(data['Rows'])} rows to {filepath}")
        else:
            logger.warning("No data rows in response")
        
        return filepath
        
    except EirGridIngestionError:
        logger.error("Ingestion failed")
        raise


def ingest_all_endpoints(save_format: str = "json") -> Dict[str, Path]:
    results = {}
    
    for endpoint_name in EIRGRID_ENDPOINTS.keys():
        try:
            data = fetch_eirgrid_data(endpoint_name)
            filepath = save_raw_data(data, endpoint_name, save_format)
            results[endpoint_name] = filepath
        except EirGridIngestionError as e:
            logger.error(f"{endpoint_name} failed: {e}")
            results[endpoint_name] = None
    
    succeeded = len([v for v in results.values() if v])
    logger.info(f"Completed: {succeeded}/{len(results)} endpoints")
    return results


def generate_mock_data() -> Dict[str, Any]:
    return {
        "Rows": [
            {"FieldName": "Wind", "Value": "1234", "Percent": "25.5"},
            {"FieldName": "Gas", "Value": "2000", "Percent": "41.3"},
            {"FieldName": "Coal", "Value": "500", "Percent": "10.3"},
            {"FieldName": "Hydro", "Value": "150", "Percent": "3.1"},
            {"FieldName": "Solar", "Value": "80", "Percent": "1.7"},
            {"FieldName": "Other", "Value": "876", "Percent": "18.1"},
        ],
        "LastUpdated": datetime.now().isoformat(),
        "Status": "OK",
    }


if __name__ == "__main__":
    import sys
    
    if "--mock" in sys.argv:
        logger.info("Using mock data")
        mock_data = generate_mock_data()
        filepath = save_raw_data(mock_data, "generation_mock", "json")
        print(f"Saved to: {filepath}")
    else:
        try:
            filepath = ingest_generation_data(save_format="json")
            print(f"Saved to: {filepath}")
        except EirGridIngestionError as e:
            print(f"Failed: {e}")
            print("Try: python src/ingest_eirgrid.py --mock")
