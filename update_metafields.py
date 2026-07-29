import os
import requests
import pandas as pd
import json
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
# AUTH
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
# FETCH ALL PRODUCTS + VARIANTS (cached once)
# ─────────────────────────────────────────────────────────
def fetch_all_products(headers):
    products = []
    url      = f"https://{STORE_URL}/admin/api/2025-01/products.json?limit=250"
    print("📦 Fetching products", end="", flush=True)
    while url:
        resp = requests.get(url, headers=headers)
        if resp.status_code != 200:
            print(f"\n❌ {resp.status_code}: {resp.text}")
            break
        products.extend(resp.json().get("products", []))
        print(".", end="", flush=True)
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
# FIND HELPERS
# ─────────────────────────────────────────────────────────
def find_variant_by_sku(products_cache, sku):
    """Returns (product_id, variant_id, title) matched by SKU."""
    for product in products_cache:
        for variant in product.get("variants", []):
            if str(variant.get("sku", "")).strip() == sku.strip():
                return product["id"], variant["id"], product.get("title", "")
    return None, None, None


def find_product_by_handle(products_cache, handle):
    """Returns (product_id, title) matched by handle."""
    for product in products_cache:
        if product.get("handle", "").strip() == handle.strip():
            return product["id"], product.get("title", "")
    return None, None


# ─────────────────────────────────────────────────────────
# VALUE FORMATTER
# Converts plain CSV value → correct format for any type
# ─────────────────────────────────────────────────────────
def format_value(value, mf_type):
    """
    Handles ALL Shopify metafield types automatically.
    Reads raw value from CSV and returns correctly formatted string.
    """
    raw = str(value).strip()

    # ── Text types (plain string) ──────────────────────
    if mf_type in (
        "single_line_text_field",
        "multi_line_text_field",
        "url",
        "color",
        "date",
        "date_time",
    ):
        return raw

    # ── Number types ──────────────────────────────────
    if mf_type == "number_integer":
        try:    return str(int(float(raw)))
        except: return raw

    if mf_type == "number_decimal":
        try:    return str(float(raw))
        except: return raw

    # ── Boolean ───────────────────────────────────────
    if mf_type == "boolean":
        return "true" if raw.lower() in ("true", "1", "yes") else "false"

    # ── rich_text_field ───────────────────────────────
    # Requires Shopify's JSON structure — auto-wrap plain text
    if mf_type == "rich_text_field":
        # Already valid Shopify JSON? return as-is
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict) and parsed.get("type") == "root":
                return raw
        except (json.JSONDecodeError, TypeError):
            pass

        # Convert plain text → rich_text JSON
        return json.dumps({
            "type": "root",
            "children": [{
                "type": "paragraph",
                "children": [{"type": "text", "value": raw}]
            }]
        })

    # ── JSON type (any raw JSON) ───────────────────────
    if mf_type == "json":
        try:
            json.loads(raw)   # validate it's valid JSON
            return raw
        except json.JSONDecodeError:
            # Wrap as JSON string if not valid JSON
            return json.dumps(raw)

    # ── List types (e.g. list.single_line_text_field) ─
    if mf_type.startswith("list."):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return raw        # already a JSON array
        except (json.JSONDecodeError, TypeError):
            pass
        # Comma-separated → JSON array
        items = [item.strip() for item in raw.split(",")]
        return json.dumps(items)

    # ── Measurement types (weight, volume, dimension) ─
    # Expected CSV value: "100 kg" or "100" (unit assumed)
    if mf_type in ("weight", "volume", "dimension"):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return raw        # already {"value":...,"unit":...}
        except (json.JSONDecodeError, TypeError):
            pass
        parts = raw.split()
        unit_map = {
            "weight":    "kg",
            "volume":    "ml",
            "dimension": "cm",
        }
        return json.dumps({
            "value": float(parts[0]),
            "unit":  parts[1] if len(parts) > 1 else unit_map[mf_type]
        })

    # ── Rating ────────────────────────────────────────
    # Expected CSV value: "4.5" or JSON {"value":4.5,"scale_min":1,"scale_max":5}
    if mf_type == "rating":
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return raw
        except (json.JSONDecodeError, TypeError):
            pass
        return json.dumps({"value": float(raw), "scale_min": 1, "scale_max": 5})

    # ── Money ─────────────────────────────────────────
    # Expected CSV value: "999.00" or JSON {"amount":"999.00","currency_code":"INR"}
    if mf_type == "money":
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return raw
        except (json.JSONDecodeError, TypeError):
            pass
        return json.dumps({"amount": raw, "currency_code": "INR"})

    # ── Reference types (product_reference etc.) ──────
    # Expected: GID like "gid://shopify/Product/123456"
    if "reference" in mf_type:
        return raw

    # ── Fallback: return as plain string ──────────────
    return raw


