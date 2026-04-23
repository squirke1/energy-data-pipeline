# Energy Data Pipeline

Python ETL pipeline for European electricity generation data from the ENTSO-E API with automated testing and CI/CD.

Raw generation data is fetched from the [ENTSO-E Transparency Platform](https://transparency.entsoe.eu/), validated, transformed into a clean analytical schema, and persisted to a local SQLite database.

## Project Structure

```
energy-data-pipeline/
├── src/
│   ├── config.py              # Paths, API endpoints, logging config
│   ├── ingest_entsoe.py       # ENTSO-E API ingestion
│   ├── ingest_eirgrid.py      # EirGrid API ingestion (legacy)
│   ├── validate.py            # Input data validation
│   ├── transform_energy.py    # Reshaping, renewable flags, carbon intensity
│   ├── load_db.py             # SQLite persistence
│   └── orchestrate.py        # End-to-end pipeline runner
├── data/
│   ├── raw/                   # Raw ingested data (CSV/JSON)
│   ├── processed/             # Processed data
│   └── energy.db              # SQLite database (created on first run)
├── tests/                     # Unit tests (55 tests)
├── notebooks/                 # Jupyter notebooks for analysis
└── .github/workflows/ci.yml   # GitHub Actions CI/CD
```

## Pipeline Stages

| Stage | Module | Description |
|-------|--------|-------------|
| Ingest | `ingest_entsoe.py` | Fetches generation data from ENTSO-E API |
| Validate | `validate.py` | Checks schema, ranges, nulls, duplicates |
| Transform | `transform_energy.py` | Wide→long melt, renewable flag, carbon intensity |
| Load | `load_db.py` | Upserts into SQLite (`generation_fact`, `generation_summary`) |
| Orchestrate | `orchestrate.py` | Runs all stages end-to-end |

### What the transform stage produces

**`generation_fact`** — one row per timestamp × fuel type:

| column | type | notes |
|--------|------|-------|
| timestamp | TEXT | 15-min intervals |
| country_code | TEXT | e.g. `IE` |
| fuel_type | TEXT | e.g. `Wind Onshore` |
| generation_mw | REAL | clipped to ≥ 0 |
| is_renewable | INTEGER | 1 for wind, solar, hydro, etc. |
| processed_at | TEXT | UTC timestamp of pipeline run |

**`generation_summary`** — one row per timestamp:

| column | type | notes |
|--------|------|-------|
| total_generation_mw | REAL | sum across all fuel types |
| renewable_mw | REAL | sum of renewable sources |
| renewable_pct | REAL | `renewable_mw / total * 100` |
| carbon_intensity_g_per_kwh | REAL | weighted avg using per-fuel emission factors |

## Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/squirke1/energy-data-pipeline.git
   cd energy-data-pipeline
   ```

2. **Create and activate virtual environment**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate  # Linux/macOS
   .venv\Scripts\activate      # Windows
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure ENTSO-E API key** (skip if using mock data)
   - Register at https://transparency.entsoe.eu/
   - Copy `.env.example` to `.env` and fill in your key:
   ```bash
   cp .env.example .env
   # ENTSOE_API_KEY=your_actual_key_here
   ```

## Usage

### Run the full pipeline

```bash
# Both sources, mock data (no API key needed)
python src/orchestrate.py --mock both

# ENTSO-E source only, last 24 hours of live data
python src/orchestrate.py entsoe

# EirGrid source only
python src/orchestrate.py eirgrid
```

### Run individual stages

```bash
# Ingest only
python src/ingest_entsoe.py --mock

# Validate raw CSV
python -c "
import pandas as pd, sys
sys.path.insert(0, 'src')
from validate import validate_generation_df
df = pd.read_csv('data/raw/entsoe_generation_<timestamp>.csv', index_col=0, parse_dates=True)
result = validate_generation_df(df)
print(result.summary())
"
```

### Programmatic API

```python
import sys
sys.path.insert(0, "src")

from orchestrate import run_entsoe_pipeline

# Run with mock data
result = run_entsoe_pipeline(hours_back=24, mock=True)
print(result)
# {'status': 'success', 'source': 'entsoe', 'fact_rows': 291, 'summary_rows': 97, ...}

# Query the database
from load_db import query_generation_summary
df = query_generation_summary(country_code="IE", limit=48)
print(df[["timestamp", "renewable_pct", "carbon_intensity_g_per_kwh"]])
```

## Testing

```bash
# Run all 55 tests
pytest tests/ -v

# Run by module
pytest tests/test_ingest.py -v
pytest tests/test_transform.py -v
pytest tests/test_load.py -v
```

## CI/CD

GitHub Actions runs on push and pull request to `main`, `develop`, `feature/**`, `release/**`, and `hotfix/**`:

1. **Lint** — `ruff check src tests`
2. **Test** — `pytest tests/ -v` on Python 3.10 and 3.11
3. **Package** — tarballs `src/` + `requirements.txt` as a build artifact (main/release/hotfix branches only)

## Configuration

`src/config.py` controls:

| variable | default | description |
|----------|---------|-------------|
| `ENTSOE_COUNTRY_CODE` | `IE` | Country for API queries |
| `REQUEST_TIMEOUT` | `30` | HTTP timeout (seconds) |
| `MAX_RETRIES` | `3` | Retries on transient failures |
| `LOG_LEVEL` | `INFO` | Override with `LOG_LEVEL=DEBUG` env var |

## License

See LICENSE file for details.
