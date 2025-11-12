# Energy Data Pipeline

A Python-based ETL pipeline for ingesting, transforming, and analyzing energy generation data from EirGrid's Smart Grid Dashboard.

## Project Structure

```
energy-data-pipeline/
├── src/
│   ├── config.py              # Configuration settings
│   ├── ingest_eirgrid.py      # Data ingestion from EirGrid API
│   ├── transform_energy.py    # Data transformation logic
│   ├── validate.py            # Data validation
│   ├── load_db.py             # Database loading
│   └── orchestrate.py         # Pipeline orchestration
├── data/
│   ├── raw/                   # Raw ingested data
│   └── processed/             # Transformed data
├── tests/                     # Unit tests
├── notebooks/                 # Jupyter notebooks for analysis
└── .github/workflows/         # CI/CD pipelines
```

## Features

### ✅ Stage 1: Data Ingestion (Completed)
- Fetches data from EirGrid REST API endpoints
- Saves raw data as JSON or CSV in `/data/raw`
- Comprehensive error handling and retry logic
- Logging for all operations
- Mock data mode for testing when API is unavailable

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

## Usage

### Ingesting Data

**With Mock Data (recommended for development):**
```bash
python src/ingest_eirgrid.py --mock
```

**With Live API (when available):**
```bash
python src/ingest_eirgrid.py
```

> **Note:** The EirGrid API endpoints may be temporarily unavailable or require authentication. Use `--mock` flag for development and testing.

**Programmatic Usage:**
```python
from src.ingest_eirgrid import ingest_generation_data, ingest_all_endpoints

# Ingest generation data
filepath = ingest_generation_data(save_format="json")

# Ingest from all endpoints
results = ingest_all_endpoints(save_format="csv")
```

## Testing

Run all tests:
```bash
pytest tests/ -v
```

Run specific test file:
```bash
pytest tests/test_ingest.py -v
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

- [ ] Stage 2: Data Transformation
- [ ] Stage 3: Data Validation
- [ ] Stage 4: Database Loading
- [ ] Stage 5: Pipeline Orchestration
- [ ] Stage 6: Analysis Notebooks

## License

See LICENSE file for details.
