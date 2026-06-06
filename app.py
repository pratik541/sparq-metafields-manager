import os
import json
import streamlit as st
import requests
import pandas as pd
import time
import re
import io
from datetime import datetime
from pathlib import Path

_env_file = Path(__file__).parent / "config" / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        if _line.strip() and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

# ─────────────────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────────────────
st.set_page_config(
    page_title  = "Sparq Metafields Manager",
    page_icon   = "💎",
    layout      = "wide",
    initial_sidebar_state = "expanded"
)

# ─────────────────────────────────────────────────────────
# CUSTOM CSS
# ─────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=DM+Sans:wght@300;400;500;600&display=swap');

html, body, [class*="css"] {
    font-family: 'DM Sans', sans-serif;
}

/* Sidebar */
section[data-testid="stSidebar"] {
    background: #f0f2f6;
    border-right: 1px solid #dde1e8;
}
section[data-testid="stSidebar"] * {
    color: #1a1a2e !important;
}

/* Main background */
.main { background: #f8f7f4; }

/* Header */
.app-header {
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #FFF0E4 100%);
    padding: 2rem 2.5rem;
    border-radius: 16px;
    margin-bottom: 2rem;
    display: flex;
    align-items: center;
    gap: 1.5rem;
    box-shadow: 0 8px 32px rgba(15,52,96,0.3);
}
.app-header h1 {
    font-family: 'DM Serif Display', serif;
    font-size: 2rem;
    color: #ffffff;
    margin: 0;
    letter-spacing: -0.5px;
}
.app-header p {
    color: #a0aec0;
    margin: 0.3rem 0 0 0;
    font-size: 0.9rem;
}

/* Stat cards */
.stat-card {
    background: white;
    border-radius: 12px;
    padding: 1.2rem 1.5rem;
    border: 1px solid #e8e8e8;
    box-shadow: 0 2px 8px rgba(0,0,0,0.06);
    text-align: center;
}
.stat-number {
    font-family: 'DM Serif Display', serif;
    font-size: 2rem;
    color: #0f3460;
    line-height: 1;
}
.stat-label {
    font-size: 0.78rem;
    color: #888;
    margin-top: 0.3rem;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

/* Section cards */
.section-card {
    background: white;
    border-radius: 16px;
    padding: 2rem;
    border: 1px solid #ebebeb;
    box-shadow: 0 2px 12px rgba(0,0,0,0.05);
    margin-bottom: 1.5rem;
}
.section-title {
    font-family: 'DM Serif Display', serif;
    font-size: 1.3rem;
    color: #1a1a2e;
    margin-bottom: 0.5rem;
}
.section-subtitle {
    font-size: 0.85rem;
    color: #888;
    margin-bottom: 1.5rem;
}

/* Buttons — main area */
.stButton > button {
    background: linear-gradient(135deg, #0f3460, #16213e) !important;
    color: white !important;
    border: none !important;
    border-radius: 8px !important;
    font-family: 'DM Sans', sans-serif !important;
    font-weight: 500 !important;
    padding: 0.6rem 1.8rem !important;
    transition: all 0.2s !important;
    box-shadow: 0 4px 12px rgba(15,52,96,0.25) !important;
}
.stButton > button:hover {
    transform: translateY(-1px) !important;
    box-shadow: 0 6px 20px rgba(15,52,96,0.35) !important;
}

/* Buttons — sidebar (lighter) */
section[data-testid="stSidebar"] .stButton > button {
    background: #4a90d9 !important;
    color: #ffffff !important;
    border: none !important;
    box-shadow: 0 2px 8px rgba(74,144,217,0.3) !important;
}
section[data-testid="stSidebar"] .stButton > button:hover {
    background: #357abd !important;
    color: #ffffff !important;
    box-shadow: 0 4px 14px rgba(74,144,217,0.45) !important;
}

/* Log box */
.log-box {
    background: #0f0f0f;
    color: #00ff88;
    font-family: 'Courier New', monospace;
    font-size: 0.8rem;
    padding: 1rem 1.2rem;
    border-radius: 10px;
    max-height: 350px;
    overflow-y: auto;
    line-height: 1.7;
    border: 1px solid #1a2e1a;
}

/* Badge pills */
.badge {
    display: inline-block;
    padding: 0.2rem 0.7rem;
    border-radius: 20px;
    font-size: 0.75rem;
    font-weight: 600;
    margin: 0.15rem;
}
.badge-blue  { background: #dbeafe; color: #1d4ed8; }
.badge-green { background: #dcfce7; color: #15803d; }
.badge-amber { background: #fef3c7; color: #b45309; }

/* Divider */
.divider {
    border: none;
    border-top: 1px solid #ebebeb;
    margin: 1.5rem 0;
}
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────
# METAFIELD CONFIG
# ─────────────────────────────────────────────────────────
METAFIELD_PATTERN = re.compile(r'product\.metafields\.([^.]+)\.(.+)\)')

METAFIELD_TYPES = {
    ("custom",             "happy_shoppers")    : "number_integer",
    ("custom",             "loved_by_customers"): "number_integer",
    ("custom",             "product_rating")    : "number_decimal",
    ("custom",             "ribbon_text")       : "single_line_text_field",
    ("mm-google-shopping", "custom_product")    : "boolean",
    ("shopify",            "age-group")         : "single_line_text_field",
    ("shopify",            "color-pattern")     : "single_line_text_field",
    ("shopify",            "earring-design")    : "single_line_text_field",
    ("shopify",            "jewelry-material")  : "single_line_text_field",
    ("shopify",            "jewelry-type")      : "single_line_text_field",
    ("shopify",            "target-gender")     : "single_line_text_field",
}

METAFIELD_MAP = {
    ("custom",             "happy_shoppers")    : "Happy Shoppers (product.metafields.custom.happy_shoppers)",
    ("custom",             "loved_by_customers"): "Loved By Customers (product.metafields.custom.loved_by_customers)",
    ("custom",             "product_rating")    : "Product Rating (product.metafields.custom.product_rating)",
    ("custom",             "ribbon_text")       : "Ribbon Text (product.metafields.custom.ribbon_text)",
    ("mm-google-shopping", "custom_product")    : "Google: Custom Product (product.metafields.mm-google-shopping.custom_product)",
    ("shopify",            "age-group")         : "Age group (product.metafields.shopify.age-group)",
    ("shopify",            "color-pattern")     : "Color (product.metafields.shopify.color-pattern)",
    ("shopify",            "earring-design")    : "Earring design (product.metafields.shopify.earring-design)",
    ("shopify",            "jewelry-material")  : "Jewelry material (product.metafields.shopify.jewelry-material)",
    ("shopify",            "jewelry-type")      : "Jewelry type (product.metafields.shopify.jewelry-type)",
    ("shopify",            "target-gender")     : "Target gender (product.metafields.shopify.target-gender)",
}

TEMPLATE_COLS = [
    "Handle","Title","Body (HTML)","Vendor","Product Category","Type","Tags",
    "Published","Option1 Name","Option1 Value","Option1 Linked To",
    "Option2 Name","Option2 Value","Option2 Linked To",
    "Option3 Name","Option3 Value","Option3 Linked To",
    "Variant SKU","Variant Grams","Variant Inventory Tracker",
    "Variant Inventory Qty","Variant Inventory Policy","Variant Fulfillment Service",
    "Variant Price","Variant Compare At Price","Variant Requires Shipping",
    "Variant Taxable","Unit Price Total Measure","Unit Price Total Measure Unit",
    "Unit Price Base Measure","Unit Price Base Measure Unit","Variant Barcode",
    "Image Src","Image Position","Image Alt Text","Gift Card",
    "SEO Title","SEO Description",
    "Google Shopping / Google Product Category","Google Shopping / Gender",
    "Google Shopping / Age Group","Google Shopping / MPN",
    "Google Shopping / Condition","Google Shopping / Custom Product",
    "Google Shopping / Custom Label 0","Google Shopping / Custom Label 1",
    "Google Shopping / Custom Label 2","Google Shopping / Custom Label 3",
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
    "Variant Image","Variant Weight Unit","Variant Tax Code","Cost per item","Status",
]


# ─────────────────────────────────────────────────────────
# API HELPERS
# ─────────────────────────────────────────────────────────
def get_access_token(store_url, client_id, client_secret):
    url = f"https://{store_url}/admin/oauth/access_token"
    try:
        resp = requests.post(url, json={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        }, timeout=15)
    except requests.exceptions.Timeout:
        return None, "Connection timed out. Check your Store URL and network."
    except requests.exceptions.ConnectionError:
        return None, "Cannot reach the store. Check your Store URL."
    if resp.status_code == 200:
        return resp.json()["access_token"], None
    return None, f"Auth failed {resp.status_code}: {resp.text}"


def fetch_all_products(headers, store_url):
    products = []
    url = f"https://{store_url}/admin/api/2025-01/products.json?limit=250"
    while url:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code != 200:
            break
        products.extend(resp.json().get("products", []))
        link = resp.headers.get("Link", "")
        url  = None
        if 'rel="next"' in link:
            for part in link.split(","):
                if 'rel="next"' in part:
                    url = part.strip().split(";")[0].strip("<> ")
        time.sleep(0.3)
    return products


def fetch_metafields(headers, store_url, product_id):
    url  = f"https://{store_url}/admin/api/2025-01/products/{product_id}/metafields.json"
    resp = requests.get(url, headers=headers, timeout=15)
    if resp.status_code == 200:
        return resp.json().get("metafields", [])
    return []


def find_product_by_sku(headers, store_url, sku, products_cache):
    for product in products_cache:
        for variant in product.get("variants", []):
            if variant.get("sku") == sku:
                return product["id"]
    return None


def create_product(headers, store_url, row, all_rows):
    handle     = row["Handle"]
    image_rows = all_rows[all_rows["Handle"] == handle]
    images     = []
    for _, ir in image_rows.iterrows():
        src = ir.get("Image Src")
        if pd.notna(src) and str(src).startswith("http"):
            images.append({
                "src":      str(src),
                "alt":      str(ir.get("Image Alt Text","")) if pd.notna(ir.get("Image Alt Text")) else "",
                "position": int(ir["Image Position"]) if pd.notna(ir.get("Image Position")) else 1
            })

    data = {"product": {
        "title":        str(row["Title"]),
        "body_html":    str(row.get("Body (HTML)",""))    if pd.notna(row.get("Body (HTML)"))   else "",
        "vendor":       str(row.get("Vendor",""))         if pd.notna(row.get("Vendor"))         else "",
        "product_type": str(row.get("Type",""))           if pd.notna(row.get("Type"))           else "",
        "tags":         str(row.get("Tags",""))           if pd.notna(row.get("Tags"))           else "",
        "handle":       str(row["Handle"]),
        "status":       str(row.get("Status","active")).lower() if pd.notna(row.get("Status")) else "active",
        "variants": [{"sku": str(row["Variant SKU"]),
                      "price": str(row.get("Variant Price","0")) if pd.notna(row.get("Variant Price")) else "0",
                      "compare_at_price": str(row.get("Variant Compare At Price","")) if pd.notna(row.get("Variant Compare At Price")) else None,
                      "inventory_management": str(row.get("Variant Inventory Tracker","")) if pd.notna(row.get("Variant Inventory Tracker")) else None,
                      "inventory_policy": str(row.get("Variant Inventory Policy","deny")) if pd.notna(row.get("Variant Inventory Policy")) else "deny",
                      "fulfillment_service": "manual",
                      "taxable": True,
                      "requires_shipping": True,
                      "weight_unit": str(row.get("Variant Weight Unit","kg")) if pd.notna(row.get("Variant Weight Unit")) else "kg",
                      }],
        "images": images,
        "published": True,
    }}

    resp = requests.post(f"https://{store_url}/admin/api/2025-01/products.json", headers=headers, json=data, timeout=15)
    if resp.status_code == 201:
        return resp.json()["product"]["id"], None
    return None, resp.text[:200]


def set_metafields_for_product(headers, store_url, product_id, row, meta_cols):
    url   = f"https://{store_url}/admin/api/2025-01/products/{product_id}/metafields.json"
    ok, skip, fail = 0, 0, 0
    logs  = []
    for col, info in meta_cols.items():
        ns, key = info["namespace"], info["key"]
        raw = row.get(col)
        if pd.isna(raw) or str(raw).strip() in ("", "nan"):
            skip += 1
            continue
        value   = str(raw).strip().lstrip("'")
        mf_type = METAFIELD_TYPES.get((ns, key), "single_line_text_field")
        try:
            if mf_type == "number_integer":  value = str(int(float(value)))
            elif mf_type == "number_decimal": value = str(float(value))
            elif mf_type == "boolean":        value = "true" if value.lower() in ("true","1","yes") else "false"
        except:
            mf_type = "single_line_text_field"
        resp = requests.post(url, headers=headers, json={"metafield": {"namespace":ns,"key":key,"value":value,"type":mf_type}}, timeout=15)
        if resp.status_code == 201:
            logs.append(f"✅ {ns}.{key} = {value}")
            ok += 1
        else:
            logs.append(f"❌ {ns}.{key} → {resp.text[:80]}")
            fail += 1
        time.sleep(0.2)
    return ok, skip, fail, logs


def parse_metafield_columns(df_columns):
    meta_cols = {}
    for col in df_columns:
        match = METAFIELD_PATTERN.search(col)
        if match:
            meta_cols[col] = {"namespace": match.group(1), "key": match.group(2)}
    return meta_cols


def build_export_rows(product, metafields):
    mf_lookup = {(mf["namespace"], mf["key"]): mf["value"] for mf in metafields}
    variant   = product["variants"][0] if product.get("variants") else {}
    images    = sorted(product.get("images", []), key=lambda x: x.get("position", 99))
    rows      = []

    main = {
        "Handle": product.get("handle",""), "Title": product.get("title",""),
        "Body (HTML)": product.get("body_html",""), "Vendor": product.get("vendor",""),
        "Product Category": product.get("product_type",""), "Type": product.get("product_type",""),
        "Tags": product.get("tags",""), "Published": "TRUE",
        "Option1 Name": product["options"][0]["name"] if product.get("options") else "Title",
        "Option1 Value": variant.get("option1","Default Title"), "Option1 Linked To": "",
        "Option2 Name": "", "Option2 Value": "", "Option2 Linked To": "",
        "Option3 Name": "", "Option3 Value": "", "Option3 Linked To": "",
        "Variant SKU": variant.get("sku",""), "Variant Grams": variant.get("grams",0),
        "Variant Inventory Tracker": variant.get("inventory_management",""),
        "Variant Inventory Qty": variant.get("inventory_quantity",0),
        "Variant Inventory Policy": variant.get("inventory_policy","deny"),
        "Variant Fulfillment Service": variant.get("fulfillment_service","manual"),
        "Variant Price": variant.get("price",""), "Variant Compare At Price": variant.get("compare_at_price",""),
        "Variant Requires Shipping": "TRUE", "Variant Taxable": "TRUE",
        "Unit Price Total Measure": "", "Unit Price Total Measure Unit": "",
        "Unit Price Base Measure": "", "Unit Price Base Measure Unit": "",
        "Variant Barcode": variant.get("barcode",""),
        "Image Src": images[0]["src"] if images else "",
        "Image Position": images[0]["position"] if images else "",
        "Image Alt Text": images[0].get("alt","") if images else "",
        "Gift Card": "FALSE", "SEO Title": "", "SEO Description": "",
        "Google Shopping / Google Product Category": "",
        "Google Shopping / Gender": "", "Google Shopping / Age Group": "",
        "Google Shopping / MPN": "", "Google Shopping / Condition": "",
        "Google Shopping / Custom Product": "",
        "Google Shopping / Custom Label 0": "", "Google Shopping / Custom Label 1": "",
        "Google Shopping / Custom Label 2": "", "Google Shopping / Custom Label 3": "",
        "Google Shopping / Custom Label 4": "",
        "Variant Image": "", "Variant Weight Unit": variant.get("weight_unit","kg"),
        "Variant Tax Code": "", "Cost per item": "",
        "Status": product.get("status","active"),
    }
    for (ns, key), col_name in METAFIELD_MAP.items():
        main[col_name] = mf_lookup.get((ns, key), "")

    rows.append(main)

    for img in images[1:]:
        row = {col: "" for col in main.keys()}
        row["Handle"]         = product.get("handle","")
        row["Image Src"]      = img["src"]
        row["Image Position"] = img.get("position","")
        row["Image Alt Text"] = img.get("alt","")
        rows.append(row)

    return rows


# ─────────────────────────────────────────────────────────
# SESSION STATE
# ─────────────────────────────────────────────────────────
if "connected"  not in st.session_state: st.session_state.connected  = False
if "token"      not in st.session_state: st.session_state.token      = None
if "headers"    not in st.session_state: st.session_state.headers    = None
if "store_url"  not in st.session_state: st.session_state.store_url  = os.getenv("SHOPIFY_STORE_URL", "")
if "import_log" not in st.session_state: st.session_state.import_log = []
if "export_df"  not in st.session_state: st.session_state.export_df  = None


# ─────────────────────────────────────────────────────────
# SIDEBAR — CREDENTIALS
# ─────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 💎 Sparq Diamonds")
    st.markdown("### Store Connection")
    st.markdown("---")

    store_url     = st.text_input("Store URL", placeholder="sparq-diamonds-dev.myshopify.com", value=st.session_state.store_url)
    client_id     = st.text_input("Client ID",     type="password", placeholder="from Dev Dashboard", value=os.getenv("SHOPIFY_CLIENT_ID", ""))
    client_secret = st.text_input("Client Secret", type="password", placeholder="from Dev Dashboard", value=os.getenv("SHOPIFY_CLIENT_SECRET", ""))

    if st.button("🔌 Connect to Store", use_container_width=True):
        if store_url and client_id and client_secret:
            with st.spinner("Connecting..."):
                token, err = get_access_token(store_url, client_id, client_secret)
            if token:
                st.session_state.connected = True
                st.session_state.token     = token
                st.session_state.store_url = store_url
                st.session_state.headers   = {
                    "X-Shopify-Access-Token": token,
                    "Content-Type": "application/json"
                }
                st.success("✅ Connected!")
            else:
                st.error(f"❌ {err}")
        else:
            st.warning("Please fill all fields")

    st.markdown("---")
    if st.session_state.connected:
        st.markdown(f"""
        <div style='background:#dcfce7;padding:0.8rem 1rem;border-radius:8px;border:1px solid #86efac'>
            <div style='color:#15803d;font-size:0.75rem;font-weight:600'>● CONNECTED</div>
            <div style='color:#166534;font-size:0.8rem;margin-top:0.2rem'>{st.session_state.store_url}</div>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown("""
        <div style='background:#fee2e2;padding:0.8rem 1rem;border-radius:8px;border:1px solid #fca5a5'>
            <div style='color:#dc2626;font-size:0.75rem;font-weight:600'>● NOT CONNECTED</div>
            <div style='color:#b91c1c;font-size:0.8rem;margin-top:0.2rem'>Enter credentials above</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("""
    <div style='font-size:0.75rem;color:#666;line-height:1.6'>
    <b>Metafields supported:</b><br>
    • custom.happy_shoppers<br>
    • custom.loved_by_customers<br>
    • custom.product_rating<br>
    • custom.ribbon_text<br>
    • shopify.jewelry-type<br>
    • shopify.jewelry-material<br>
    • shopify.target-gender<br>
    • shopify.earring-design<br>
    • shopify.color-pattern<br>
    • shopify.age-group<br>
    • mm-google-shopping.custom_product
    </div>
    """, unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────
# MAIN CONTENT
# ─────────────────────────────────────────────────────────

# Header
st.markdown("""
<div class="app-header">
    <div style="font-size:3rem">💎</div>
    <div>
        <h1>Metafields Manager</h1>
        <p>Import & Export product metafields for Sparq Diamonds · Powered by Shopify Admin API</p>
    </div>
</div>
""", unsafe_allow_html=True)


# ── Stats row ─────────────────────────────────────────────
products = []
if st.session_state.connected:
    with st.spinner("Loading store stats..."):
        try:
            products = fetch_all_products(st.session_state.headers, st.session_state.store_url)
        except requests.exceptions.Timeout:
            st.warning("⚠️ Store connection timed out. Check your network and try reconnecting.")
            st.session_state.connected = False
            st.session_state.token = None
        except requests.exceptions.ConnectionError:
            st.warning("⚠️ Cannot reach the store. Check your Store URL.")
            st.session_state.connected = False
            st.session_state.token = None

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(f"""<div class="stat-card">
            <div class="stat-number">{len(products)}</div>
            <div class="stat-label">Total Products</div>
        </div>""", unsafe_allow_html=True)
    with col2:
        skus = sum(1 for p in products if any(v.get("sku") for v in p.get("variants",[])))
        st.markdown(f"""<div class="stat-card">
            <div class="stat-number">{skus}</div>
            <div class="stat-label">Products with SKU</div>
        </div>""", unsafe_allow_html=True)
    with col3:
        active = sum(1 for p in products if p.get("status") == "active")
        st.markdown(f"""<div class="stat-card">
            <div class="stat-number">{active}</div>
            <div class="stat-label">Active Products</div>
        </div>""", unsafe_allow_html=True)
    with col4:
        st.markdown(f"""<div class="stat-card">
            <div class="stat-number">11</div>
            <div class="stat-label">Metafield Columns</div>
        </div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
else:
    st.info("👈 Connect your Shopify store from the sidebar to get started.")
    st.stop()


# ── Tabs ──────────────────────────────────────────────────
tab1, tab2, tab3, tab4 = st.tabs(["📥  Import Metafields", "📤  Export Metafields", "📋  View Products", "🔄  Update Metafields"])


# ─────────────────────────────────────────────────────────
# TAB 1 — IMPORT
# ─────────────────────────────────────────────────────────
with tab1:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Import Products & Metafields</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-subtitle">Upload your CSV file — products will be created if they don\'t exist, metafields will be set automatically.</div>', unsafe_allow_html=True)

    uploaded = st.file_uploader("Upload CSV File", type=["csv"], key="import_file",
                                help="Upload a Shopify-format CSV with metafield columns")

    if uploaded:
        df_import = pd.read_csv(uploaded)
        meta_cols = parse_metafield_columns(df_import.columns)

        # Preview
        main_rows = df_import[df_import["Variant SKU"].notna() & (df_import["Variant SKU"].astype(str).str.strip() != "")]

        col_a, col_b, col_c = st.columns(3)
        col_a.metric("Rows in CSV",        len(df_import))
        col_b.metric("Unique Products",    len(main_rows))
        col_c.metric("Metafield Columns",  len(meta_cols))

        st.markdown("<hr class='divider'>", unsafe_allow_html=True)

        # Show detected metafields
        st.markdown("**Detected Metafield Columns:**")
        badges = ""
        for col, info in meta_cols.items():
            badges += f'<span class="badge badge-blue">{info["namespace"]}.{info["key"]}</span>'
        st.markdown(badges, unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        # Preview table
        with st.expander("👁️ Preview CSV Data", expanded=False):
            st.dataframe(main_rows[["Handle","Title","Variant SKU","Variant Price"]].head(10), use_container_width=True)

        st.markdown("<br>", unsafe_allow_html=True)

        if st.button("🚀 Start Import", use_container_width=False):
            st.session_state.import_log = []
            log_placeholder = st.empty()
            progress        = st.progress(0)
            status_text     = st.empty()

            products_cache  = fetch_all_products(st.session_state.headers, st.session_state.store_url)
            total           = len(main_rows)
            created         = 0
            skipped         = 0
            mf_ok           = 0
            mf_fail         = 0

            def add_log(msg):
                st.session_state.import_log.append(msg)
                log_html = "<br>".join(st.session_state.import_log[-40:])
                log_placeholder.markdown(f'<div class="log-box">{log_html}</div>', unsafe_allow_html=True)

            add_log(f"🚀 Starting import of {total} products...")
            add_log(f"─────────────────────────────────────")

            for i, (_, row) in enumerate(main_rows.iterrows()):
                sku   = str(row["Variant SKU"]).strip()
                title = str(row["Title"])[:50]
                status_text.markdown(f"**Processing [{i+1}/{total}]:** {title}")
                progress.progress((i + 1) / total)
                add_log(f"")
                add_log(f"[{i+1}/{total}] {title}")
                add_log(f"  SKU: {sku}")

                existing_id = find_product_by_sku(st.session_state.headers, st.session_state.store_url, sku, products_cache)

                if existing_id:
                    product_id = existing_id
                    skipped   += 1
                    add_log(f"  ⚠️  Already exists — updating metafields only")
                else:
                    product_id, err = create_product(st.session_state.headers, st.session_state.store_url, row, df_import)
                    if product_id:
                        created += 1
                        add_log(f"  ✅ Product created (ID: {product_id})")
                    else:
                        add_log(f"  ❌ Creation failed: {err}")
                        continue

                ok, sk, fl, logs = set_metafields_for_product(
                    st.session_state.headers, st.session_state.store_url,
                    product_id, row, meta_cols
                )
                for l in logs:
                    add_log(f"    {l}")
                mf_ok   += ok
                mf_fail += fl
                time.sleep(0.3)

            progress.progress(1.0)
            status_text.markdown("**✅ Import complete!**")
            add_log(f"")
            add_log(f"─────────────────────────────────────")
            add_log(f"✅ Products created   : {created}")
            add_log(f"⚠️  Already existed   : {skipped}")
            add_log(f"✅ Metafields set     : {mf_ok}")
            add_log(f"❌ Metafield errors   : {mf_fail}")
            add_log(f"─────────────────────────────────────")

            st.success(f"✅ Done! {created} products created, {mf_ok} metafields set.")

    st.markdown('</div>', unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────
# TAB 2 — EXPORT
# ─────────────────────────────────────────────────────────
with tab2:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Export Products & Metafields</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-subtitle">Export all products with their metafields to a CSV file matching your import template format.</div>', unsafe_allow_html=True)

    col_e1, col_e2 = st.columns([1, 2])
    with col_e1:
        st.metric("Products in Store", len(products))
        include_empty = st.checkbox("Include empty metafields", value=True)

    with col_e2:
        st.markdown("**Export will include:**")
        st.markdown("""
        - ✅ All product details (title, description, vendor, tags)
        - ✅ Variant data (SKU, price, inventory)
        - ✅ All product images (multiple rows per product)
        - ✅ All 11 metafield columns
        - ✅ Same column format as your import template
        """)

    st.markdown("<br>", unsafe_allow_html=True)

    if st.button("📤 Export to CSV", use_container_width=False):
        export_log  = st.empty()
        export_prog = st.progress(0)
        all_rows    = []
        logs        = []

        def elog(msg):
            logs.append(msg)
            log_html = "<br>".join(logs[-30:])
            export_log.markdown(f'<div class="log-box">{log_html}</div>', unsafe_allow_html=True)

        elog(f"📦 Fetching metafields for {len(products)} products...")

        for i, product in enumerate(products):
            title = product.get("title","")[:50]
            elog(f"[{i+1}/{len(products)}] {title}")
            export_prog.progress((i + 1) / len(products))

            metafields = fetch_metafields(st.session_state.headers, st.session_state.store_url, product["id"])
            rows       = build_export_rows(product, metafields)
            all_rows.extend(rows)

            found_keys = {(mf["namespace"], mf["key"]) for mf in metafields}
            for (ns, key) in METAFIELD_MAP.keys():
                if (ns, key) in found_keys:
                    elog(f"  ✅ {ns}.{key}")
            time.sleep(0.25)

        export_prog.progress(1.0)

        # Build DataFrame
        df_export  = pd.DataFrame(all_rows)
        final_cols = [c for c in TEMPLATE_COLS if c in df_export.columns]
        df_export  = df_export[final_cols]

        st.session_state.export_df = df_export

        elog(f"")
        elog(f"✅ Export complete! {len(products)} products, {len(all_rows)} rows")

    # Download button
    if st.session_state.export_df is not None:
        df = st.session_state.export_df
        st.success(f"✅ Export ready — {len(df)} rows, {len(df.columns)} columns")

        # Preview
        with st.expander("👁️ Preview Export Data", expanded=True):
            st.dataframe(df.head(10), use_container_width=True)

        # Download
        csv_buffer = io.StringIO()
        df.to_csv(csv_buffer, index=False, encoding="utf-8")
        filename = f"metafields_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

        st.download_button(
            label     = "⬇️ Download CSV",
            data      = csv_buffer.getvalue().encode("utf-8"),
            file_name = filename,
            mime      = "text/csv",
            use_container_width = False
        )

    st.markdown('</div>', unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────
# TAB 3 — VIEW PRODUCTS
# ─────────────────────────────────────────────────────────
with tab3:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.markdown('<div class="section-title">All Products in Store</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="section-subtitle">{len(products)} products found in {st.session_state.store_url}</div>', unsafe_allow_html=True)

    # Search
    search = st.text_input("🔍 Search by title or SKU", placeholder="e.g. Diamond Ring or SQTNP8520")

    # Build table
    rows = []
    for p in products:
        variant = p["variants"][0] if p.get("variants") else {}
        rows.append({
            "Title"   : p.get("title",""),
            "SKU"     : variant.get("sku",""),
            "Price"   : f"₹{variant.get('price','')}",
            "Status"  : p.get("status","").upper(),
            "Vendor"  : p.get("vendor",""),
            "Type"    : p.get("product_type",""),
            "Images"  : len(p.get("images",[])),
            "Variants": len(p.get("variants",[])),
        })

    df_view = pd.DataFrame(rows)

    if search:
        mask    = (
            df_view["Title"].str.contains(search, case=False, na=False) |
            df_view["SKU"].str.contains(search, case=False, na=False)
        )
        df_view = df_view[mask]

    st.dataframe(df_view, use_container_width=True, height=450,
                 column_config={
                     "Price":  st.column_config.TextColumn("Price"),
                     "Status": st.column_config.TextColumn("Status"),
                     "Images": st.column_config.NumberColumn("Images", format="%d 🖼️"),
                 })

    st.markdown(f"Showing **{len(df_view)}** of **{len(products)}** products", unsafe_allow_html=False)
    st.markdown('</div>', unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────
# TAB 4 — UPDATE METAFIELDS
# ─────────────────────────────────────────────────────────
with tab4:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Update Metafields by Handle / SKU</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-subtitle">Upload a targeted update CSV — finds each product by Handle or Variant SKU and creates or updates the specified metafield.</div>', unsafe_allow_html=True)

    # Expected format info
    with st.expander("📋 Expected CSV Format", expanded=False):
        st.markdown("Your CSV must have these **6 columns** (exact names):")
        sample_df = pd.DataFrame([
            {
                "Handle":             "sparq-lab-grown-diamond-017ct-...",
                "Variant SKU":        "SQTNP8520-EG-925S-0.17CT",
                "Metafield namespace":"custom",
                "Metafield Key":      "product_details",
                "Metafield type":     "rich_text_field",
                "Metafield Value":    "Your value here",
            }
        ])
        st.dataframe(sample_df, use_container_width=True)
        st.markdown("""
        **Match logic:**
        - Tries **Handle** first (exact match)
        - Falls back to **Variant SKU** if handle not found
        - If metafield already exists → **updates** it
        - If metafield doesn't exist → **creates** it
        """)

    st.markdown("<br>", unsafe_allow_html=True)

    # File uploader
    update_file = st.file_uploader("Upload Update CSV", type=["csv"], key="update_file")

    if update_file:
        df_update = pd.read_csv(update_file)

        # Validate columns
        required_cols = ["Handle", "Variant SKU", "Metafield namespace",
                         "Metafield Key", "Metafield type", "Metafield Value"]
        missing_cols  = [c for c in required_cols if c not in df_update.columns]

        if missing_cols:
            st.error(f"❌ Missing columns: {missing_cols}")
            st.stop()

        # Stats
        col_u1, col_u2, col_u3 = st.columns(3)
        col_u1.metric("Rows to Update",       len(df_update))
        col_u2.metric("Unique Handles",        df_update["Handle"].nunique())
        col_u3.metric("Unique Metafield Keys", df_update["Metafield Key"].nunique())

        st.markdown("<hr class='divider'>", unsafe_allow_html=True)

        # Preview
        with st.expander("👁️ Preview Update Data", expanded=True):
            st.dataframe(df_update, use_container_width=True)

        # Show what metafields will be updated
        st.markdown("**Metafields to be updated:**")
        grouped = df_update.groupby(["Metafield namespace", "Metafield Key", "Metafield type"]).size().reset_index(name="count")
        for _, grow in grouped.iterrows():
            st.markdown(
                f'<span class="badge badge-amber">{grow["Metafield namespace"]}.{grow["Metafield Key"]}</span>'
                f'<span class="badge badge-blue">{grow["Metafield type"]}</span>'
                f'<span class="badge badge-green">{grow["count"]} products</span>',
                unsafe_allow_html=True
            )

        st.markdown("<br>", unsafe_allow_html=True)

        if st.button("🔄 Start Update", key="btn_update"):

            # Cache products
            with st.spinner("Loading products from store..."):
                products_cache = fetch_all_products(st.session_state.headers, st.session_state.store_url)

            update_log  = st.empty()
            update_prog = st.progress(0)
            update_status = st.empty()

            u_logs   = []
            updated  = 0
            ucreated = 0
            failed   = 0
            notfound = 0
            total    = len(df_update)

            def ulog(msg):
                u_logs.append(msg)
                log_html = "<br>".join(u_logs[-40:])
                update_log.markdown(f'<div class="log-box">{log_html}</div>', unsafe_allow_html=True)

            ulog(f"📦 {len(products_cache)} products loaded from store")
            ulog(f"🚀 Starting update of {total} rows...")
            ulog("─────────────────────────────────────")

            for i, row in df_update.iterrows():
                handle    = str(row.get("Handle","")).strip()
                sku       = str(row.get("Variant SKU","")).strip()
                namespace = str(row.get("Metafield namespace","")).strip()
                key       = str(row.get("Metafield Key","")).strip()
                mf_type   = str(row.get("Metafield type","")).strip()
                value     = row.get("Metafield Value","")

                update_prog.progress((i + 1) / total)
                update_status.markdown(f"**Processing [{i+1}/{total}]:** `{sku}`")

                ulog(f"")
                ulog(f"[{i+1}/{total}] SKU: {sku}")

                # Skip empty
                if pd.isna(value) or str(value).strip() == "":
                    ulog(f"  ⏭️  Skipped — empty value")
                    continue

                # Find product by handle → SKU fallback
                product_id = None
                title      = ""
                if handle:
                    for p in products_cache:
                        if p.get("handle","").strip() == handle:
                            product_id = p["id"]
                            title      = p.get("title","")
                            break
                if not product_id and sku:
                    for p in products_cache:
                        for v in p.get("variants",[]):
                            if str(v.get("sku","")).strip() == sku:
                                product_id = p["id"]
                                title      = p.get("title","")
                                break
                        if product_id:
                            break

                if not product_id:
                    ulog(f"  ❌ NOT FOUND — handle: {handle[:40]}")
                    notfound += 1
                    continue

                ulog(f"  ✅ Found: {title[:50]}")

                # Check if metafield already exists
                mf_url    = f"https://{st.session_state.store_url}/admin/api/2025-01/products/{product_id}/metafields.json"
                mf_resp   = requests.get(mf_url, headers=st.session_state.headers, timeout=15)
                existing_id = None
                if mf_resp.status_code == 200:
                    for mf in mf_resp.json().get("metafields",[]):
                        if mf["namespace"] == namespace and mf["key"] == key:
                            existing_id = mf["id"]
                            break

                # Coerce value to correct string format for the given type
                raw = str(value).strip().lstrip("'")
                try:
                    if mf_type == "number_integer":
                        raw = str(int(float(raw)))
                    elif mf_type == "number_decimal":
                        raw = str(float(raw))
                    elif mf_type == "boolean":
                        raw = "true" if raw.lower() in ("true", "1", "yes") else "false"
                    elif mf_type == "rich_text_field":
                        # Only skip wrapping if value is already a Shopify rich text JSON object
                        try:
                            parsed = json.loads(raw)
                            already_rich = isinstance(parsed, dict) and parsed.get("type") == "root"
                        except (json.JSONDecodeError, ValueError):
                            already_rich = False
                        if not already_rich:
                            plain = re.sub(r"<[^>]+>", "", raw).strip()
                            raw = json.dumps({
                                "type": "root",
                                "children": [{"type": "paragraph", "children": [{"type": "text", "value": plain}]}]
                            })
                except (ValueError, TypeError):
                    pass

                payload = {"metafield": {
                    "namespace": namespace, "key": key,
                    "value": raw, "type": mf_type
                }}

                if existing_id:
                    # UPDATE
                    resp = requests.put(
                        f"https://{st.session_state.store_url}/admin/api/2025-01/metafields/{existing_id}.json",
                        headers=st.session_state.headers, json=payload, timeout=15
                    )
                    if resp.status_code == 200:
                        ulog(f"  🔄 UPDATED → {namespace}.{key} = {str(value)[:40]}")
                        updated += 1
                    else:
                        ulog(f"  ❌ Update failed: {resp.text[:80]}")
                        failed += 1
                else:
                    # CREATE
                    resp = requests.post(mf_url, headers=st.session_state.headers, json=payload, timeout=15)
                    if resp.status_code == 201:
                        ulog(f"  ✨ CREATED → {namespace}.{key} = {str(value)[:40]}")
                        ucreated += 1
                    else:
                        ulog(f"  ❌ Create failed: {resp.text[:80]}")
                        failed += 1

                time.sleep(0.35)

            update_prog.progress(1.0)
            update_status.markdown("**✅ Update complete!**")
            ulog("")
            ulog("─────────────────────────────────────")
            ulog(f"🔄 Metafields updated  : {updated}")
            ulog(f"✨ Metafields created  : {ucreated}")
            ulog(f"❌ Failed              : {failed}")
            ulog(f"🔍 Products not found  : {notfound}")
            ulog("─────────────────────────────────────")

            # Summary cards
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("🔄 Updated",   updated)
            c2.metric("✨ Created",   ucreated)
            c3.metric("❌ Failed",    failed)
            c4.metric("🔍 Not Found", notfound)

    st.markdown('</div>', unsafe_allow_html=True)