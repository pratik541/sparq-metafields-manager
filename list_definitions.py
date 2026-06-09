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
    resp = requests.post(f"https://{STORE_URL}/admin/oauth/access_token", json={
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    })
    return resp.json()["access_token"] if resp.status_code == 200 else None

QUERY = """
{
  metafieldDefinitions(first: 50, ownerType: PRODUCT) {
    edges { node { name namespace key type { name } } }
  }
}
"""

QUERY_VARIANT = """
{
  metafieldDefinitions(first: 50, ownerType: PRODUCTVARIANT) {
    edges { node { name namespace key type { name } } }
  }
}
"""

token = get_access_token()
headers = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}

print("=" * 55)
print("  PRODUCT metafield definitions")
print("=" * 55)
resp = requests.post(f"https://{STORE_URL}/admin/api/2025-01/graphql.json",
                     headers=headers, json={"query": QUERY})
for edge in resp.json()["data"]["metafieldDefinitions"]["edges"]:
    n = edge["node"]
    print(f"  Name      : {n['name']}")
    print(f"  namespace : {n['namespace']}")
    print(f"  key       : {n['key']}")
    print(f"  type      : {n['type']['name']}")
    print()

print("=" * 55)
print("  VARIANT metafield definitions")
print("=" * 55)
resp = requests.post(f"https://{STORE_URL}/admin/api/2025-01/graphql.json",
                     headers=headers, json={"query": QUERY_VARIANT})
for edge in resp.json()["data"]["metafieldDefinitions"]["edges"]:
    n = edge["node"]
    print(f"  Name      : {n['name']}")
    print(f"  namespace : {n['namespace']}")
    print(f"  key       : {n['key']}")
    print(f"  type      : {n['type']['name']}")
    print()
