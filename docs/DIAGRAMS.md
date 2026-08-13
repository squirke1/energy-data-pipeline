# Architecture & Data Flow

Reference diagrams for `energy-data-pipeline`. These render natively on GitHub (no plugins needed) since they're standard Mermaid fenced code blocks.

## System context (C4 level 1)

The zoomed-out view before the detail: what's inside the system boundary versus what's external to it. One actor (a developer or a CI job, running the same CLI either way), three external data sources, one local sink - a single relational store for both trusted, validated data and raw payloads (via a JSONB column for the latter).

```mermaid
C4Context
    title System Context — energy-data-pipeline

    Person(dev, "Developer / CI job", "Runs the pipeline via CLI, locally or in GitHub Actions, identically either way")

    System(pipeline, "energy-data-pipeline", "Ingests, validates, transforms, and loads energy + weather data")

    System_Ext(entsoe, "ENTSO-E Transparency Platform", "Irish grid generation data. Token auth, email-gated approval")
    System_Ext(carbon, "UK Carbon Intensity API", "GB generation mix + carbon intensity. Official (National Grid ESO), fully public, no auth")
    System_Ext(meteo, "Open-Meteo", "Weather data (temperature, wind, solar radiation). Fully public, no auth")

    SystemDb(pg, "Postgres", "Validated/transformed data (generation_fact, generation_summary), raw ingested payloads (raw_ingestions), pipeline_runs")

    Rel(dev, pipeline, "Runs", "CLI, --mock or live")
    Rel(pipeline, entsoe, "Fetches generation data", "HTTPS + token")
    Rel(pipeline, carbon, "Fetches generation mix", "HTTPS")
    Rel(pipeline, meteo, "Fetches weather data", "HTTPS")
    Rel(pipeline, pg, "Reads / writes", "psycopg2")
```

## Class hierarchy

Every source subclasses `BaseSource`, which is what lets `Orchestrator` treat `EntsoeSource`, `WeatherSource`, and `CarbonIntensitySource` interchangeably for the parts of the pipeline that don't care which one it is - `save()`/`ingest()` and the single `IngestionError` type. `Orchestrator`'s other dependencies (`PostgresDatabase`, `GenerationValidator`, `GenerationTransformer`) are constructor-injected rather than module-level globals, which is what lets tests substitute fakes/mocks instead of monkeypatching module functions.

```mermaid
classDiagram
    class BaseSource {
        <<abstract>>
        +source_name: str
        +db: PostgresDatabase
        +fetch(hours_back)* DataFrame
        +generate_mock_data(hours)* DataFrame
        +save(df) str
        +ingest(hours_back) str
    }
    class EntsoeSource {
        +country_code: str
        +get_client() EntsoePandasClient
    }
    class WeatherSource
    class CarbonIntensitySource

    BaseSource <|-- EntsoeSource
    BaseSource <|-- WeatherSource
    BaseSource <|-- CarbonIntensitySource

    class Orchestrator {
        +db: PostgresDatabase
        +validator: GenerationValidator
        +transformer: GenerationTransformer
        +run_entsoe(hours_back, country_code, mock) dict
        +run_weather(hours_back, mock) dict
        +run_carbon_intensity(hours_back, mock) dict
    }
    Orchestrator --> BaseSource : fetches from
    Orchestrator --> PostgresDatabase : loads into
    Orchestrator --> GenerationValidator : validates with
    Orchestrator --> GenerationTransformer : transforms with
```

## System architecture

