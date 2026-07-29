"""Native Shopify field bulk update — pure logic, no Streamlit or pandas.

Companion to bulk_update.py, which handles metafields. This module handles
native product and variant fields via productVariantsBulkUpdate / productUpdate.
"""

from decimal import Decimal, InvalidOperation
import time

import requests

API_VER = "2025-01"

# Aliased mutations packed into a single HTTP request. Each productVariantsBulkUpdate
# costs roughly 10 points against the 1000-point GraphQL bucket, so 10 per request
# leaves headroom for the throttle retry to recover.
NATIVE_BATCH_SIZE = 10

# CSV column -> GraphQL field path. Paths containing "." are nested inputs.
NATIVE_VARIANT_FIELDS = {
    "Variant Price":             "price",
    "Variant Compare At Price":  "compareAtPrice",
    "Variant Barcode":           "barcode",
    "Variant Taxable":           "taxable",
    "Variant Tax Code":          "taxCode",
    "Variant Inventory Policy":  "inventoryPolicy",
    "Cost per item":             "inventoryItem.cost",
    "Variant Grams":             "inventoryItem.measurement.weight",
    "Variant Requires Shipping": "inventoryItem.requiresShipping",
    "Variant Inventory Tracker": "inventoryItem.tracked",
}

NATIVE_PRODUCT_FIELDS = {
    "Title":           "title",
    "Body (HTML)":     "descriptionHtml",
    "Vendor":          "vendor",
    "Type":            "productType",
    "Tags":            "tags",
    "Status":          "status",
    "SEO Title":       "seo.title",
    "SEO Description": "seo.description",
}

# Blank means "skip", so clearing a field needs an explicit sentinel.
CLEARABLE_COLUMNS = {"Variant Compare At Price", "Variant Barcode"}

MONEY_COLUMNS = {"Variant Price", "Variant Compare At Price", "Cost per item"}
BOOL_COLUMNS  = {"Variant Taxable", "Variant Requires Shipping"}

INVENTORY_POLICIES = ("DENY", "CONTINUE")
PRODUCT_STATUSES   = ("ACTIVE", "DRAFT", "ARCHIVED")

_TRUE_WORDS    = ("true", "1", "yes")
_FALSE_WORDS   = ("false", "0", "no")
_TRACKED_TRUE  = ("shopify", "true", "1", "yes", "tracked")
_TRACKED_FALSE = ("false", "0", "no", "untracked")

_BLANK_WORDS = ("", "nan", "none")


def is_blank(raw):
    """True when a CSV cell carries no instruction and must be left untouched."""
    if raw is None:
        return True
    if isinstance(raw, float) and raw != raw:  # NaN
        return True
    return str(raw).strip().lower() in _BLANK_WORDS


