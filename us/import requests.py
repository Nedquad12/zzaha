import requests
from config import MASSIVE_API_KEY, MASSIVE_BASE_URL
import pandas as pd

ticker = "AAPL"
url = f"{MASSIVE_BASE_URL}/aggs/ticker/{ticker}/range/1/day/2025-01-01/2026-03-13"
r = requests.get(url, params={"adjusted": "true", "sort": "asc", "limit": 50000, "apiKey": MASSIVE_API_KEY})
results = r.json()["results"]
dates = [pd.to_datetime(x["t"], unit="ms").date() for x in results[-3:]]
print("Total candle:", len(results))
print("3 terakhir:", dates)