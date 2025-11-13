import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"

RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)

# ENTSO-E API Configuration
# Get API key from: https://transparency.entsoe.eu/content/static_content/Static%20content/web%20api/Guide.html
ENTSOE_COUNTRY_CODE = "IE"  # Ireland

# Legacy EirGrid endpoints (deprecated, kept for backward compatibility)
EIRGRID_BASE_URL = "https://www.smartgriddashboard.com/DashboardService.svc"
EIRGRID_ENDPOINTS = {
    "generation": f"{EIRGRID_BASE_URL}/data",
    "co2": f"{EIRGRID_BASE_URL}/co2",
    "frequency": f"{EIRGRID_BASE_URL}/frequency",
    "demand": f"{EIRGRID_BASE_URL}/demand",
}

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_DELAY = 2
