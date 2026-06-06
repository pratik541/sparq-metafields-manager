import os
import requests
from pathlib import Path

_env_file = Path(__file__).parent / "config" / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        if _line.strip() and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

STORE_URL     = os.environ["SHOPIFY_STORE_URL"]
CLIENT_ID     = os.environ["SHOPIFY_CLIENT_ID"]
CLIENT_SECRET = os.environ["SHOPIFY_CLIENT_SECRET"]

def get_access_token():
    """Exchange client credentials for a fresh access token (valid 24h)."""
    url = f"https://{STORE_URL}/admin/oauth/access_token"
    payload = {
        "grant_type":    "client_credentials",
        "client_id":     CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }
    resp = requests.post(url, json=payload)
    if resp.status_code == 200:
        token = resp.json()["access_token"]
        print("✅ Got fresh access token")
        return token
    else:
        print(f"❌ Token fetch failed {resp.status_code}: {resp.text}")
        return None

# Get a fresh token
ACCESS_TOKEN = get_access_token()
if not ACCESS_TOKEN:
    exit(1)

headers = {
    "X-Shopify-Access-Token": ACCESS_TOKEN,
    "Content-Type": "application/json"
}

# Test — Fetch Products
url = f"https://{STORE_URL}/admin/api/2025-01/products.json?limit=5"
response = requests.get(url, headers=headers)

if response.status_code == 200:
    products = response.json()["products"]
    print(f"✅ Connected! Found {len(products)} products")
    for p in products:
        print(f"   → {p['id']} | {p['title']}")
else:
    print(f"❌ Error {response.status_code}: {response.text}")