def coerce_native_value(column, raw):
    """Convert a CSV cell to a GraphQL-ready value.

    Returns (value, None) on success, or (None, error_message) on failure.
    A successful return where value is None means "send JSON null" (CLEAR).
    Callers must check is_blank() first — this function assumes a real value.
    """
    text = str(raw).strip()

    if text.upper() == "CLEAR":
        if column in CLEARABLE_COLUMNS:
            return None, None
        return None, f"CLEAR is not supported for '{column}' — only {sorted(CLEARABLE_COLUMNS)}"

    if column in MONEY_COLUMNS:
        cleaned = text.replace("₹", "").replace(",", "").replace(" ", "")
        try:
            amount = Decimal(cleaned)
        except InvalidOperation:
            return None, f"'{text}' is not a valid amount"
        if not amount.is_finite():
            return None, f"'{text}' is not a valid amount"
        if amount < 0:
            return None, f"'{text}' is negative — amounts must be zero or more"
        return cleaned, None

    if column in BOOL_COLUMNS:
        low = text.lower()
        if low in _TRUE_WORDS:
            return True, None
        if low in _FALSE_WORDS:
            return False, None
        return None, f"'{text}' is not a valid true/false value"

    if column == "Variant Inventory Policy":
        upper = text.upper()
        if upper not in INVENTORY_POLICIES:
            return None, f"'{text}' must be one of {list(INVENTORY_POLICIES)}"
        return upper, None

    if column == "Status":
        upper = text.upper()
        if upper not in PRODUCT_STATUSES:
            return None, f"'{text}' must be one of {list(PRODUCT_STATUSES)}"
        return upper, None

    if column == "Variant Grams":
        try:
            grams = Decimal(text.replace(",", "").replace(" ", ""))
        except InvalidOperation:
            return None, f"'{text}' is not a valid weight in grams"
        if not grams.is_finite():
            return None, f"'{text}' is not a valid weight in grams"
        if grams < 0:
            return None, f"'{text}' is negative — weight must be zero or more"
        # Variant Weight Unit is deliberately ignored: the Shopify export writes
        # this column in grams regardless of the display unit.
        return {"value": float(grams), "unit": "GRAMS"}, None

    if column == "Variant Inventory Tracker":
        low = text.lower()
        if low in _TRACKED_TRUE:
            return True, None
        if low in _TRACKED_FALSE:
            return False, None
        return None, f"'{text}' is not a valid inventory tracker value"

    if column == "Tags":
        return [part.strip() for part in text.split(",") if part.strip()], None

    return text, None


def _assign_nested(target, path, value):
    """Place value at a dotted path inside target, creating intermediate dicts."""
    parts = path.split(".")
    cursor = target
    for part in parts[:-1]:
        cursor = cursor.setdefault(part, {})
    cursor[parts[-1]] = value


def _build_input(row, gid, field_map):
    """Shared builder for variant and product inputs.

    Returns (input_dict_or_None, errors). Only columns that are present in the
    row AND non-blank AND coerce cleanly appear in the result.
    """
    result = {"id": gid}
    errors = []

    for column, path in field_map.items():
        if column not in row:
            continue
        raw = row[column]
        if is_blank(raw):
            continue
        value, error = coerce_native_value(column, raw)
        if error:
            errors.append(f"{column}: {error}")
            continue
        _assign_nested(result, path, value)

    if len(result) == 1:  # only "id" — nothing to update
        return None, errors
    return result, errors


def build_variant_input(row, variant_gid):
    """Build a ProductVariantsBulkInput dict for one CSV row."""
    return _build_input(row, variant_gid, NATIVE_VARIANT_FIELDS)


def build_product_input(row, product_gid):
    """Build a ProductInput dict for one CSV row."""
    return _build_input(row, product_gid, NATIVE_PRODUCT_FIELDS)


def chunk(items, size):
    """Split items into fixed-size lists."""
    if size <= 0:
        raise ValueError("size must be greater than zero")
    return [items[index:index + size] for index in range(0, len(items), size)]


def group_by_product(resolved):
    """Group resolved variant rows by parent product, preserving input order."""
    groups, order = {}, []
    for item in resolved:
        product_gid = item["product_gid"]
        if product_gid not in groups:
            groups[product_gid] = {
                "product_gid": product_gid, "variants": [], "metas": [],
            }
            order.append(product_gid)
        groups[product_gid]["variants"].append(item["variant_input"])
        groups[product_gid]["metas"].append(item["meta"])
    return [groups[product_gid] for product_gid in order]


def build_aliased_variant_mutation(groups):
    """Build one aliased productVariantsBulkUpdate mutation per product group."""
    definitions, selections, variables = [], [], {}
    for index, group in enumerate(groups):
        definitions.extend((f"$p{index}: ID!", f"$v{index}: [ProductVariantsBulkInput!]!"))
        variables[f"p{index}"] = group["product_gid"]
        variables[f"v{index}"] = group["variants"]
        selections.append(
            f"  m{index}: productVariantsBulkUpdate(productId: $p{index}, variants: $v{index}) {{\n"
            "    productVariants { id }\n"
            "    userErrors { field message }\n"
            "  }"
        )
    return "mutation NativeVariantBulk(" + ", ".join(definitions) + ") {\n" + "\n".join(selections) + "\n}", variables


