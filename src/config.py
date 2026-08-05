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

# Open-Meteo weather API (no key required) - used to correlate wind/solar
# conditions with renewable generation
OPEN_METEO_BASE_URL = "https://api.open-meteo.com/v1/forecast"
WEATHER_LATITUDE = 53.3498  # Dublin
WEATHER_LONGITUDE = -6.2603
WEATHER_LOCATION_NAME = "Dublin"

# UK Carbon Intensity API (National Grid ESO, no key required) - real
# generation mix + measured/forecast carbon intensity for Great Britain,
# used as a second-country comparison against ENTSO-E's Irish data.
# Replaces the old EirGrid integration: EirGrid's live dashboard endpoint
# only returns a coarse 5-category snapshot (not the per-fuel-type time
# series this pipeline needs), while this API is official, documented,
# and returns exactly that shape.
CARBON_INTENSITY_BASE_URL = "https://api.carbonintensity.org.uk"
CARBON_INTENSITY_COUNTRY_CODE = "GB"

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_DELAY = 2
