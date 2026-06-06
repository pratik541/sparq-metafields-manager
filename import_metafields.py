import os
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

CSV_FILE = "Metafiled_template.csv"

# ── Auto-detect metafield columns from CSV header ─────────
# Column format: "Label (product.metafields.namespace.key)"
METAFIELD_PATTERN = re.compile(r'product\.metafields\.([^.]+)\.(.+)\)')

# Metafield type mapping by namespace+key
METAFIELD_TYPES = {
    ("custom",  "happy_shoppers")      : "number_integer",
    ("custom",  "loved_by_customers")  : "number_integer",
    ("custom",  "product_rating")      : "number_decimal",
    ("custom",  "ribbon_text")         : "single_line_text_field",
    ("mm-google-shopping", "custom_product"): "boolean",
    ("shopify", "age-group")           : "single_line_text_field",
    ("shopify", "color-pattern")       : "single_line_text_field",
    ("shopify", "earring-design")      : "single_line_text_field",
    ("shopify", "jewelry-material")    : "single_line_text_field",
    ("shopify", "jewelry-type")        : "single_line_text_field",
    ("shopify", "target-gender")       : "single_line_text_field",
}


# ─────────────────────────────────────────────────────────
# 1. AUTH
# ─────────────────────────────────────────────────────────
def get_access_token():
    url = f"https://{STORE_URL}/admin/oauth/access_token"
    payload = {
        "grant_type":    "client_credentials",
        "client_id":     CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }
    resp = requests.post(url, json=payload)
    if resp.status_code == 200:
        print("✅ Access token received")
        return resp.json()["access_token"]
    print(f"❌ Token error {resp.status_code}: {resp.text}")
    return None


# ─────────────────────────────────────────────────────────
# 2. FIND PRODUCT BY SKU
# ─────────────────────────────────────────────────────────
def find_product_by_sku(headers, sku):
    """Search Shopify for a product that has this SKU on any variant."""
    url = f"https://{STORE_URL}/admin/api/2025-01/products.json?limit=250"
    resp = requests.get(url, headers=headers)
    if resp.status_code != 200:
        return None
    for product in resp.json().get("products", []):
        for variant in product.get("variants", []):
            if variant.get("sku") == sku:
                return product["id"]
    return None


# ─────────────────────────────────────────────────────────
# 3. CREATE PRODUCT
# ─────────────────────────────────────────────────────────
def create_product(headers, row, all_rows):
    """Create product with all images and variant details."""
    handle = row["Handle"]

    # Collect all images for this product handle
    image_rows = all_rows[all_rows["Handle"] == handle]
    images = []
    for _, img_row in image_rows.iterrows():
        if pd.notna(img_row.get("Image Src")) and str(img_row["Image Src"]).startswith("http"):
            images.append({
                "src":      str(img_row["Image Src"]),
                "alt":      str(img_row.get("Image Alt Text", "")) if pd.notna(img_row.get("Image Alt Text")) else "",
                "position": int(img_row["Image Position"]) if pd.notna(img_row.get("Image Position")) else 1
            })

    product_data = {
        "product": {
            "title":        str(row["Title"]),
            "body_html":    str(row.get("Body (HTML)", "")) if pd.notna(row.get("Body (HTML)")) else "",
            "vendor":       str(row.get("Vendor", ""))      if pd.notna(row.get("Vendor")) else "",
            "product_type": str(row.get("Type", ""))        if pd.notna(row.get("Type")) else "",
            "tags":         str(row.get("Tags", ""))        if pd.notna(row.get("Tags")) else "",
            "handle":       str(row["Handle"]),
            "status":       str(row.get("Status", "active")).lower() if pd.notna(row.get("Status")) else "active",
            "variants": [{
                "sku":            str(row["Variant SKU"]),
                "price":          str(row.get("Variant Price", "0"))          if pd.notna(row.get("Variant Price")) else "0",
                "compare_at_price": str(row.get("Variant Compare At Price", "")) if pd.notna(row.get("Variant Compare At Price")) else None,
                "inventory_management": str(row.get("Variant Inventory Tracker", "")) if pd.notna(row.get("Variant Inventory Tracker")) else None,
                "inventory_policy": str(row.get("Variant Inventory Policy", "deny")) if pd.notna(row.get("Variant Inventory Policy")) else "deny",
                "fulfillment_service": str(row.get("Variant Fulfillment Service", "manual")) if pd.notna(row.get("Variant Fulfillment Service")) else "manual",
                "taxable":        bool(row.get("Variant Taxable", True)),
                "requires_shipping": bool(row.get("Variant Requires Shipping", True)),
                "weight_unit":    str(row.get("Variant Weight Unit", "kg")) if pd.notna(row.get("Variant Weight Unit")) else "kg",
            }],
            "images": images,
            "published": bool(row.get("Published", True)),
        }
    }

    url  = f"https://{STORE_URL}/admin/api/2025-01/products.json"
    resp = requests.post(url, headers=headers, json=product_data)

    if resp.status_code == 201:
        product = resp.json()["product"]
        print(f"  ✅ Product created → {product['title']}")
        print(f"     ID: {product['id']} | SKU: {row['Variant SKU']} | Images: {len(images)}")
        return product["id"]
    else:
        print(f"  ❌ Failed to create '{row['Title']}': {resp.text[:200]}")
        return None


