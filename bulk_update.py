import os
import json
import requests
import pandas as pd
import time
import re
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

CSV_FILE   = "Metafield_updates.csv"
BATCH_SIZE = 25   # metafieldsSet limit per call
API_VER    = "2025-01"
GQL_URL    = f"https://{STORE_URL}/admin/api/{API_VER}/graphql.json"

METAFIELDS_SET_MUTATION = """
mutation MetafieldsSet($metafields: [MetafieldsSetInput!]!) {
  metafieldsSet(metafields: $metafields) {
    metafields { id key namespace }
    userErrors { field message elementIndex }
  }
}
"""


# ─────────────────────────────────────────────────────────
# AUTH
# ─────────────────────────────────────────────────────────
def get_access_token():
    resp = requests.post(
        f"https://{STORE_URL}/admin/oauth/access_token",
        json={"grant_type": "client_credentials",
              "client_id": CLIENT_ID,
              "client_secret": CLIENT_SECRET},
        timeout=30
    )
    if resp.status_code == 200:
        print("✅ Access token received")
        return resp.json()["access_token"]
    print(f"❌ Auth failed {resp.status_code}: {resp.text}")
    return None


# ─────────────────────────────────────────────────────────
# FETCH ALL PRODUCTS
# ─────────────────────────────────────────────────────────
def fetch_all_products(headers):
    products = []
    url = f"https://{STORE_URL}/admin/api/{API_VER}/products.json?limit=250"
    print("📦 Fetching products", end="", flush=True)
    while url:
        resp = requests.get(url, headers=headers, timeout=60)
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
# VALUE FORMATTER
# ─────────────────────────────────────────────────────────
def format_value(value, mf_type):
    raw = str(value).strip().lstrip("'")
    try:
        if mf_type == "number_integer":
            return str(int(float(raw)))
        if mf_type == "number_decimal":
            return str(float(raw))
        if mf_type == "boolean":
            return "true" if raw.lower() in ("true", "1", "yes") else "false"
        if mf_type == "rich_text_field":
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict) and parsed.get("type") == "root":
                    return raw
            except (json.JSONDecodeError, ValueError):
                pass
            plain = re.sub(r"<[^>]+>", "", raw).strip()
            return json.dumps({
                "type": "root",
                "children": [{"type": "paragraph",
                               "children": [{"type": "text", "value": plain}]}]
            })
        if mf_type == "json":
            try:
                json.loads(raw)
                return raw
            except json.JSONDecodeError:
                return json.dumps(raw)
    except (ValueError, TypeError):
        pass
    return raw


# ─────────────────────────────────────────────────────────
# SEND ONE BATCH  (retry on throttle/429)
# ─────────────────────────────────────────────────────────
def send_batch(headers, batch, batch_num, total_batches):
    for attempt in range(4):
        resp = requests.post(
            GQL_URL,
            headers=headers,
            json={"query": METAFIELDS_SET_MUTATION,
                  "variables": {"metafields": batch}},
            timeout=60
        )

        if resp.status_code == 429:
            print(f"  ⏳ HTTP 429 rate limit — waiting 3s (attempt {attempt+1})")
            time.sleep(3)
            continue

        if resp.status_code != 200:
            print(f"  ❌ HTTP {resp.status_code}: {resp.text[:120]}")
            return 0, len(batch)

        data   = resp.json()
        errors = data.get("errors", [])

        if errors and any(e.get("extensions", {}).get("code") == "THROTTLED"
                          for e in errors):
            retry_after = float(errors[0].get("extensions", {}).get("retryAfter", 2))
            print(f"  ⏳ Throttled — waiting {retry_after:.1f}s")
            time.sleep(retry_after + 0.5)
            continue

        result      = (data.get("data") or {}).get("metafieldsSet") or {}
        set_ok      = result.get("metafields", [])
        user_errors = result.get("userErrors", [])

        if user_errors:
            for ue in user_errors:
                print(f"  ❌ [{ue.get('elementIndex','')}] "
                      f"{ue.get('field','')}: {ue['message']}")
        print(f"  ✅ Batch {batch_num}/{total_batches} — "
              f"{len(set_ok)} set, {len(user_errors)} errors")
        return len(set_ok), len(user_errors)

    return 0, len(batch)


