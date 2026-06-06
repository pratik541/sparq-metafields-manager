import os
import requests
import pandas as pd
import time
from datetime import datetime
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

# Output file name (auto-dated)
OUTPUT_FILE = f"metafields_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

# ── Metafield columns to export (namespace.key → CSV column name) ──
METAFIELD_MAP = {
    ("custom",            "happy_shoppers")   : "Happy Shoppers (product.metafields.custom.happy_shoppers)",
    ("custom",            "loved_by_customers"): "Loved By Customers (product.metafields.custom.loved_by_customers)",
    ("custom",            "product_rating")   : "Product Rating (product.metafields.custom.product_rating)",
    ("custom",            "ribbon_text")      : "Ribbon Text (product.metafields.custom.ribbon_text)",
    ("mm-google-shopping","custom_product")   : "Google: Custom Product (product.metafields.mm-google-shopping.custom_product)",
    ("shopify",           "age-group")        : "Age group (product.metafields.shopify.age-group)",
    ("shopify",           "color-pattern")    : "Color (product.metafields.shopify.color-pattern)",
    ("shopify",           "earring-design")   : "Earring design (product.metafields.shopify.earring-design)",
    ("shopify",           "jewelry-material") : "Jewelry material (product.metafields.shopify.jewelry-material)",
    ("shopify",           "jewelry-type")     : "Jewelry type (product.metafields.shopify.jewelry-type)",
    ("shopify",           "target-gender")    : "Target gender (product.metafields.shopify.target-gender)",
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
# 2. FETCH ALL PRODUCTS (paginated)
# ─────────────────────────────────────────────────────────
def fetch_all_products(headers):
    """Fetch all products using pagination (handles stores with 250+ products)."""
    products  = []
    url       = f"https://{STORE_URL}/admin/api/2025-01/products.json?limit=250"

    print("\n📦 Fetching products", end="", flush=True)

    while url:
        resp = requests.get(url, headers=headers)
        if resp.status_code != 200:
            print(f"\n❌ Error fetching products: {resp.status_code} {resp.text}")
            break

        batch = resp.json().get("products", [])
        products.extend(batch)
        print(f".", end="", flush=True)

        # Handle pagination via Link header
        link_header = resp.headers.get("Link", "")
        next_url    = None
        if 'rel="next"' in link_header:
            for part in link_header.split(","):
                if 'rel="next"' in part:
                    next_url = part.strip().split(";")[0].strip("<> ")
                    break
        url = next_url
        time.sleep(0.3)

    print(f"\n✅ Total products fetched: {len(products)}")
    return products


# ─────────────────────────────────────────────────────────
# 3. FETCH METAFIELDS FOR A PRODUCT
# ─────────────────────────────────────────────────────────
def fetch_metafields(headers, product_id):
    """Fetch all metafields for a single product."""
    url  = f"https://{STORE_URL}/admin/api/2025-01/products/{product_id}/metafields.json"
    resp = requests.get(url, headers=headers)
    if resp.status_code == 200:
        return resp.json().get("metafields", [])
    return []


# ─────────────────────────────────────────────────────────
# 4. BUILD CSV ROWS
# ─────────────────────────────────────────────────────────
def build_rows(product, metafields):
    """
    Build CSV rows for one product.
    - Row 1 : full product data + metafields (matches import template format)
    - Row 2+ : image-only rows (for extra images)
    """
    rows = []

    # Build metafield lookup: (namespace, key) → value
    mf_lookup = {}
    for mf in metafields:
        mf_lookup[(mf["namespace"], mf["key"])] = mf["value"]

    # Pull variant (first variant only — single-variant products)
    variant = product["variants"][0] if product.get("variants") else {}

    # Sort images by position
    images = sorted(product.get("images", []), key=lambda x: x.get("position", 99))

    # ── Row 1 — Main product row ──────────────────────────
    main_row = {
        "Handle"                          : product.get("handle", ""),
        "Title"                           : product.get("title", ""),
        "Body (HTML)"                     : product.get("body_html", ""),
        "Vendor"                          : product.get("vendor", ""),
        "Product Category"                : product.get("product_type", ""),
        "Type"                            : product.get("product_type", ""),
        "Tags"                            : product.get("tags", ""),
        "Published"                       : str(product.get("published_at") is not None).upper(),
        "Option1 Name"                    : product["options"][0]["name"] if product.get("options") else "Title",
        "Option1 Value"                   : variant.get("option1", "Default Title"),
        "Option1 Linked To"               : "",
        "Option2 Name"                    : product["options"][1]["name"] if len(product.get("options", [])) > 1 else "",
        "Option2 Value"                   : variant.get("option2", ""),
        "Option2 Linked To"               : "",
        "Option3 Name"                    : product["options"][2]["name"] if len(product.get("options", [])) > 2 else "",
        "Option3 Value"                   : variant.get("option3", ""),
        "Option3 Linked To"               : "",
        "Variant SKU"                     : variant.get("sku", ""),
        "Variant Grams"                   : variant.get("grams", 0),
        "Variant Inventory Tracker"       : variant.get("inventory_management", ""),
        "Variant Inventory Qty"           : variant.get("inventory_quantity", 0),
        "Variant Inventory Policy"        : variant.get("inventory_policy", "deny"),
        "Variant Fulfillment Service"     : variant.get("fulfillment_service", "manual"),
        "Variant Price"                   : variant.get("price", ""),
        "Variant Compare At Price"        : variant.get("compare_at_price", ""),
        "Variant Requires Shipping"       : str(variant.get("requires_shipping", True)).upper(),
        "Variant Taxable"                 : str(variant.get("taxable", True)).upper(),
        "Unit Price Total Measure"        : "",
        "Unit Price Total Measure Unit"   : "",
        "Unit Price Base Measure"         : "",
        "Unit Price Base Measure Unit"    : "",
        "Variant Barcode"                 : variant.get("barcode", ""),
        "Image Src"                       : images[0]["src"]      if images else "",
        "Image Position"                  : images[0]["position"] if images else "",
        "Image Alt Text"                  : images[0].get("alt", "") if images else "",
        "Gift Card"                       : str(product.get("gift_card", False)).upper(),
        "SEO Title"                       : "",
        "SEO Description"                 : "",
        "Google Shopping / Google Product Category": "",
        "Google Shopping / Gender"        : "",
        "Google Shopping / Age Group"     : "",
        "Google Shopping / MPN"           : "",
        "Google Shopping / Condition"     : "",
        "Google Shopping / Custom Product": "",
        "Google Shopping / Custom Label 0": "",
        "Google Shopping / Custom Label 1": "",
        "Google Shopping / Custom Label 2": "",
        "Google Shopping / Custom Label 3": "",
        "Google Shopping / Custom Label 4": "",
        "Variant Image"                   : variant.get("image_id", ""),
        "Variant Weight Unit"             : variant.get("weight_unit", "kg"),
        "Variant Tax Code"                : "",
        "Cost per item"                   : "",
        "Status"                          : product.get("status", "active"),
    }

    # Add metafield values to main row
    for (namespace, key), col_name in METAFIELD_MAP.items():
        main_row[col_name] = mf_lookup.get((namespace, key), "")

    rows.append(main_row)

    # ── Extra image rows (Row 2, 3...) ────────────────────
    for img in images[1:]:
        image_row = {col: "" for col in main_row.keys()}  # blank row
        image_row["Handle"]        = product.get("handle", "")
        image_row["Image Src"]     = img["src"]
        image_row["Image Position"] = img.get("position", "")
        image_row["Image Alt Text"] = img.get("alt", "")
        rows.append(image_row)

    return rows


# ─────────────────────────────────────────────────────────
# 5. MAIN
# ─────────────────────────────────────────────────────────
def run_export():
    print("=" * 60)
    print("   SPARQ DIAMONDS — METAFIELDS EXPORT")
    print("=" * 60)

    # Auth
    token = get_access_token()
    if not token:
        return

    headers = {
        "X-Shopify-Access-Token": token,
        "Content-Type":           "application/json"
    }

    # Fetch all products
    products = fetch_all_products(headers)
    if not products:
        print("⚠️  No products found in store.")
        return

    # Build all rows
    all_rows        = []
    total_mf_found  = 0
    total_mf_empty  = 0

    print(f"\n🏷️  Fetching metafields for each product...\n")

    for i, product in enumerate(products):
        title      = product.get("title", "Unknown")
        sku        = product["variants"][0].get("sku", "N/A") if product.get("variants") else "N/A"
        product_id = product["id"]

        print(f"[{i+1}/{len(products)}] {title[:60]}")
        print(f"   SKU: {sku}")

        # Fetch metafields
        metafields = fetch_metafields(headers, product_id)

        # Count found vs empty
        found_keys = {(mf["namespace"], mf["key"]) for mf in metafields}
        for key in METAFIELD_MAP.keys():
            if key in found_keys:
                total_mf_found += 1
            else:
                total_mf_empty += 1

        if metafields:
            for mf in metafields:
                print(f"   ✅ {mf['namespace']}.{mf['key']} = {str(mf['value'])[:40]}")
        else:
            print(f"   ⚠️  No metafields found")

        # Build CSV rows for this product
        rows = build_rows(product, metafields)
        all_rows.extend(rows)
        print()

        time.sleep(0.3)  # avoid rate limits

    # Save to CSV
    df = pd.DataFrame(all_rows)

    # Reorder columns to match original template order
    template_cols = [
        "Handle", "Title", "Body (HTML)", "Vendor", "Product Category", "Type", "Tags",
        "Published", "Option1 Name", "Option1 Value", "Option1 Linked To",
        "Option2 Name", "Option2 Value", "Option2 Linked To",
        "Option3 Name", "Option3 Value", "Option3 Linked To",
        "Variant SKU", "Variant Grams", "Variant Inventory Tracker",
        "Variant Inventory Qty", "Variant Inventory Policy", "Variant Fulfillment Service",
        "Variant Price", "Variant Compare At Price", "Variant Requires Shipping",
        "Variant Taxable", "Unit Price Total Measure", "Unit Price Total Measure Unit",
        "Unit Price Base Measure", "Unit Price Base Measure Unit", "Variant Barcode",
        "Image Src", "Image Position", "Image Alt Text", "Gift Card",
        "SEO Title", "SEO Description",
        "Google Shopping / Google Product Category", "Google Shopping / Gender",
        "Google Shopping / Age Group", "Google Shopping / MPN",
        "Google Shopping / Condition", "Google Shopping / Custom Product",
        "Google Shopping / Custom Label 0", "Google Shopping / Custom Label 1",
        "Google Shopping / Custom Label 2", "Google Shopping / Custom Label 3",
        "Google Shopping / Custom Label 4",
        "Happy Shoppers (product.metafields.custom.happy_shoppers)",
        "Loved By Customers (product.metafields.custom.loved_by_customers)",
        "Product Rating (product.metafields.custom.product_rating)",
        "Ribbon Text (product.metafields.custom.ribbon_text)",
        "Google: Custom Product (product.metafields.mm-google-shopping.custom_product)",
        "Age group (product.metafields.shopify.age-group)",
        "Color (product.metafields.shopify.color-pattern)",
        "Earring design (product.metafields.shopify.earring-design)",
        "Jewelry material (product.metafields.shopify.jewelry-material)",
        "Jewelry type (product.metafields.shopify.jewelry-type)",
        "Target gender (product.metafields.shopify.target-gender)",
        "Variant Image", "Variant Weight Unit", "Variant Tax Code",
        "Cost per item", "Status",
    ]

    # Keep only columns that exist in df
    final_cols = [c for c in template_cols if c in df.columns]
    df         = df[final_cols]

    df.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig")

    # Final summary
    print("=" * 60)
    print("   EXPORT COMPLETE — SUMMARY")
    print("=" * 60)
    print(f"  📦 Products exported     : {len(products)}")
    print(f"  📄 Total CSV rows        : {len(all_rows)}")
    print(f"  ✅ Metafields with data  : {total_mf_found}")
    print(f"  ⚠️  Metafields empty     : {total_mf_empty}")
    print(f"  💾 Saved to              : {OUTPUT_FILE}")
    print("=" * 60)
    print(f"\n✅ Open '{OUTPUT_FILE}' to view your exported data!")


if __name__ == "__main__":
    run_export()