Three independently-authenticated sources, coordinated by `orchestrate.py`. Every source's raw payload goes to Postgres's `raw_ingestions` table via `PostgresDatabase.save_raw()` first - that's the "bronze" layer, schema-flexible on purpose via a JSONB column. Only ENTSO-E has the `fuel_type`/`is_renewable` shape that `validate.py`/`transform_energy.py` are built around, so it's the only source that additionally earns the validate → transform → load path into `generation_fact`/`generation_summary` - the "silver" layer. Bronze and silver are just tables in the same database now, not separate engines.

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

    I_ENTSOE --> RAWSAVE["PostgresDatabase<br/>.save_raw()"]
    I_CARBON --> RAWSAVE
    I_WEATHER --> RAWSAVE
    RAWSAVE --> PG[("Postgres<br/>raw_ingestions, generation_fact,<br/>generation_summary")]

    I_ENTSOE --> VALIDATE["GenerationValidator<br/>.validate()"]
    VALIDATE --> TRANSFORM["GenerationTransformer<br/>melt, flag renewables,<br/>compute carbon intensity"]
    TRANSFORM --> LOAD["PostgresDatabase<br/>.load_generation_fact()<br/>.load_generation_summary()"]

    LOAD --> PG
    LOAD --> RUNLOG["PostgresDatabase<br/>.log_pipeline_run()"]
    RAWSAVE -.after save.-> RUNLOG
    RUNLOG --> PG

    ORCH["Orchestrator"]:::orch -.controls.-> I_ENTSOE
    ORCH -.controls.-> I_CARBON
    ORCH -.controls.-> I_WEATHER
    ORCH -.controls.-> VALIDATE
    ORCH -.controls.-> TRANSFORM
    ORCH -.controls.-> LOAD

    classDef orch fill:#5b8def,color:#fff,stroke:#3a6bc7
```

## Data flow (swimlanes by source)

Each source is its own lane through `Orchestrator`. ENTSO-E earns its way into Postgres's `generation_fact`/`generation_summary` through validate → transform → load, and can fail at the validate step; the GB carbon-intensity source and weather have no `fuel_type`/MW generation shape to validate or transform against, so their lanes are shorter by design, not by omission - straight to `raw_ingestions`. All three converge on the same `PostgresDatabase.log_pipeline_run()` call, so every run - success or failure, any source - lands in one queryable table.

```mermaid
flowchart TB
    subgraph L1["EntsoeSource lane"]
        direction LR
        A1["source.fetch()<br/>(live or --mock)"] --> A2{"GenerationValidator<br/>.validate()"}
        A2 -- passed --> A3["GenerationTransformer<br/>melt, flag renewable,<br/>carbon intensity"]
        A3 --> A4["PostgresDatabase<br/>generation_fact +<br/>generation_summary"]
        A2 -- failed --> A5["raise ValueError"]
    end

    subgraph L2["CarbonIntensitySource lane (GB)"]
        direction LR
        B1["source.fetch()<br/>(live or --mock)"] --> B2["source.save()<br/>to raw_ingestions"]
    end

    subgraph L3["WeatherSource lane"]
        direction LR
        C1["source.fetch()<br/>(live or --mock)"] --> C2["source.save()<br/>to raw_ingestions"]
    end

    A4 --> PG[("Postgres")]
    B2 --> PG
    C2 --> PG

    A4 --> LOG["PostgresDatabase<br/>.log_pipeline_run(source, status)"]
    A5 --> LOG
    B2 --> LOG
    C2 --> LOG
    LOG --> PG
```

## Run sequence (success and failure paths)

The swimlane diagram shows *what path data takes*; this shows *who calls whom, in what order* - including what happens when validation fails. `Orchestrator.run_entsoe()` is the only source with a validate/transform branch to show; `run_carbon_intensity()` and `run_weather()` share one private helper, `_run_raw_only_pipeline()`, for their shorter fetch → save → log sequence (see the swimlane diagram above).

```mermaid
sequenceDiagram
    actor CLI as orchestrate.py __main__
    participant Orch as Orchestrator.run_entsoe()
    participant Source as EntsoeSource
    participant Val as GenerationValidator
    participant Trans as GenerationTransformer
    participant DB as PostgresDatabase

    CLI->>Orch: orchestrator.run_entsoe(mock=True)
    Orch->>DB: init_db()
    Orch->>Source: source.fetch() / source.generate_mock_data()
    Source-->>Orch: raw_df
    Orch->>Val: validator.validate(raw_df)
    Val-->>Orch: ValidationResult

    alt validation passed
        Orch->>Trans: transformer.transform_entsoe_generation(raw_df)
        Trans-->>Orch: long_df, summary_df
        Orch->>DB: load_generation_fact(long_df)
        Orch->>DB: load_generation_summary(summary_df)
        DB->>DB: upsert rows (Postgres)
        Orch->>DB: log_pipeline_run("entsoe", fact_rows, "success")
        DB->>DB: insert pipeline_runs row
        Orch-->>CLI: {"status": "success", ...}
    else validation failed
        Orch->>Orch: raise ValueError(validation.errors)
        Orch->>DB: log_pipeline_run("entsoe", 0, "failed", str(e))
        DB->>DB: insert pipeline_runs row
        Orch--xCLI: exception propagates
        CLI->>CLI: caught by top-level except,<br/>printed, other sources still run
    end
