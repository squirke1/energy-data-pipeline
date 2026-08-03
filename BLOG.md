# Building a European Energy Data Pipeline: An ETL Deep Dive

Electricity grids produce a constant stream of data — how much power is being generated, by what fuel source, and when. That data is public, but turning it into something usable means solving a familiar set of data engineering problems: unreliable sources, authentication, retries, formats, testing, and deployment. This post walks through the stack behind `energy-data-pipeline`, a Python ETL project for ingesting European electricity generation data, and the design decisions behind Stage 1 of its pipeline.

## What the pipeline does

At a high level, this is a classic ETL shape:

```
energy-data-pipeline/
├── src/
│   ├── config.py              # Configuration settings
│   ├── ingest_entsoe.py       # Extract: pull data from ENTSO-E
│   ├── transform_energy.py    # Transform: clean/reshape (not yet built)
│   ├── validate.py            # Validate: data quality checks (not yet built)
│   ├── load_db.py             # Load: persist to a database (not yet built)
│   └── orchestrate.py         # Orchestration (not yet built)
├── data/
│   ├── raw/                   # Extracted data, untouched
│   └── processed/             # Transformed output
└── tests/
```

Right now, only the **Extract** stage is implemented. That's deliberate — get one stage production-quality (tested, linted, CI-gated) before building on top of it, rather than sketching all five stages at once and having none of them be trustworthy.

## The extraction layer: two sources, one lesson

The interesting part of this project isn't the code that exists today — it's the code that got replaced. The first ingestion source was **EirGrid's Smart Grid Dashboard**, Ireland's transmission system operator, scraped via its internal dashboard API:

```python
EIRGRID_BASE_URL = "https://www.smartgriddashboard.com/DashboardService.svc"
EIRGRID_ENDPOINTS = {
    "generation": f"{EIRGRID_BASE_URL}/data",
    "co2": f"{EIRGRID_BASE_URL}/co2",
    "frequency": f"{EIRGRID_BASE_URL}/frequency",
    "demand": f"{EIRGRID_BASE_URL}/demand",
}
```

This worked, and `ingest_eirgrid.py` still exists with retry logic and test coverage. But it's an **undocumented internal endpoint** built for a dashboard, not a public API: no versioning guarantees, no official auth, and it only covers Ireland. That's a fragile foundation for a pipeline meant to be a data source for downstream analysis.

The fix was migrating to **[ENTSO-E's Transparency Platform](https://transparency.entsoe.eu/)** — the official pan-European API published by the association of electricity transmission operators. It's authenticated with a proper API token, versioned, and covers generation, load, prices, and cross-border flows for 30+ European market zones, not just one country. That's the difference between scraping a website and integrating with a system designed to be integrated with — and it's the kind of tradeoff worth catching early, before three more pipeline stages get built on the shakier source.

## The stack

| Concern | Tool | Why |
|---|---|---|
| API client | [`entsoe-py`](https://github.com/EnergieID/entsoe-py) (`EntsoePandasClient`) | Wraps ENTSO-E's XML-based SOAP-ish API and hands back pandas DataFrames directly — no manual XML parsing |
| Data handling | `pandas` | Time-indexed generation data, timezone conversion, CSV/JSON export |
| Secrets | `python-dotenv` | API key loaded from `.env`, never hardcoded or committed |
| HTTP (legacy source) | `requests` | Manual retry/timeout logic for the EirGrid scraper |
| Lint | `ruff` | Fast, single-tool linting in CI |
| Tests | `pytest` | Unit tests per ingestion module |
| CI/CD | GitHub Actions | Lint + test matrix across Python 3.10/3.11, artifact packaging on release branches |

The extraction code itself is intentionally small — three functions doing one job each:

```python
def get_entsoe_client() -> EntsoePandasClient:
    api_key = os.getenv("ENTSOE_API_KEY")
    if not api_key:
        raise EntsoeIngestionError("ENTSOE_API_KEY not set. Get your key from https://transparency.entsoe.eu")
    return EntsoePandasClient(api_key=api_key)

def fetch_generation(start, end, country_code="IE") -> pd.DataFrame:
    client = get_entsoe_client()
    df = client.query_generation(country_code=country_code, start=start, end=end)
    df.index = df.index.tz_convert("Europe/Dublin")
    df["country_code"] = country_code
    return df

def save_generation_data(df: pd.DataFrame, format: str = "csv") -> Path:
    ...
```

One deliberate feature worth calling out: **mock data mode**. `generate_mock_data()` produces a synthetic DataFrame with the same shape as a real ENTSO-E response — same columns, same 15-minute time index — so the rest of the pipeline (and anyone cloning the repo) can be developed and tested without an API key or hitting rate limits:

```bash
python src/ingest_entsoe.py --mock
```

This is a small thing that pays off disproportionately: it decouples "does my pipeline code work" from "do I have valid credentials and network access right now," which matters a lot in CI and even more when a teammate is onboarding.

## CI/CD as a pipeline for the pipeline

The project uses GitFlow (`main` / `develop` / `feature/*` / `release/*` / `hotfix/*`), and GitHub Actions enforces quality at every branch:

```yaml
jobs:
  lint-test:
    strategy:
      matrix:
        python-version: ["3.10", "3.11"]
    steps:
      - run: ruff check src tests
      - run: pytest tests/ -v

  package:
    needs: lint-test
    if: github.ref == 'refs/heads/main' || startsWith(github.ref, 'refs/heads/release/') || startsWith(github.ref, 'refs/heads/hotfix/')
    steps:
      - run: tar -czf dist/energy-data-pipeline.tar.gz src requirements.txt
```

Every push and PR gets linted and tested across two Python versions before anything merges. Packaging only runs on branches that are actually headed to production. It's a small pipeline, but the same principle that applies to the data — validate before it moves downstream — applies to the code too.

## What's next

Stage 1 (extraction) is done. The stub files already sketch the rest of the roadmap:

- **Transform** (`transform_energy.py`) — reshape raw generation data into a clean, analysis-ready schema
- **Validate** (`validate.py`) — data quality checks (missing intervals, negative generation values, stale timestamps) before anything gets loaded
- **Load** (`load_db.py`) — persist processed data to a database
- **Orchestrate** (`orchestrate.py`) — tie extract → transform → validate → load into a single scheduled run

The pattern established in Stage 1 — small single-purpose functions, mock-data support, tests and lint gating every merge — is the template the rest of the pipeline will follow.