def build_aliased_product_mutation(inputs):
    """Build one aliased productUpdate mutation per ProductInput."""
    definitions, selections, variables = [], [], {}
    for index, product_input in enumerate(inputs):
        definitions.append(f"$i{index}: ProductInput!")
        variables[f"i{index}"] = product_input
        selections.append(
            f"  m{index}: productUpdate(input: $i{index}) {{\n"
            "    product { id }\n"
            "    userErrors { field message }\n"
            "  }"
        )
    return "mutation NativeProductBulk(" + ", ".join(definitions) + ") {\n" + "\n".join(selections) + "\n}", variables


MAX_ATTEMPTS = 3


def _fail_all(alias_metas, reason):
    return [dict(meta, Error=reason) for metas in alias_metas for meta in metas]


def send_native_batch(headers, gql_url, query, variables, alias_metas, http_post=None, sleep=None):
    """Send an aliased mutation, retrying throttles and attributing errors to rows."""
    post, pause = http_post or requests.post, sleep or time.sleep
    for _attempt in range(MAX_ATTEMPTS):
        response = post(gql_url, headers=headers, json={"query": query, "variables": variables}, timeout=60)
        if response.status_code == 429:
            pause(3)
            continue
        if response.status_code != 200:
            return [], _fail_all(alias_metas, f"HTTP {response.status_code}: {response.text[:120]}")

        data = response.json()
        errors = data.get("errors") or []
        throttled = [error for error in errors if error.get("extensions", {}).get("code") == "THROTTLED"]
        if throttled:
            pause(float(throttled[0].get("extensions", {}).get("retryAfter", 2)) + 0.5)
            continue
        if errors:
            return [], _fail_all(alias_metas, str(errors[0].get("message", "GraphQL error"))[:160])

        successes, failures = [], []
        for index, metas in enumerate(alias_metas):
            result = (data.get("data") or {}).get(f"m{index}")
            if not result:
                failures.extend(dict(meta, Error="Shopify returned no response for this product") for meta in metas)
            elif result.get("userErrors"):
                reason = "; ".join(
                    f"{error.get('field') or 'error'}: {error.get('message', '')}"
                    for error in result["userErrors"]
                )[:200]
                failures.extend(dict(meta, Error=reason) for meta in metas)
            else:
                successes.extend(metas)
        return successes, failures
    return [], _fail_all(alias_metas, f"Rate limited — gave up after {MAX_ATTEMPTS} attempts")


VARIANT_CACHE_KEYS = {
    "Variant Price": "price", "Variant Compare At Price": "compare_at_price",
    "Variant Barcode": "barcode", "Variant Taxable": "taxable",
    "Variant Inventory Policy": "inventory_policy", "Variant Grams": "grams",
    "Variant Requires Shipping": "requires_shipping",
    "Variant Inventory Tracker": "inventory_management",
}
PRODUCT_CACHE_KEYS = {
    "Title": "title", "Body (HTML)": "body_html", "Vendor": "vendor",
    "Type": "product_type", "Tags": "tags", "Status": "status",
}
UNKNOWN_CURRENT = {"Cost per item", "Variant Tax Code", "SEO Title", "SEO Description"}
UNKNOWN, CLEARED = "unknown", "(cleared)"


def current_value(column, variant, product):
    """Read a display value from the REST product cache, or report unknown."""
    if column in UNKNOWN_CURRENT:
        return UNKNOWN
    if column in VARIANT_CACHE_KEYS:
        return str((variant or {}).get(VARIANT_CACHE_KEYS[column], ""))
    if column in PRODUCT_CACHE_KEYS:
        return str((product or {}).get(PRODUCT_CACHE_KEYS[column], ""))
    return UNKNOWN


def _comparable(value):
    return str(value).strip().lower().replace("â‚¹", "").replace(",", "").replace(" ", "")