# ─────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────
def run_bulk_update():
    print("=" * 60)
    print("   SPARQ DIAMONDS — BULK METAFIELDS UPDATE (GraphQL)")
    print("=" * 60)

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

    required = ["Handle", "Variant SKU", "Metafield namespace",
                "Metafield Key", "Metafield type", "Metafield Value"]
    missing  = [c for c in required if c not in df.columns]
    if missing:
        print(f"❌ Missing columns: {missing}")
        return

    # Fetch products for SKU/handle lookup
    products_cache = fetch_all_products(headers)

    # Build metafield input list
    print("🔍 Resolving owners for each row...")
    metafield_inputs = []
    skipped  = 0
    notfound = 0

    for _, row in df.iterrows():
        handle    = str(row.get("Handle",             "")).strip()
        sku       = str(row.get("Variant SKU",        "")).strip()
        namespace = str(row.get("Metafield namespace","")).strip()
        key       = str(row.get("Metafield Key",      "")).strip()
        mf_type   = str(row.get("Metafield type",     "")).strip()
        owner_col = str(row.get("Owner",              "")).strip().lower()
        value     = row.get("Metafield Value", "")

        if pd.isna(value) or str(value).strip() in ("", "nan"):
            skipped += 1
            continue

        sku_clean    = sku.lower()    not in ("", "nan", "none")
        handle_clean = handle.lower() not in ("", "nan", "none")
        wants_product = owner_col in ("product", "products")

        owner_gid = None
        if sku_clean:
            for p in products_cache:
                for v in p.get("variants", []):
                    if str(v.get("sku", "")).strip() == sku:
                        if wants_product:
                            owner_gid = f"gid://shopify/Product/{p['id']}"
                        else:
                            owner_gid = f"gid://shopify/ProductVariant/{v['id']}"
                        break
                if owner_gid:
                    break

        if not owner_gid and handle_clean:
            for p in products_cache:
                if p.get("handle", "").strip() == handle:
                    owner_gid = f"gid://shopify/Product/{p['id']}"
                    break

        if not owner_gid:
            notfound += 1
            continue

        metafield_inputs.append({
            "ownerId":   owner_gid,
            "namespace": namespace,
            "key":       key,
            "type":      mf_type,
            "value":     format_value(value, mf_type),
        })

    total_inputs  = len(metafield_inputs)
    total_batches = (total_inputs + BATCH_SIZE - 1) // BATCH_SIZE
    print(f"✅ {total_inputs} metafield inputs ready")
    print(f"⏭️  {skipped} skipped (empty values)")
    print(f"❌ {notfound} not found (check SKU/handle)")
    print(f"📦 {total_batches} batches of {BATCH_SIZE}\n")

    est_sec = total_batches * 1.2
    print(f"⏱️  Estimated time: ~{round(est_sec/60, 1)} min\n")
    print("─" * 60)

    # Send batches
    success_total = 0
    error_total   = 0

    for batch_i in range(total_batches):
        batch  = metafield_inputs[batch_i * BATCH_SIZE : (batch_i + 1) * BATCH_SIZE]
        ok, er = send_batch(headers, batch, batch_i + 1, total_batches)
        success_total += ok
        error_total   += er
        time.sleep(0.5)  # stay safely under GraphQL rate limit

    # Summary
    print("=" * 60)
    print("   BULK UPDATE COMPLETE — SUMMARY")
    print("=" * 60)
    print(f"  ✅ Metafields set    : {success_total}")
    print(f"  ❌ Errors            : {error_total}")
    print(f"  ⏭️  Skipped           : {skipped}")
    print(f"  🔍 Not found         : {notfound}")
    print(f"  📦 Total rows in CSV : {len(df)}")
    print("=" * 60)


if __name__ == "__main__":
    run_bulk_update()
