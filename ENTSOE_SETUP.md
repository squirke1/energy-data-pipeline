# ENTSO-E API Setup Guide

## Step 1: Register and Get API Key

### If you DON'T have an account yet:

1. Go to https://transparency.entsoe.eu/
2. Click "Login" in top right corner
3. Click "Register" below the login form
4. Fill in your details:
   - First Name, Last Name
   - Email address
   - Company/Organization (can be "Personal" or "Student")
   - Country
5. Accept terms and submit
6. **IMPORTANT:** Check your email and click the verification link
7. After email verification, log in to the platform

### If you already have an account:

1. Go to https://transparency.entsoe.eu/
2. Click "Login" and enter your credentials
3. **Check your email** - you should have received a verification email when you registered
4. Click the verification link in that email if you haven't already
5. After verification, the "Web API Security Token" option should appear

### Getting the Token:

1. Once logged in and verified, click your email/username in top right
2. Select "Web API" from the dropdown menu (NOT "Account Settings")
3. You should see "Generate a new security token" button
4. Click it and copy your token (long alphanumeric string)
5. Keep this token safe - you'll need it for the pipeline

**Note:** The token section only appears after email verification is complete!

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