```

## Database schema

### Postgres

All four tables are created and owned by `PostgresDatabase`. `generation_fact`/`generation_summary` are upserted via `INSERT ... ON CONFLICT DO UPDATE`; fact and summary rows aren't linked by a foreign key — they're correlated by `(timestamp, country_code)`, which is also the natural join key for a future weather-vs-generation analysis (Stage 6). `raw_ingestions` is the bronze layer — no fixed schema on `payload`, since it's whatever shape the source's DataFrame produced (a `JSONB` column, not a set of typed columns), which is exactly the point: a new source, or a source's API changing shape, needs no migration here. It has no `UNIQUE` constraint (unlike the other three) since every ingest run appends a new row rather than upserting.

```mermaid
erDiagram
    generation_fact {
        serial id PK
        timestamptz timestamp
        text country_code
        text fuel_type
        double generation_mw
        boolean is_renewable
        timestamptz processed_at
    }
    generation_summary {
        serial id PK
        timestamptz timestamp
        text country_code
        double total_generation_mw
        double renewable_mw
        double renewable_pct
        double carbon_intensity_g_per_kwh
        timestamptz processed_at
    }
    pipeline_runs {
        serial id PK
        timestamptz run_at
        text source
        int rows_loaded
        text status
        text message
    }
    raw_ingestions {
        serial id PK
        text source
        timestamptz ingested_at
        text format
        jsonb payload
    }

    generation_fact }o..o{ generation_summary : "same timestamp + country_code"
```

Example `raw_ingestions` row (`payload` shown expanded; it's stored as a single JSONB value):

```json
{
  "id": 42,
  "source": "weather",
  "ingested_at": "2026-08-06T11:55:36.999+00:00",
  "format": "records",
  "payload": [
    { "index": "2026-08-06T10:00:00+01:00", "temperature_2m": 15.6, "wind_speed_10m": 8.6, "location": "Dublin" },
    { "index": "2026-08-06T11:00:00+01:00", "temperature_2m": 16.1, "wind_speed_10m": 9.2, "location": "Dublin" }
  ]
}
```

## CI/CD pipeline

From `.github/workflows/ci.yml`. Every push and PR gets linted and tested across both Python versions; only branches actually headed to production get packaged. Postgres runs as a GitHub Actions **service container** - ephemeral, one per job run, on the runner's default port (no local-port-collision workaround needed there, unlike `docker-compose.yml`).

```mermaid
flowchart TD
    TRIGGER["push or pull_request<br/>main, develop, feature/**, release/**, hotfix/**"] --> SVC

    subgraph matrix["Lint and Test — matrix: Python 3.10, 3.11"]
        direction LR
        SVC["Start service container<br/>postgres:16-alpine<br/>(health-checked before job proceeds)"] --> M1["Checkout"] --> M2["Set up Python"] --> M3["pip install -r requirements.txt<br/>pip install pytest ruff"] --> M4["ruff check src tests"] --> M5["pytest tests/ -v<br/>(hits the service container)"]
    end

    M5 --> GATE{"branch is<br/>main / release/* / hotfix/*?"}
    GATE -- yes --> PKG["Package artifact<br/>tar czf dist/energy-data-pipeline.tar.gz<br/>src requirements.txt"]
    GATE -- no --> SKIP["Package job skipped"]
    PKG --> UPLOAD["Upload artifact<br/>(GitHub Actions artifact store)"]
```

A second, independent workflow, `.github/workflows/scheduled-run.yml`, is what actually runs the pipeline in production - `ci.yml` above only lints, tests, and packages. It fires on a cron schedule (or a manual `workflow_dispatch`) and runs `python src/orchestrate.py` live against a managed Postgres, authenticated via repo secrets rather than the service-container credentials `ci.yml` uses. See the README's "Production Deployment" section for setup.

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
