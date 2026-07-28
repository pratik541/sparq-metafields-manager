"""Native Shopify field bulk update — pure logic, no Streamlit or pandas.

Companion to bulk_update.py, which handles metafields. This module handles
native product and variant fields via productVariantsBulkUpdate / productUpdate.
"""

from decimal import Decimal, InvalidOperation

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
