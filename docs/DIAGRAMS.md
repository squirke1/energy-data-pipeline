# Architecture & Data Flow

Reference diagrams for `energy-data-pipeline`. These render natively on GitHub (no plugins needed) since they're standard Mermaid fenced code blocks.

## System context (C4 level 1)

The zoomed-out view before the detail: what's inside the system boundary versus what's external to it. One actor (a developer or a CI job, running the same CLI either way), three external data sources, one local sink.

```mermaid
C4Context
    title System Context — energy-data-pipeline

    Person(dev, "Developer / CI job", "Runs the pipeline via CLI, locally or in GitHub Actions, identically either way")

    System(pipeline, "energy-data-pipeline", "Ingests, validates, transforms, and loads energy + weather data")

    System_Ext(entsoe, "ENTSO-E Transparency Platform", "Irish grid generation data. Token auth, email-gated approval")
    System_Ext(carbon, "UK Carbon Intensity API", "GB generation mix + carbon intensity. Official (National Grid ESO), fully public, no auth")
    System_Ext(meteo, "Open-Meteo", "Weather data (temperature, wind, solar radiation). Fully public, no auth")

    SystemDb(db, "data/energy.db", "Local SQLite database - generation_fact, generation_summary, pipeline_runs")

    Rel(dev, pipeline, "Runs", "CLI, --mock or live")
    Rel(pipeline, entsoe, "Fetches generation data", "HTTPS + token")
    Rel(pipeline, carbon, "Fetches generation mix", "HTTPS")
    Rel(pipeline, meteo, "Fetches weather data", "HTTPS")
    Rel(pipeline, db, "Reads / writes", "sqlite3")
```

## System architecture

Three independently-authenticated sources, coordinated by `orchestrate.py`. Only ENTSO-E has the `fuel_type`/`is_renewable` shape that `validate.py`/`transform_energy.py` are built around, so it's the only source that earns the full validate → transform → load path into `generation_fact`/`generation_summary`. The GB carbon-intensity source and weather both go straight to storage plus the shared run-log instead of being forced into a schema that doesn't fit their data.

```mermaid
flowchart TD
    subgraph ext["External sources"]
        ENTSOE["ENTSO-E Transparency Platform<br/><i>token auth, Ireland</i>"]
        CARBON["UK Carbon Intensity API<br/><i>no auth, Great Britain</i>"]
        METEO["Open-Meteo<br/><i>no auth, no signup</i>"]
    end

    subgraph ingest["Ingestion — src/ingest_*.py"]
        I_ENTSOE["ingest_entsoe.py"]
        I_CARBON["ingest_carbon_intensity.py"]
        I_WEATHER["ingest_weather.py"]
    end

    ENTSOE --> I_ENTSOE
    CARBON --> I_CARBON
    METEO --> I_WEATHER

    I_ENTSOE --> RAW[("data/raw/*.csv, *.json")]
    I_CARBON --> RAW
    I_WEATHER --> RAW

    I_ENTSOE --> VALIDATE["validate.py<br/>validate_generation_df()"]
    VALIDATE --> TRANSFORM["transform_energy.py<br/>melt, flag renewables,<br/>compute carbon intensity"]
    TRANSFORM --> LOAD["load_db.py<br/>load_generation_fact()<br/>load_generation_summary()"]

    I_CARBON --> SAVE_C["save_generation_mix_data()"]
    I_WEATHER --> SAVE_W["save_weather_data()"]

    LOAD --> DB[("data/energy.db — SQLite")]
    SAVE_C --> RUNLOG["log_pipeline_run()"]
    SAVE_W --> RUNLOG
    LOAD --> RUNLOG
    RUNLOG --> DB

    ORCH["orchestrate.py"]:::orch -.controls.-> I_ENTSOE
    ORCH -.controls.-> I_CARBON
    ORCH -.controls.-> I_WEATHER
    ORCH -.controls.-> VALIDATE
    ORCH -.controls.-> TRANSFORM
    ORCH -.controls.-> LOAD

    classDef orch fill:#5b8def,color:#fff,stroke:#3a6bc7
```

## Data flow (swimlanes by source)

Each source is its own lane through `orchestrate.py`. ENTSO-E earns its way into `generation_fact`/`generation_summary` through validate → transform → load, and can fail at the validate step; the GB carbon-intensity source and weather have no `fuel_type`/MW generation shape to validate or transform against, so their lanes are shorter by design, not by omission. All three converge on the same `log_pipeline_run()` call, so every run - success or failure, any source - lands in one queryable place.

