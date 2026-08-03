#!/bin/bash
# Loads ENTSOE_API_KEY from .env (see .env.example / ENTSOE_SETUP.md)
set -a
source .env
set +a

# Run the ingestion
python src/ingest_entsoe.py