def _display_new(value):
    if value is None:
        return CLEARED
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return ", ".join(value)
    if isinstance(value, dict):
        return f"{value.get('value')} {value.get('unit', '').lower()}".strip()
    return str(value)


def diff_row(row, variant, product):
    """Return one dry-run diff record for each supplied native field."""
    records = []
    for column in list(NATIVE_VARIANT_FIELDS) + list(NATIVE_PRODUCT_FIELDS):
        if column not in row or is_blank(row[column]):
            continue
        value, error = coerce_native_value(column, row[column])
        present = current_value(column, variant, product)
        if error:
            records.append({"Field": column, "Current": present, "New": f"ERROR — {error}", "Changed": False})
            continue
        shown = _display_new(value)
        changed = present == UNKNOWN or (value is None and _comparable(present) != "") or (value is not None and _comparable(present) != _comparable(shown))
        records.append({"Field": column, "Current": present, "New": shown, "Changed": changed})
    return records


KEY_COLUMNS = ("Variant SKU", "Handle")


def recognised_native_columns(columns):
    """Return known native update columns present in an upload, in mapping order."""
    return [column for column in list(NATIVE_VARIANT_FIELDS) + list(NATIVE_PRODUCT_FIELDS) if column in columns]


def build_lookup_index(products):
    """Build O(1) SKU and handle maps while retaining cache values for diffing."""
    sku_map, handle_map = {}, {}
    for product in products:
        product_gid = f"gid://shopify/Product/{product['id']}"
        variants = product.get("variants") or []
        first_variant = variants[0] if variants else {}
        handle = str(product.get("handle", "")).strip()
        if handle:
            handle_map[handle] = {"product_gid": product_gid, "product": product, "variant": first_variant}
        for variant in variants:
            sku = str(variant.get("sku", "")).strip()
            if sku:
                sku_map[sku] = {"variant_gid": f"gid://shopify/ProductVariant/{variant['id']}", "product_gid": product_gid, "variant": variant, "product": product}
    return sku_map, handle_map


def _row_meta(row, product):
    return {"Variant SKU": str(row.get("Variant SKU", "") or "").strip(), "Handle": str(row.get("Handle", "") or "").strip(), "Product": str((product or {}).get("title", ""))[:60]}


def resolve_rows(rows, sku_map, handle_map):
    """Resolve each CSV row and bucket it as updates, skipped, not-found, or error."""
    output = {key: [] for key in ("variant_updates", "product_updates", "diff_records", "skipped", "notfound", "errors")}
    for row in rows:
        sku, handle = str(row.get("Variant SKU", "") or "").strip(), str(row.get("Handle", "") or "").strip()
        target = sku_map.get(sku) if sku and sku.lower() not in _BLANK_WORDS else None
        if target is None and handle and handle.lower() not in _BLANK_WORDS:
            target = handle_map.get(handle)
        if target is None:
            output["notfound"].append({**_row_meta(row, None), "Reason": "SKU/handle not in store"})
            continue
        product, variant, meta = target["product"], target["variant"], _row_meta(row, target["product"])
        variant_gid = target.get("variant_gid") or (f"gid://shopify/ProductVariant/{variant['id']}" if variant else None)
        variant_input, variant_errors = build_variant_input(row, variant_gid) if variant_gid else (None, [])
        product_input, product_errors = build_product_input(row, target["product_gid"])
        if variant_errors or product_errors:
            output["errors"].append({**meta, "Error": "; ".join(variant_errors + product_errors)[:250]})
            continue
        if variant_input is None and product_input is None:
            output["skipped"].append({**meta, "Reason": "no updatable native fields in row"})
            continue
        if variant_input:
            output["variant_updates"].append({"product_gid": target["product_gid"], "variant_input": variant_input, "meta": meta})
        if product_input:
            output["product_updates"].append({"product_gid": target["product_gid"], "product_input": product_input, "meta": meta})
        output["diff_records"].extend({**meta, **record} for record in diff_row(row, variant, product))
    return output