# ─────────────────────────────────────────────────────────
# GET EXISTING METAFIELD ID
# ─────────────────────────────────────────────────────────
def get_existing_metafield_id(headers, owner_type, owner_id, namespace, key):
    url  = f"https://{STORE_URL}/admin/api/2025-01/{owner_type}/{owner_id}/metafields.json"
    resp = requests.get(url, headers=headers)
    if resp.status_code == 200:
        for mf in resp.json().get("metafields", []):
            if mf["namespace"] == namespace and mf["key"] == key:
                return mf["id"]
    return None


def get_existing_metafield(headers, owner_type, owner_id, namespace, key):
    url  = f"https://{STORE_URL}/admin/api/2025-01/{owner_type}/{owner_id}/metafields.json"
    resp = requests.get(url, headers=headers)
    if resp.status_code == 200:
        for mf in resp.json().get("metafields", []):
            if mf["namespace"] == namespace and mf["key"] == key:
                return mf
    return None


# ─────────────────────────────────────────────────────────
# UPSERT METAFIELD — PUT if exists, POST if new
# ─────────────────────────────────────────────────────────
def upsert_metafield(headers, owner_type, owner_id, namespace, key, mf_type, raw_value):
    formatted_value = format_value(raw_value, mf_type)
    existing_id     = get_existing_metafield_id(
        headers, owner_type, owner_id, namespace, key
    )

    payload = {
        "metafield": {
            "namespace": namespace,
            "key":       key,
            "value":     formatted_value,
            "type":      mf_type,
        }
    }

    if existing_id:
        url  = f"https://{STORE_URL}/admin/api/2025-01/metafields/{existing_id}.json"
        resp = requests.put(url, headers=headers, json=payload)
        if resp.status_code == 200:
            return "updated", formatted_value
        return "failed", resp.text[:200]
    else:
        url  = f"https://{STORE_URL}/admin/api/2025-01/{owner_type}/{owner_id}/metafields.json"
        resp = requests.post(url, headers=headers, json=payload)
        if resp.status_code == 201:
            return "created", formatted_value
        return "failed", resp.text[:200]


def verify_metafield(headers, owner_type, owner_id, namespace, key, expected_value):
    mf = get_existing_metafield(headers, owner_type, owner_id, namespace, key)
    if not mf:
        return False, "not found after save"

    saved_value = str(mf.get("value", ""))
    if saved_value == str(expected_value):
        return True, saved_value

    return False, saved_value[:200]


