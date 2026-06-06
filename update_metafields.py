import os
import requests
import pandas as pd
import time
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

CSV_FILE = "Metafiled_Update.csv"


# ─────────────────────────────────────────────────────────
# STEP 1 — GET ACCESS TOKEN
# ─────────────────────────────────────────────────────────
def get_access_token():
    url  = f"https://{STORE_URL}/admin/oauth/access_token"
    resp = requests.post(url, json={
        "grant_type":    "client_credentials",
        "client_id":     CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    })
    if resp.status_code == 200:
        print("✅ Access token received")
        return resp.json()["access_token"]
    print(f"❌ Token error {resp.status_code}: {resp.text}")
    return None


# ─────────────────────────────────────────────────────────
# STEP 2 — FETCH ALL PRODUCTS (cached once)
# ─────────────────────────────────────────────────────────
def fetch_all_products(headers):
    products = []
    url      = f"https://{STORE_URL}/admin/api/2025-01/products.json?limit=250"

    print("📦 Fetching products from store", end="", flush=True)
    while url:
        resp = requests.get(url, headers=headers)
        if resp.status_code != 200:
            print(f"\n❌ Error: {resp.status_code} {resp.text}")
            break
        products.extend(resp.json().get("products", []))
        print(".", end="", flush=True)

        # Pagination
        link = resp.headers.get("Link", "")
        url  = None
        if 'rel="next"' in link:
            for part in link.split(","):
                if 'rel="next"' in part:
                    url = part.strip().split(";")[0].strip("<> ")
        time.sleep(0.3)

    print(f"\n✅ {len(products)} products loaded\n")
    return products


# ─────────────────────────────────────────────────────────
# STEP 3 — FIND PRODUCT by Handle → SKU fallback
# ─────────────────────────────────────────────────────────
def find_product(products_cache, handle, sku):
    """
    Match priority:
      1. Handle (exact match) — fastest
      2. Variant SKU (fallback) — if handle not found
    """
    # Try Handle first
    if handle:
        for p in products_cache:
            if p.get("handle", "").strip() == handle.strip():
                return p["id"], p.get("title", "")

    # Fallback to SKU
    if sku:
        for p in products_cache:
            for v in p.get("variants", []):
                if str(v.get("sku", "")).strip() == sku.strip():
                    return p["id"], p.get("title", "")

    return None, None


# ─────────────────────────────────────────────────────────
# STEP 4 — CHECK IF METAFIELD ALREADY EXISTS
# ─────────────────────────────────────────────────────────
def get_existing_metafield_id(headers, product_id, namespace, key):
    """Returns metafield ID if it exists, else None."""
    url  = f"https://{STORE_URL}/admin/api/2025-01/products/{product_id}/metafields.json"
    resp = requests.get(url, headers=headers)
    if resp.status_code == 200:
        for mf in resp.json().get("metafields", []):
            if mf["namespace"] == namespace and mf["key"] == key:
                return mf["id"]
    return None


# ─────────────────────────────────────────────────────────
# STEP 4b — FORMAT VALUE FOR METAFIELD TYPE
# ─────────────────────────────────────────────────────────
def format_value(mf_type, value):
    """Convert plain text/HTML to the format Shopify expects per type."""
    import json, re

    text = str(value).strip()

    if mf_type == "rich_text_field":
        # Strip HTML tags to get plain text, then wrap in Shopify rich text JSON
        plain = re.sub(r"<[^>]+>", "", text).strip()
        rich  = {
            "type": "root",
            "children": [
                {
                    "type": "paragraph",
                    "children": [{"type": "text", "value": plain}]
                }
            ]
        }
        return json.dumps(rich)

    if mf_type in ("number_integer",):
        return str(int(float(text)))

    if mf_type in ("number_decimal",):
        return str(float(text))

    if mf_type == "boolean":
        return "true" if text.lower() in ("true", "1", "yes") else "false"

    return text   # single_line_text_field, multi_line_text_field, etc.


