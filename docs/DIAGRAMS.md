# Architecture & Data Flow

Reference diagrams for `energy-data-pipeline`. These render natively on GitHub (no plugins needed) since they're standard Mermaid fenced code blocks.

## System architecture

Three independently-authenticated sources feed the same shared validate → transform → load machinery, coordinated by `orchestrate.py`. Weather takes a lighter path since it isn't generation data — it doesn't have a `fuel_type`/`is_renewable` shape to validate or transform, so it goes straight to storage plus the shared run-log.

```mermaid
flowchart TD
    subgraph ext["External sources"]
        ENTSOE["ENTSO-E Transparency Platform<br/><i>token auth, 30+ EU zones</i>"]
        EIRGRID["EirGrid Smart Grid Dashboard<br/><i>no auth, legacy, IE only</i>"]
        METEO["Open-Meteo<br/><i>no auth, no signup</i>"]
    end

    subgraph ingest["Ingestion — src/ingest_*.py"]
        I_ENTSOE["ingest_entsoe.py"]
        I_EIRGRID["ingest_eirgrid.py"]
        I_WEATHER["ingest_weather.py"]
    end

    ENTSOE --> I_ENTSOE
    EIRGRID --> I_EIRGRID
    METEO --> I_WEATHER

    I_ENTSOE --> RAW[("data/raw/*.csv, *.json")]
    I_EIRGRID --> RAW
    I_WEATHER --> RAW

    I_ENTSOE --> VALIDATE["validate.py<br/>validate_generation_df()"]
    I_EIRGRID --> VALIDATE2["validate.py<br/>validate_eirgrid_response()"]

    VALIDATE --> TRANSFORM["transform_energy.py<br/>melt, flag renewables,<br/>compute carbon intensity"]
    VALIDATE2 --> TRANSFORM

    TRANSFORM --> LOAD["load_db.py<br/>load_generation_fact()<br/>load_generation_summary()"]
    I_WEATHER --> SAVE["save_weather_data()"]

    LOAD --> DB[("data/energy.db — SQLite")]
    SAVE --> RUNLOG["log_pipeline_run()"]
    LOAD --> RUNLOG
    RUNLOG --> DB

    ORCH["orchestrate.py"]:::orch -.controls.-> I_ENTSOE
    ORCH -.controls.-> I_EIRGRID
    ORCH -.controls.-> I_WEATHER
    ORCH -.controls.-> VALIDATE
    ORCH -.controls.-> TRANSFORM
    ORCH -.controls.-> LOAD

    classDef orch fill:#5b8def,color:#fff,stroke:#3a6bc7
```

## Data flow (swimlanes by source)

Each source is its own lane through `orchestrate.py`. ENTSO-E and EirGrid both earn their way into `generation_fact`/`generation_summary` through the same validate → transform → load sequence and can fail at the validate step; weather has no generation shape to validate or transform against, so its lane is shorter by design, not by omission. All three converge on the same `log_pipeline_run()` call, so every run - success or failure, any source - lands in one queryable place.

```mermaid
flowchart TB
    subgraph L1["ENTSO-E lane"]
        direction LR
        A1["Fetch<br/>(live or --mock)"] --> A2{"Validate<br/>validate_generation_df()"}
        A2 -- passed --> A3["Transform<br/>melt, flag renewable,<br/>carbon intensity"]
        A3 --> A4["Load<br/>generation_fact +<br/>generation_summary"]
        A2 -- failed --> A5["raise ValueError"]
    end

    subgraph L2["EirGrid lane"]
        direction LR
        B1["Fetch<br/>(live or --mock)"] --> B2{"Validate<br/>validate_eirgrid_response()"}
        B2 -- passed --> B3["Transform<br/>melt, flag renewable,<br/>carbon intensity"]
        B3 --> B4["Load<br/>generation_fact +<br/>generation_summary"]
        B2 -- failed --> B5["raise ValueError"]
    end

    subgraph L3["Weather lane"]
        direction LR
        C1["Fetch<br/>(live or --mock)"] --> C2["Save raw CSV/JSON<br/>to data/raw/"]
    end

    A4 --> LOG["log_pipeline_run(source, status)"]
    A5 --> LOG
    B4 --> LOG
    B5 --> LOG
    C2 --> LOG
    LOG --> DB[("data/energy.db")]
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
