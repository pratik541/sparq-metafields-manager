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

# All metafield definitions to create
DEFINITIONS = [
    # custom namespace
    {"namespace": "custom", "key": "happy_shoppers",    "type": "number_integer",          "name": "Happy Shoppers",       "owner": "PRODUCT"},
    {"namespace": "custom", "key": "loved_by_customers","type": "number_integer",          "name": "Loved By Customers",   "owner": "PRODUCT"},
    {"namespace": "custom", "key": "product_rating",    "type": "number_decimal",          "name": "Product Rating",       "owner": "PRODUCT"},
    {"namespace": "custom", "key": "ribbon_text",       "type": "single_line_text_field",  "name": "Ribbon Text",          "owner": "PRODUCT"},
    {"namespace": "custom", "key": "prod_var_details",  "type": "rich_text_field",         "name": "Product Variant Details", "owner": "PRODUCT"},

    # shopify namespace
    {"namespace": "shopify", "key": "age-group",        "type": "single_line_text_field",  "name": "Age Group",            "owner": "PRODUCT"},
    {"namespace": "shopify", "key": "color-pattern",    "type": "single_line_text_field",  "name": "Color",                "owner": "PRODUCT"},
    {"namespace": "shopify", "key": "earring-design",   "type": "single_line_text_field",  "name": "Earring Design",       "owner": "PRODUCT"},
    {"namespace": "shopify", "key": "jewelry-material", "type": "single_line_text_field",  "name": "Jewelry Material",     "owner": "PRODUCT"},
    {"namespace": "shopify", "key": "jewelry-type",     "type": "single_line_text_field",  "name": "Jewelry Type",         "owner": "PRODUCT"},
    {"namespace": "shopify", "key": "target-gender",    "type": "single_line_text_field",  "name": "Target Gender",        "owner": "PRODUCT"},

    # mm-google-shopping
    {"namespace": "mm-google-shopping", "key": "custom_product", "type": "boolean", "name": "Custom Product", "owner": "PRODUCT"},
]


def get_access_token():
    resp = requests.post(
        f"https://{STORE_URL}/admin/oauth/access_token",
        json={"grant_type": "client_credentials",
              "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET}
    )
    if resp.status_code == 200:
        print("✅ Access token received")
        return resp.json()["access_token"]
    print(f"❌ {resp.status_code}: {resp.text}")
    return None


def create_definition(headers, defn):
    """Create metafield definition via GraphQL."""
    query = """
    mutation CreateMetafieldDefinition($definition: MetafieldDefinitionInput!) {
      metafieldDefinitionCreate(definition: $definition) {
        createdDefinition { id name namespace key type { name } }
        userErrors { field message }
      }
    }
    """
    variables = {
        "definition": {
            "name":          defn["name"],
            "namespace":     defn["namespace"],
            "key":           defn["key"],
            "type":          defn["type"],
            "ownerType":     defn["owner"],
        }
    }
    resp = requests.post(
        f"https://{STORE_URL}/admin/api/2025-01/graphql.json",
        headers=headers,
        json={"query": query, "variables": variables}
    )
    if resp.status_code == 200:
        data   = resp.json()
        # "data" can be None when Shopify returns top-level GraphQL errors
        gql_errors = data.get("errors")
        if gql_errors:
            return False, gql_errors[0].get("message", str(gql_errors[0]))
        result = (data.get("data") or {}).get("metafieldDefinitionCreate") or {}
        errors = result.get("userErrors", [])
        if errors:
            return False, errors[0]["message"]
        return True, result.get("createdDefinition", {}).get("id")
    return False, resp.text[:100]


def run():
    print("=" * 55)
    print("   CREATE METAFIELD DEFINITIONS")
    print("=" * 55)

    token = get_access_token()
    if not token:
        return

    headers = {
        "X-Shopify-Access-Token": token,
        "Content-Type": "application/json"
    }

    created  = 0
    skipped  = 0
    failed   = 0

    for defn in DEFINITIONS:
        label = f"{defn['namespace']}.{defn['key']} ({defn['type']})"
        print(f"\n→ {label}")

        # shopify namespace is reserved — cannot be created via API
        if defn["namespace"] == "shopify":
            print(f"  ⏭️  Skipped — 'shopify' namespace is reserved by Shopify.")
            print(f"      Create this manually in Shopify Admin → Products → Metafields.")
            skipped += 1
            continue

        ok, result = create_definition(headers, defn)
        if ok:
            print(f"  ✅ Created (ID: {result})")
            created += 1
        elif "in use" in str(result).lower() or "already exists" in str(result).lower() or "taken" in str(result).lower():
            print(f"  ⚠️  Already exists — skipping")
            skipped += 1
        else:
            print(f"  ❌ Failed: {result}")
            failed += 1

    print()
    print("=" * 55)
    print(f"  ✅ Created  : {created}")
    print(f"  ⚠️  Existed  : {skipped}")
    print(f"  ❌ Failed   : {failed}")
    print("=" * 55)
    print("\n✅ Now run update_metafields.py — values will show in Shopify!")


if __name__ == "__main__":
    run()