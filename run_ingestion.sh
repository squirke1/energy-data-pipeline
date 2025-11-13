#!/bin/bash
# Set your ENTSO-E API key here
export ENTSOE_API_KEY="your_key_here"

# Run the ingestion
python src/ingest_entsoe.py