# ─────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────
def run_update():
    print("=" * 60)
    print("   SHOPIFY BULK EDITOR — METAFIELDS UPDATE")
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
        df = pd.read_csv(CSV_FILE, encoding="utf-8-sig")
        df = df.loc[:, ~df.columns.str.startswith("Unnamed")]
        print(f"📄 CSV loaded → {len(df)} rows\n")
    except FileNotFoundError:
        print(f"❌ File not found: {CSV_FILE}")
        return

    # Validate required columns
    required = ["Handle", "Variant SKU", "Metafield namespace",
                "Metafield Key", "Metafield type", "Metafield Value"]
    missing  = [c for c in required if c not in df.columns]
    if missing:
        print(f"❌ Missing columns in CSV: {missing}")
        return
    print(f"✅ Columns OK\n")

    # Show what will be updated
    print("📋 Metafields to process:")
    summary = df.groupby(["Metafield namespace", "Metafield Key", "Metafield type"]).size()
    for (ns, key, mf_type), count in summary.items():
        print(f"   → {ns}.{key} ({mf_type}) — {count} rows")
    print()

    # Cache all products once
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
        owner_col = str(row.get("Owner",              "")).strip().lower()
        value     = row.get("Metafield Value", "")

        print(f"[{i+1}/{total}] SKU       : {sku}")
        print(f"        Handle    : {handle[:55]}")
        print(f"        Owner     : {owner_col or 'auto'}")
        print(f"        Field     : {namespace}.{key} ({mf_type})")
        print(f"        Value     : {str(value)[:60]}")

        # Skip empty values
        if pd.isna(value) or str(value).strip() in ("", "nan"):
            print(f"  ⏭️  SKIPPED — empty value\n")
            skipped += 1
            continue

        # ── FIND OWNER ────────────────────────────────────
        # Owner column controls level explicitly:
        #   Owner=variant  → variants/{variant_id}
        #   Owner=product  → products/{product_id}
        #   Owner missing  → SKU present=variant, else product
        # ──────────────────────────────────────────────────
        owner_type = None
        owner_id   = None
        title      = ""

        sku_clean    = sku.lower() not in ("nan", "none", "")
        handle_clean = handle.lower() not in ("nan", "none", "")

        wants_product = owner_col in ("product", "products")

        if sku_clean:
            product_id, variant_id, title = find_variant_by_sku(products_cache, sku)
            if wants_product and product_id:
                owner_type = "products"
                owner_id   = product_id
                print(f"  📦 PRODUCT level (via SKU) → {title[:45]}")
            elif variant_id and not wants_product:
                owner_type = "variants"
                owner_id   = variant_id
                print(f"  🔩 VARIANT level → {title[:45]}")
            elif product_id:
                owner_type = "products"
                owner_id   = product_id
                print(f"  📦 PRODUCT level (fallback) → {title[:45]}")
        elif handle_clean:
            product_id, title = find_product_by_handle(products_cache, handle)
            if product_id:
                owner_type = "products"
                owner_id   = product_id
                print(f"  📦 PRODUCT level → {title[:45]}")

        if not owner_id:
            print(f"  ❌ NOT FOUND — check Handle or SKU\n")
            notfound += 1
            continue

        # ── UPSERT ───────────────────────────────────────
        action, result = upsert_metafield(
            headers, owner_type, owner_id,
            namespace, key, mf_type, value
        )

        if action == "updated":
            print(f"  🔄 UPDATED  → {namespace}.{key}")
            updated += 1
        elif action == "created":
            print(f"  ✨ CREATED  → {namespace}.{key}")
            created += 1
        else:
            print(f"  ❌ FAILED   → {result}")
            failed += 1

        if action in ("updated", "created"):
            ok, saved = verify_metafield(
                headers, owner_type, owner_id, namespace, key, result
            )
            if ok:
                print("  VERIFIED -> saved value matches Shopify")
            else:
                print(f"  WARNING  -> read-back mismatch: {saved}")

        print()
        time.sleep(0.4)

    # Summary
    print("=" * 60)
    print("   UPDATE COMPLETE — SUMMARY")
    print("=" * 60)
    print(f"  🔄 Updated             : {updated}")
    print(f"  ✨ Created             : {created}")
    print(f"  ❌ Failed              : {failed}")
    print(f"  🔍 Not found           : {notfound}")
    print(f"  ⏭️  Skipped             : {skipped}")
    print(f"  📦 Total rows          : {total}")
    print("=" * 60)


if __name__ == "__main__":
    run_update()
