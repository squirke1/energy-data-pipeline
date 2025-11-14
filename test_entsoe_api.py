#!/usr/bin/env python
"""
Quick test script to verify ENTSO-E API connection
"""
import os
from dotenv import load_dotenv
from entsoe.entsoe import EntsoePandasClient
import pandas as pd

load_dotenv()

def test_api_connection():
    api_key = os.getenv("ENTSOE_API_KEY")
    
    if not api_key:
        print("❌ ENTSOE_API_KEY not found in .env file")
        print("Please create a .env file with your API key")
        return False
    
    print(f"✓ API key found: {api_key[:10]}...")
    
    try:
        client = EntsoePandasClient(api_key=api_key)
        print("✓ Client created successfully")
        
        # Test with a small query (last hour)
        end = pd.Timestamp.now(tz='Europe/Dublin')
        start = end - pd.Timedelta(hours=1)
        
        print(f"\nTesting query for Ireland (IE)")
        print(f"From: {start}")
        print(f"To: {end}")
        
        df = client.query_generation(country_code='IE', start=start, end=end)
        
        print(f"\n✓ Successfully fetched data!")
        print(f"  Rows: {len(df)}")
        print(f"  Columns: {df.shape[1]}")
        print(f"\nGeneration types available:")
        for col in df.columns:
            print(f"  - {col}")
        
        print(f"\n✓ API connection working! You're ready to run the pipeline.")
        return True
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        print("\nTroubleshooting:")
        print("1. Check your API key is correct in .env")
        print("2. Verify your email is confirmed on ENTSO-E")
        print("3. Try generating a new token")
        return False

if __name__ == "__main__":
    test_api_connection()