# ─────────────────────────────────────────────────────────
# 4. SET METAFIELDS
# ─────────────────────────────────────────────────────────
def parse_metafield_columns(df_columns):
    """Auto-detect metafield columns from CSV headers."""
    meta_cols = {}
    for col in df_columns:
        match = METAFIELD_PATTERN.search(col)
        if match:
            namespace = match.group(1)
            key       = match.group(2)
            meta_cols[col] = {"namespace": namespace, "key": key}
    return meta_cols


def clean_value(value):
    """Clean values — strip leading apostrophe (Excel artifact) and whitespace."""
    v = str(value).strip()
    if v.startswith("'"):
        v = v[1:].strip()
    return v


def set_metafields(headers, product_id, row, meta_cols):
    """Set all metafields on a product."""
    url            = f"https://{STORE_URL}/admin/api/2025-01/products/{product_id}/metafields.json"
    success_count  = 0
    skip_count     = 0
    fail_count     = 0

    for col, info in meta_cols.items():
        namespace = info["namespace"]
        key       = info["key"]

        # Skip empty values
        raw = row.get(col)
        if pd.isna(raw) or str(raw).strip() == "" or str(raw).strip() == "nan":
            skip_count += 1
            continue

        value = clean_value(raw)
        if not value:
            skip_count += 1
            continue

        # Determine type
        mf_type = METAFIELD_TYPES.get((namespace, key), "single_line_text_field")

        # Type coercions
        try:
            if mf_type == "number_integer":
                value = str(int(float(value)))
            elif mf_type == "number_decimal":
                value = str(float(value))
            elif mf_type == "boolean":
                value = "true" if str(value).lower() in ("true", "1", "yes") else "false"
        except (ValueError, TypeError):
            mf_type = "single_line_text_field"  # fallback to text

        payload = {
            "metafield": {
                "namespace": namespace,
                "key":       key,
                "value":     value,
                "type":      mf_type
            }
        }

        resp = requests.post(url, headers=headers, json=payload)
        if resp.status_code == 201:
            print(f"    ✅ [{namespace}.{key}] = {value}")
            success_count += 1
        else:
            err = resp.json().get("errors", resp.text)
            print(f"    ❌ [{namespace}.{key}] failed: {err}")
            fail_count += 1

        time.sleep(0.25)  # avoid rate limits

    return success_count, skip_count, fail_count


# ─────────────────────────────────────────────────────────
# 5. MAIN
# ─────────────────────────────────────────────────────────
def run_import():
    print("=" * 60)
    print("   SPARQ DIAMONDS — METAFIELDS IMPORT")
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
        print(f"\n📄 CSV loaded → {len(df)} rows | {len(df.columns)} columns")
    except FileNotFoundError:
        print(f"❌ File not found: {CSV_FILE}")
        return

    # Detect metafield columns
    meta_cols = parse_metafield_columns(df.columns)
    print(f"🏷️  Metafield columns detected: {len(meta_cols)}")
    for col, info in meta_cols.items():
        print(f"   → {info['namespace']}.{info['key']}")

    # Filter to main product rows only (rows with a SKU)
    main_rows = df[df["Variant SKU"].notna() & (df["Variant SKU"].astype(str).str.strip() != "")]
    print(f"\n📦 Products to process: {len(main_rows)}")

    # Counters
    created   = 0
    skipped   = 0
    mf_ok     = 0
    mf_skip   = 0
    mf_fail   = 0

    print("\n🚀 Starting import...\n")

    for i, (_, row) in enumerate(main_rows.iterrows()):
        sku   = str(row["Variant SKU"]).strip()
        title = str(row["Title"])

        print(f"[{i+1}/{len(main_rows)}] {title}")
        print(f"  SKU: {sku}")

        # Check if product already exists
        existing_id = find_product_by_sku(headers, sku)

        if existing_id:
            print(f"  ⚠️  Already exists (ID: {existing_id}) — updating metafields only")
            product_id = existing_id
            skipped   += 1
        else:
            product_id = create_product(headers, row, df)
            if product_id:
                created += 1
            else:
                print(f"  ⏭️  Skipping metafields (product creation failed)\n")
                continue

        # Set metafields
        s, sk, f = set_metafields(headers, product_id, row, meta_cols)
        mf_ok   += s
        mf_skip += sk
        mf_fail += f

        print()
        time.sleep(0.5)

    # Final summary
    print("=" * 60)
    print("   IMPORT COMPLETE — SUMMARY")
    print("=" * 60)
    print(f"  ✅ Products created      : {created}")
    print(f"  ⚠️  Products already existed: {skipped}")
    print(f"  ✅ Metafields set        : {mf_ok}")
    print(f"  ⏭️  Metafields skipped    : {mf_skip} (empty values)")
    print(f"  ❌ Metafield errors      : {mf_fail}")
    print("=" * 60)
    print("\n✅ Go check your Shopify Admin → Products to verify!")


if __name__ == "__main__":
    run_import()