```mermaid
flowchart TB
    subgraph L1["ENTSO-E lane"]
        direction LR
        A1["Fetch<br/>(live or --mock)"] --> A2{"Validate<br/>validate_generation_df()"}
        A2 -- passed --> A3["Transform<br/>melt, flag renewable,<br/>carbon intensity"]
        A3 --> A4["Load<br/>generation_fact +<br/>generation_summary"]
        A2 -- failed --> A5["raise ValueError"]
    end

    subgraph L2["Carbon intensity lane (GB)"]
        direction LR
        B1["Fetch<br/>(live or --mock)"] --> B2["Save raw CSV/JSON<br/>to data/raw/"]
    end

    subgraph L3["Weather lane"]
        direction LR
        C1["Fetch<br/>(live or --mock)"] --> C2["Save raw CSV/JSON<br/>to data/raw/"]
    end

    A4 --> LOG["log_pipeline_run(source, status)"]
    A5 --> LOG
    B2 --> LOG
    C2 --> LOG
    LOG --> DB[("data/energy.db")]
```

## Run sequence (success and failure paths)

The swimlane diagram shows *what path data takes*; this shows *who calls whom, in what order* - including what happens when validation fails. `run_entsoe_pipeline()` is the only source with a validate/transform branch to show; `run_carbon_intensity_pipeline()` and `run_weather_pipeline()` are a shorter fetch → save → log sequence (see the swimlane diagram above).

```mermaid
sequenceDiagram
    actor CLI as orchestrate.py __main__
    participant Orch as run_entsoe_pipeline()
    participant Ingest as ingest_entsoe.py
    participant Val as validate.py
    participant Trans as transform_energy.py
    participant Load as load_db.py
    participant DB as data/energy.db

    CLI->>Orch: run_entsoe_pipeline(mock=True)
    Orch->>Load: init_db()
    Orch->>Ingest: fetch_generation() / generate_mock_data()
    Ingest-->>Orch: raw_df
    Orch->>Val: validate_generation_df(raw_df)
    Val-->>Orch: ValidationResult

    alt validation passed
        Orch->>Trans: transform_entsoe_generation(raw_df)
        Trans-->>Orch: long_df, summary_df
        Orch->>Load: load_generation_fact(long_df)
        Orch->>Load: load_generation_summary(summary_df)
        Load->>DB: upsert rows
        Orch->>Load: log_pipeline_run("entsoe", fact_rows, "success")
        Load->>DB: insert pipeline_runs row
        Orch-->>CLI: {"status": "success", ...}
    else validation failed
        Orch->>Orch: raise ValueError(validation.errors)
        Orch->>Load: log_pipeline_run("entsoe", 0, "failed", str(e))
        Load->>DB: insert pipeline_runs row
        Orch--xCLI: exception propagates
        CLI->>CLI: caught by top-level except,<br/>printed, other sources still run
    end
```

## Database schema

SQLite, created and upserted by `load_db.py`. Fact and summary rows aren't linked by a foreign key — they're correlated by `(timestamp, country_code)`, which is also the natural join key for a future weather-vs-generation analysis (Stage 6).

```mermaid
erDiagram
    generation_fact {
        int id PK
        text timestamp
        text country_code
        text fuel_type
        real generation_mw
        int is_renewable
        text processed_at
    }
    generation_summary {
        int id PK
        text timestamp
        text country_code
        real total_generation_mw
        real renewable_mw
        real renewable_pct
        real carbon_intensity_g_per_kwh
        text processed_at
    }
    pipeline_runs {
        int id PK
        text run_at
        text source
        int rows_loaded
        text status
        text message
    }

    generation_fact }o..o{ generation_summary : "same timestamp + country_code"
```

## CI/CD pipeline

From `.github/workflows/ci.yml`. Every push and PR gets linted and tested across both Python versions; only branches actually headed to production get packaged.

```mermaid
flowchart TD
    TRIGGER["push or pull_request<br/>main, develop, feature/**, release/**, hotfix/**"] --> M1

    subgraph matrix["Lint and Test — matrix: Python 3.10, 3.11"]
        direction LR
        M1["Checkout"] --> M2["Set up Python"] --> M3["pip install -r requirements.txt<br/>pip install pytest ruff"] --> M4["ruff check src tests"] --> M5["pytest tests/ -v"]
    end

    M5 --> GATE{"branch is<br/>main / release/* / hotfix/*?"}
    GATE -- yes --> PKG["Package artifact<br/>tar czf dist/energy-data-pipeline.tar.gz<br/>src requirements.txt"]
    GATE -- no --> SKIP["Package job skipped"]
    PKG --> UPLOAD["Upload artifact<br/>(GitHub Actions artifact store)"]
```

## Branching model (GitFlow)

```mermaid
gitGraph
    commit id: "init"
    branch develop
    checkout develop
    commit id: "stage1: ingestion"
    branch feature/x
    checkout feature/x
    commit id: "work"
    checkout develop
    merge feature/x
    commit id: "stage2-5: pipeline"
    checkout main
    merge develop tag: "release"
```

- `feature/*` branches off `develop`, PRs back into `develop`
- `develop` → `main` only via a reviewed PR (never a direct push)
- CI (`ruff check` + `pytest`) gates every push and PR on every branch; artifact packaging only runs on `main`/`release/*`/`hotfix/*`
