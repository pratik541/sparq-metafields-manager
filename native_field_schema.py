"""Read the store's real native-field schema via GraphQL introspection.

native_update.py hardcodes NATIVE_PRODUCT_FIELDS and NATIVE_VARIANT_FIELDS, a
deliberately small, tested subset of what Shopify's ProductInput and
ProductVariantsBulkInput actually accept. This module asks the live schema
instead, the same way metafield_definitions.py asks the store for its real
metafield definitions rather than trusting a hardcoded guess.

No Streamlit imports, so it can be tested without a UI.
"""

import requests

API_VER = "2025-01"

# Nested input object types worth expanding into dotted paths, matching the
# convention NATIVE_PRODUCT_FIELDS/NATIVE_VARIANT_FIELDS already use (e.g.
# "seo.title", "inventoryItem.measurement.weight").
FLATTENABLE_TYPES = {"SEOInput", "InventoryItemInput", "InventoryItemMeasurementInput"}

# Object types that resolve to one combined CSV value today (a dict with a
# couple of sub-keys), rather than needing further flattening.
COMPOSITE_NOTES = {
    "WeightInput": "Composite value (value + unit) — see Variant Grams",
    "MoneyInput": "Composite value (amount + currency)",
}

# Types that can't be a plain CSV cell — they need a GID, a list, or a
# structured object the bulk-update tool doesn't build today.
COMPLEX_TYPES = {
    "ID", "OptionCreateInput", "ProductClaimOwnershipInput",
    "InventoryLevelInput", "VariantOptionValueInput",
    "CountryHarmonizedSystemCodeInput", "UnitPriceMeasurementInput",
}

SKIP_FIELDS = {"id"}  # internal identifier, supplied automatically, never a CSV column

SCHEMA_TYPES = (
    "ProductInput", "ProductVariantsBulkInput",
    "SEOInput", "InventoryItemInput", "InventoryItemMeasurementInput",
)

_FIELD_SELECTION = "inputFields { name type { kind name ofType { kind name ofType { kind name } } } }"

SCHEMA_QUERY = f"""
{{
  t0: __type(name: "{SCHEMA_TYPES[0]}") {{ {_FIELD_SELECTION} }}
  t1: __type(name: "{SCHEMA_TYPES[1]}") {{ {_FIELD_SELECTION} }}
  t2: __type(name: "{SCHEMA_TYPES[2]}") {{ {_FIELD_SELECTION} }}
  t3: __type(name: "{SCHEMA_TYPES[3]}") {{ {_FIELD_SELECTION} }}
  t4: __type(name: "{SCHEMA_TYPES[4]}") {{ {_FIELD_SELECTION} }}
}}
"""

SCHEMA_COLUMNS = ["Owner", "GraphQL Path", "Type", "Supported in this app", "Notes"]


def _unwrap(type_node):
    """Return the innermost named type, looking through NON_NULL/LIST wrappers."""
    while type_node and not type_node.get("name"):
        type_node = type_node.get("ofType")
    return (type_node or {}).get("name", "")


def _flatten(fields_by_type, type_name, prefix, owner_label, supported, depth=0):
    """Turn one input type's fields into reference rows, recursing into
    nested object types up to a shallow depth to avoid runaway recursion.
    """
    rows = []
    if depth > 3:
        return rows

    for field in fields_by_type.get(type_name, []):
        name = field["name"]
        if name in SKIP_FIELDS:
            continue
        field_type = _unwrap(field["type"])
        path = f"{prefix}.{name}" if prefix else name

        if field_type in FLATTENABLE_TYPES and field_type in fields_by_type:
            rows.extend(_flatten(fields_by_type, field_type, path, owner_label, supported, depth + 1))
            continue

        if name == "metafields":
            note = "Use the separate Update Metafields tab for this"
        elif field_type in COMPOSITE_NOTES:
            note = COMPOSITE_NOTES[field_type]
        elif field_type in COMPLEX_TYPES:
            note = "Complex — needs a GID, list, or structured object, not plain text"
        else:
            note = ""

        rows.append({
            "Owner": owner_label,
            "GraphQL Path": path,
            "Type": field_type,
            "Supported in this app": "Yes" if path in supported else "No",
            "Notes": note,
        })
    return rows


def fetch_native_field_schema(headers, store_url, http_post=None):
    """Return (rows, error).

    rows is a list of dicts keyed by SCHEMA_COLUMNS, product fields first then
    variant fields — every field Shopify's ProductInput / ProductVariantsBulkInput
    actually accepts, cross-checked against what native_update.py maps today.
    error is None on success, or a message to show the user.
    """
    from native_update import NATIVE_PRODUCT_FIELDS, NATIVE_VARIANT_FIELDS

    post = http_post or requests.post
    url = f"https://{store_url}/admin/api/{API_VER}/graphql.json"

    try:
        resp = post(url, headers=headers, json={"query": SCHEMA_QUERY}, timeout=60)
    except Exception as exc:  # network error, DNS, timeout
        return [], f"Could not reach Shopify: {exc}"

    if resp.status_code != 200:
        return [], f"Shopify returned HTTP {resp.status_code}: {resp.text[:160]}"

    try:
        body = resp.json()
    except ValueError:
        return [], "Shopify returned a response that was not JSON"

    errors = body.get("errors") or []
    if errors:
        return [], str(errors[0].get("message", "GraphQL error"))[:200]

    payload = body.get("data") or {}
    if not payload:
        return [], "Shopify returned no schema data"

    fields_by_type = {}
    for index, type_name in enumerate(SCHEMA_TYPES):
        node = payload.get(f"t{index}") or {}
        fields_by_type[type_name] = node.get("inputFields") or []

    rows = (
        _flatten(fields_by_type, "ProductInput", "", "Product", set(NATIVE_PRODUCT_FIELDS.values()))
        + _flatten(fields_by_type, "ProductVariantsBulkInput", "", "Variant", set(NATIVE_VARIANT_FIELDS.values()))
    )
    if not rows:
        return [], "Shopify's schema returned no fields for ProductInput or ProductVariantsBulkInput"

    return rows, None
