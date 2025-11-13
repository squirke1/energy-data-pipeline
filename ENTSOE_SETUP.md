# ENTSO-E API Setup Guide

## Step 1: Register and Get API Key

1. Go to https://transparency.entsoe.eu/
2. Click "Login" in top right corner
3. Click "Register" to create a new account
4. Fill in your details and verify your email
5. Once logged in, click your username → "Account Settings"
6. Look for "Web API Security Token" section
7. Click "Generate a new token"
8. Copy your token (long alphanumeric string)

## Step 2: Configure Your Pipeline

Create a `.env` file in the project root:

```bash
# Copy the example file
cp .env.example .env

# Edit .env and add your token
ENTSOE_API_KEY=your_token_goes_here
```

## Step 3: Test the Connection

Run this command to test your API key:

```bash
python src/ingest_entsoe.py
```

This will:
- Fetch the last 24 hours of Irish electricity generation data
- Save it to `data/raw/entsoe_generation_TIMESTAMP.csv`
- Show generation by fuel type (Gas, Wind, Hydro, etc.)

## Available Data

With ENTSO-E API you can get:
- Generation by fuel type (actual and forecasted)
- Load (demand) data
- Cross-border flows
- Prices (day-ahead, intraday)
- Available capacity
- Outages

## Supported Countries

The API key works for all European countries:
- IE (Ireland)
- GB (Great Britain)
- DE (Germany)
- FR (France)
- And 30+ more European zones

## Troubleshooting

If you get authentication errors:
1. Make sure your token is correctly copied to `.env`
2. Check there are no extra spaces or quotes
3. Verify your account email is confirmed
4. Try generating a new token if needed

## Data Frequency

Generation data is available in:
- 15-minute intervals (for most zones)
- Hourly aggregates
- Daily summaries
