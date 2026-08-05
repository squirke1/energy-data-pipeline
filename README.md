# Energy Data Pipeline

A Python-based ETL pipeline that ingests from three independent sources - ENTSO-E (European grid generation data), the UK Carbon Intensity API (Great Britain's generation mix and carbon intensity, for cross-country comparison), and Open-Meteo (weather, for correlating wind/solar conditions with renewable generation) - then validates, transforms, and loads it into a local database.

See [docs/DIAGRAMS.md](docs/DIAGRAMS.md) for the architecture, data flow, database schema, and branching model diagrams.

## Project Structure

```
energy-data-pipeline/
├── src/
│   ├── config.py                    # Configuration settings
│   ├── ingest_entsoe.py             # Data ingestion from ENTSO-E API (primary)
│   ├── ingest_carbon_intensity.py   # GB generation mix + carbon intensity (no API key)
│   ├── ingest_weather.py            # Weather ingestion from Open-Meteo (no API key)
│   ├── transform_energy.py          # Data transformation logic
│   ├── validate.py                  # Data validation
│   ├── load_db.py                   # Database loading
│   └── orchestrate.py               # Pipeline orchestration
├── data/
│   ├── raw/                   # Raw ingested data
│   └── processed/             # Transformed data
├── tests/                     # Unit tests
├── notebooks/                 # Jupyter notebooks for analysis
└── .github/workflows/         # CI/CD pipelines
```

## Features

### ✅ Stage 1: Data Ingestion
- Fetches generation data from ENTSO-E Transparency Platform (Ireland, token auth)
- Fetches generation mix + carbon intensity from the UK Carbon Intensity API (Great Britain, free, no API key)
- Fetches weather data (temperature, wind speed, solar radiation) from Open-Meteo - free, no API key required
- Saves raw data as CSV or JSON in `/data/raw`
- Comprehensive error handling and logging
- Mock data mode for every source, for testing without network access or API keys

### ✅ Stages 2-5: Validate, Transform, Load, Orchestrate
- `validate.py` checks generation data for missing intervals, out-of-range values, and stale timestamps
- `transform_energy.py` reshapes raw generation data into long/summary tables and flags renewable sources
- `load_db.py` loads validated, transformed data into a local SQLite database
- `orchestrate.py` chains ingest → validate → transform → load for each source, runnable independently or together

## Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/squirke1/energy-data-pipeline.git
   cd energy-data-pipeline
   ```

2. **Create and activate virtual environment**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate  # On macOS/Linux
   # or
   .venv\Scripts\activate  # On Windows
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure ENTSO-E API**
   - Register at https://transparency.entsoe.eu/
   - Get your API token from Account Settings
   - Copy `.env.example` to `.env` and add your key:
   ```bash
   cp .env.example .env
   # Edit .env and add: ENTSOE_API_KEY=your_actual_key_here
   ```

## Usage

### Ingesting Data

Each source can be ingested independently, with or without a mock flag - no credentials are needed for mock mode, and Open-Meteo (weather) needs none even live:

```bash
# ENTSO-E (needs ENTSOE_API_KEY, or use --mock)
python src/ingest_entsoe.py --mock
export ENTSOE_API_KEY="your_api_key_here"
python src/ingest_entsoe.py

# UK Carbon Intensity API (needs no key, live or mock)
python src/ingest_carbon_intensity.py --mock
python src/ingest_carbon_intensity.py

# Weather via Open-Meteo (needs no key, live or mock)
python src/ingest_weather.py --mock
python src/ingest_weather.py
```

> **Note:** Get your free ENTSO-E API key from [https://transparency.entsoe.eu](https://transparency.entsoe.eu). The key provides access to European electricity generation, load, and pricing data.

**Running the full pipeline (ingest → validate → transform → load):**

```bash
# All three sources, mock data
python src/orchestrate.py --mock

# A single source
python src/orchestrate.py --mock entsoe
python src/orchestrate.py --mock carbon_intensity
python src/orchestrate.py --mock weather
```

**Programmatic Usage:**

```python
from src.ingest_entsoe import ingest_generation_data
import os

# Set API key
os.environ["ENTSOE_API_KEY"] = "your_key_here"

# Ingest last 24 hours of generation data
filepath = ingest_generation_data(hours_back=24, save_format="csv")
```

## Testing

Run all tests:
```bash
pytest tests/ -v
```

Run specific test file:
```bash
pytest tests/test_ingest_entsoe.py -v
```

## CI/CD

This project uses GitHub Actions with GitFlow workflow:
- **main** - Production branch
- **develop** - Integration branch
- **feature/** - Feature branches
- **release/** - Release preparation
- **hotfix/** - Urgent production fixes

CI pipeline runs on all branches and includes:
- Linting with `ruff`
- Unit tests with `pytest`
- Artifact packaging (main branch only)

## Development

### Code Quality

Lint code:
```bash
ruff check src tests
```

### Git Workflow

1. Create feature branch from `develop`:
   ```bash
   git checkout develop
   git checkout -b feature/your-feature-name
   ```

2. Make changes and commit:
   ```bash
   git add .
   git commit -m "Description of changes"
   ```

3. Push and create PR to `develop`:
   ```bash
   git push origin feature/your-feature-name
   ```

## Configuration

Edit `src/config.py` to customize:
- API endpoints
- Data storage paths
- Logging levels
- Request timeouts and retry settings

## Next Steps

- [x] Stage 2: Data Transformation
- [x] Stage 3: Data Validation
- [x] Stage 4: Database Loading
- [x] Stage 5: Pipeline Orchestration
- [ ] Stage 6: Analysis Notebooks (correlate weather with renewable generation)

## License

See LICENSE file for details.
