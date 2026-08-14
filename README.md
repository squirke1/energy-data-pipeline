# Energy Data Pipeline

A Python-based ETL pipeline that ingests from three independent sources - ENTSO-E (European grid generation data), the UK Carbon Intensity API (Great Britain's generation mix and carbon intensity, for cross-country comparison), and Open-Meteo (weather, for correlating wind/solar conditions with renewable generation) - then validates, transforms, and loads it into Postgres.

See [docs/DIAGRAMS.md](docs/DIAGRAMS.md) for the architecture, data flow, database schema, and branching model diagrams.

## Project Structure

```
energy-data-pipeline/
├── src/
│   ├── config.py                    # Configuration settings
│   ├── base_source.py               # BaseSource ABC + shared IngestionError
│   ├── ingest_entsoe.py             # EntsoeSource(BaseSource) - ENTSO-E API (primary)
│   ├── ingest_carbon_intensity.py   # CarbonIntensitySource(BaseSource) - GB mix + carbon intensity
│   ├── ingest_weather.py            # WeatherSource(BaseSource) - Open-Meteo
│   ├── transform_energy.py          # GenerationTransformer
│   ├── validate.py                  # GenerationValidator
│   ├── load_db.py                   # PostgresDatabase - generation_fact/summary, raw_ingestions, pipeline_runs
│   └── orchestrate.py               # Orchestrator - ties every source together
├── data/
│   └── processed/             # Transformed output (reserved; not yet written to)
├── tests/                     # Unit tests
├── notebooks/                 # Jupyter notebooks for analysis
├── docker-compose.yml         # Local Postgres
└── .github/workflows/         # CI/CD pipelines
```

## Features

### ✅ Stage 1: Data Ingestion
- Fetches generation data from ENTSO-E Transparency Platform (Ireland, token auth)
- Fetches generation mix + carbon intensity from the UK Carbon Intensity API (Great Britain, free, no API key)
- Fetches weather data (temperature, wind speed, solar radiation) from Open-Meteo - free, no API key required
- Saves every source's raw payload to Postgres (`raw_ingestions` table, via a JSONB column), as received - schema-flexible, since each source's shape is different and can change without a migration
- Comprehensive error handling and logging
- Mock data mode for every source, for testing without network access or API keys

### ✅ Stages 2-5: Validate, Transform, Load, Orchestrate
- `GenerationValidator` (`validate.py`) checks generation data for missing intervals, out-of-range values, and stale timestamps
- `GenerationTransformer` (`transform_energy.py`) reshapes raw generation data into long/summary tables and flags renewable sources
- `PostgresDatabase` (`load_db.py`) loads validated, transformed data into Postgres (`generation_fact`, `generation_summary`, `pipeline_runs`). Only ENTSO-E has the fuel-type/MW shape this needs - the GB carbon-intensity and weather sources only ever reach `raw_ingestions`, never `generation_fact`/`generation_summary`, since they don't fit that schema
- `Orchestrator` (`orchestrate.py`) chains ingest → validate → transform → load for each source, runnable independently or together

### Design

Every ingestion source (`EntsoeSource`, `WeatherSource`, `CarbonIntensitySource`) subclasses `BaseSource`, which defines the shared `fetch()` / `generate_mock_data()` / `save()` / `ingest()` shape and a single `IngestionError` used by all three - so `Orchestrator` can handle any source polymorphically rather than needing per-source exception handling. Dependencies (`PostgresDatabase`, `GenerationValidator`, `GenerationTransformer`) are constructor-injected rather than imported as module globals, which is what makes the class-based tests able to swap in mocks/fakes cleanly.

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

5. **Start Postgres**
   ```bash
   docker compose up -d
   ```
   Defaults (in `docker-compose.yml` and `src/config.py`) use port **5433**, not the standard 5432 - deliberately, so this doesn't collide with a native/other local Postgres install. Override via `.env` (`POSTGRES_PORT`, etc.) if you'd rather use a different port or point at an existing instance.

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
from src.ingest_entsoe import EntsoeSource
import os

# Set API key
os.environ["ENTSOE_API_KEY"] = "your_key_here"

# Ingest last 24 hours of generation data - saves the raw payload to
# Postgres and returns its row id
raw_id = EntsoeSource(country_code="IE").ingest(hours_back=24)
```

## Testing

`tests/test_load.py` runs against a real local Postgres (not mocks) for genuine integration confidence, truncating tables before each test for isolation - so `docker compose up -d` must be running first. Everything else (ingestion, transform, validation) is mocked at the HTTP/client boundary and needs no live services.

Run all tests:
```bash
docker compose up -d
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

## Production Deployment

Beyond local development, the pipeline runs unattended on a schedule via a second workflow, `.github/workflows/scheduled-run.yml`, against a free-tier managed Postgres ([Neon](https://neon.tech)) instead of the local `docker-compose.yml` container.

### One-time setup

1. **Create a free Neon project** at [neon.tech](https://neon.tech) and grab its connection details (host, database name, user, password) from the project dashboard.
2. **Create a Slack incoming webhook** (a Slack app with "Incoming Webhooks" enabled, pointed at whichever channel you want failure alerts in) and copy its URL.
3. **Add them all as GitHub Actions secrets** on this repo (Settings → Secrets and variables → Actions), or via the CLI - each of these prompts for the value on stdin, so nothing sensitive needs to be pasted into a chat, a PR, or committed to the repo:
   ```bash
   gh secret set ENTSOE_API_KEY
   gh secret set POSTGRES_HOST
   gh secret set POSTGRES_PORT      # 5432 for Neon
   gh secret set POSTGRES_DB
   gh secret set POSTGRES_USER
   gh secret set POSTGRES_PASSWORD
   gh secret set SLACK_WEBHOOK_URL
   ```
4. The workflow runs every 6 hours (`workflow_dispatch` also allows a manual run from the Actions tab) and connects with `POSTGRES_SSLMODE=require`, since Neon is reachable over the internet - unlike the local dev Postgres, which has no SSL configured and isn't reachable outside your machine.

Retries (`src/retry.py`) mean a transient failure from any of the three upstream APIs doesn't fail the whole scheduled run - only a persistent one does. `orchestrate.py`'s CLI turns that into a real non-zero exit code (a `run_all()` catching each source's exceptions internally, to isolate one source's failure from the others, previously meant the process always exited 0 - fixed alongside this feature, since it would have made failure alerting silently never fire), which is what triggers a Slack message with a link to the failed run, on top of the failure always being recorded in `pipeline_runs` either way.

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
- Postgres connection settings (all overridable via `.env` - see `.env.example`)
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
