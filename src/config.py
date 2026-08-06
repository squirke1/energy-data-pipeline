import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
PROCESSED_DATA_DIR = DATA_DIR / "processed"

PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)

# Postgres - validated/transformed data (generation_fact, generation_summary,
# pipeline_runs). Connection defaults match docker-compose.yml. Host port
# defaults to 5433 (not 5432) - a native/other local Postgres on 5432 is
# common and shouldn't collide with this project's container.
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5433"))
POSTGRES_DB = os.getenv("POSTGRES_DB", "energy_pipeline")
POSTGRES_USER = os.getenv("POSTGRES_USER", "pipeline")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "pipeline")

# MongoDB - raw ingested payloads, as received from each source, before
# validation/transformation. Schema-flexible on purpose: each source's
# JSON shape is different and can change without a migration. Host port
# defaults to 27018 (not 27017) for the same local-collision reason as
# Postgres above.
MONGO_HOST = os.getenv("MONGO_HOST", "localhost")
MONGO_PORT = int(os.getenv("MONGO_PORT", "27018"))
MONGO_DB = os.getenv("MONGO_DB", "energy_pipeline")
MONGO_USER = os.getenv("MONGO_USER", "pipeline")
MONGO_PASSWORD = os.getenv("MONGO_PASSWORD", "pipeline")
MONGO_RAW_COLLECTION = "raw_ingestions"

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