# ─────────────────────────────────────────────────────────
# STEP 5 — CREATE OR UPDATE METAFIELD
# ─────────────────────────────────────────────────────────
def upsert_metafield(headers, product_id, namespace, key, mf_type, value):
    """
    Checks if metafield exists:
      → EXISTS : PUT  to update
      → MISSING: POST to create
    """
    existing_id = get_existing_metafield_id(headers, product_id, namespace, key)

    payload = {
        "metafield": {
            "namespace": namespace,
            "key":       key,
            "value":     format_value(mf_type, value),
            "type":      mf_type,
        }
    }

    if existing_id:
        # UPDATE
        url  = f"https://{STORE_URL}/admin/api/2025-01/metafields/{existing_id}.json"
        resp = requests.put(url, headers=headers, json=payload)
        if resp.status_code == 200:
            return "updated", None
        return "failed", resp.text[:200]
    else:
        # CREATE
        url  = f"https://{STORE_URL}/admin/api/2025-01/products/{product_id}/metafields.json"
        resp = requests.post(url, headers=headers, json=payload)
        if resp.status_code == 201:
            return "created", None
        return "failed", resp.text[:200]


# ─────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────
def run_update():
    print("=" * 60)
    print("   SPARQ DIAMONDS — METAFIELDS UPDATE")
    print("=" * 60)

    # Auth
    token = get_access_token()
    if not token:
        return

    headers = {
        "X-Shopify-Access-Token": token,
        "Content-Type":           "application/json"
    }

    # Load CSV
    try:
        df = pd.read_csv(CSV_FILE)
        print(f"📄 CSV loaded → {len(df)} rows\n")
    except FileNotFoundError:
        print(f"❌ File not found: {CSV_FILE}")
        return

    # Validate columns
    required = [
        "Handle", "Variant SKU",
        "Metafield namespace", "Metafield Key",
        "Metafield type", "Metafield Value"
    ]
    missing = [c for c in required if c not in df.columns]
    if missing:
        print(f"❌ Missing columns in CSV: {missing}")
        return
    print(f"✅ All required columns found\n")

    # Cache products once (avoids repeated API calls)
    products_cache = fetch_all_products(headers)

    # Counters
    updated  = 0
    created  = 0
    failed   = 0
    notfound = 0
    skipped  = 0
    total    = len(df)

    print("🚀 Starting update...\n")
    print("-" * 60)

    for i, row in df.iterrows():
        handle    = str(row.get("Handle",             "")).strip()
        sku       = str(row.get("Variant SKU",        "")).strip()
        namespace = str(row.get("Metafield namespace","")).strip()
        key       = str(row.get("Metafield Key",      "")).strip()
        mf_type   = str(row.get("Metafield type",     "")).strip()
        value     = row.get("Metafield Value", "")

        print(f"[{i+1}/{total}] SKU       : {sku}")
        print(f"        Handle    : {handle[:60]}")
        print(f"        Metafield : {namespace}.{key} ({mf_type})")
        print(f"        Value     : {str(value)[:60]}")

        # Skip empty values
        if pd.isna(value) or str(value).strip() == "":
            print(f"  ⏭️  SKIPPED — value is empty\n")
            skipped += 1
            continue

        # Find product
        product_id, title = find_product(products_cache, handle, sku)

        if not product_id:
            print(f"  ❌ NOT FOUND — check Handle or SKU\n")
            notfound += 1
            continue

        print(f"  🎯 Product  : {title[:55]} (ID: {product_id})")

        # Create or update metafield
        action, err = upsert_metafield(
            headers, product_id, namespace, key, mf_type, value
        )

        if action == "updated":
            print(f"  🔄 UPDATED  : {namespace}.{key} = {str(value)[:50]}")
            updated += 1
        elif action == "created":
            print(f"  ✨ CREATED  : {namespace}.{key} = {str(value)[:50]}")
            created += 1
        else:
            print(f"  ❌ FAILED   : {err}")
            failed += 1

        print()
        time.sleep(0.4)   # Avoid Shopify rate limits (40 req/sec)

    # ── Final Summary ─────────────────────────────────────
    print("=" * 60)
    print("   UPDATE COMPLETE — SUMMARY")
    print("=" * 60)
    print(f"  🔄 Updated           : {updated}")
    print(f"  ✨ Created           : {created}")
    print(f"  ❌ Failed            : {failed}")
    print(f"  🔍 Products not found: {notfound}")
    print(f"  ⏭️  Skipped           : {skipped}")
    print(f"  📦 Total rows        : {total}")
    print("=" * 60)


if __name__ == "__main__":
    run_update()