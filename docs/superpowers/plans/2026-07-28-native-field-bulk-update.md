# Native Field Bulk Update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a 6th Streamlit tab that bulk-updates native Shopify product and variant fields (price, compare-at, barcode, cost, weight, title, tags, status) from a CSV, with a dry-run diff gate before anything is written.

**Architecture:** All mutation logic goes in a new pure-Python module `native_update.py` with no Streamlit and no pandas imports, so it is unit-testable. `app.py` gains a thin tab 6 that uploads, validates, shows a diff, applies, and reports. Variant writes use `productVariantsBulkUpdate` (which is per-product), product writes use `productUpdate`; because this catalog is mostly single-variant, N mutations are packed into one HTTP request using GraphQL alias syntax to avoid ~40,000 round trips.

**Tech Stack:** Python 3.14, Streamlit, pandas, requests, pytest 8.3.3. Shopify Admin GraphQL API version 2025-01.

## Global Constraints

- Shopify Admin API version is **2025-01** everywhere — matches `app.py:1314`. Do not bump it.
- `native_update.py` must not import `streamlit` or `pandas`. Rows arrive as plain dicts.
- A blank / `NaN` / `"nan"` / `"none"` cell means **leave the field untouched**. Never send an empty value.
- A column absent from the uploaded CSV means that field is **never touched**.
- The literal value `CLEAR` sends JSON `null`, and is accepted **only** for `Variant Compare At Price` and `Variant Barcode`.
- `Variant Grams` is always grams. `Variant Weight Unit` is ignored — reinterpreting grams as the display unit would be a 1000x error.
- Nothing is sent to Shopify until the user presses **Apply** on a separate button, after seeing the diff.
- Progress is reported **per batch, never per row** — per-row Streamlit updates caused the 40k-row hang fixed in commit `4d30621`.
- `NATIVE_BATCH_SIZE = 10` aliased mutations per HTTP request.
- Rate-limit handling matches `app.py:1332-1364`: HTTP 429 → sleep 3s; GraphQL `THROTTLED` → sleep `retryAfter + 0.5`; 3 attempts then the batch is recorded failed.
- Out of scope: inventory quantity, SKU rewriting, images, option values, Display Price metafield sync.

---

### Task 1: Value coercion primitives

**Files:**
- Create: `native_update.py`
- Create: `tests/__init__.py` (empty)
- Create: `tests/test_native_update.py`
- Modify: `requirements.txt`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `is_blank(raw) -> bool`
  - `coerce_native_value(column: str, raw) -> tuple[value, str | None]` — returns `(value, None)` on success or `(None, error_message)` on failure. A successful return of `value is None` means "send JSON null" (the `CLEAR` sentinel).
  - Constants `NATIVE_VARIANT_FIELDS`, `NATIVE_PRODUCT_FIELDS`, `CLEARABLE_COLUMNS`, `MONEY_COLUMNS`, `BOOL_COLUMNS`, `INVENTORY_POLICIES`, `PRODUCT_STATUSES`, `NATIVE_BATCH_SIZE`

- [ ] **Step 1: Add pytest to requirements.txt**

Append one line so the test tooling is declared (pytest 8.3.3 is already installed locally):

```
requests
pandas
openpyxl
streamlit
pytest
```

- [ ] **Step 2: Write the failing tests**

Create `tests/__init__.py` as an empty file, then create `tests/test_native_update.py`:

```python
import math

import pytest

from native_update import (
    coerce_native_value,
    is_blank,
)


class TestIsBlank:
    @pytest.mark.parametrize("raw", [None, "", "   ", "nan", "NaN", "none", "None", float("nan")])
    def test_blank_values(self, raw):
        assert is_blank(raw) is True

    @pytest.mark.parametrize("raw", ["0", 0, "false", "abc", 287093.0, " x "])
    def test_non_blank_values(self, raw):
        assert is_blank(raw) is False


class TestMoneyCoercion:
    def test_plain_number(self):
        assert coerce_native_value("Variant Price", "1999") == ("1999", None)

    def test_strips_rupee_symbol_and_commas(self):
        assert coerce_native_value("Variant Price", "₹ 287,093.00") == ("287093.00", None)

    def test_decimal_preserved(self):
        assert coerce_native_value("Cost per item", "12.50") == ("12.50", None)

    def test_float_input_from_pandas(self):
        value, error = coerce_native_value("Variant Price", 1999.0)
        assert error is None
        assert value == "1999.0"

    def test_invalid_amount_is_an_error(self):
        value, error = coerce_native_value("Variant Price", "abc")
        assert value is None
        assert "not a valid amount" in error

    def test_negative_amount_is_an_error(self):
        value, error = coerce_native_value("Variant Price", "-5")
        assert value is None
        assert "negative" in error


class TestClearSentinel:
    def test_clear_on_compare_at_returns_none_without_error(self):
        assert coerce_native_value("Variant Compare At Price", "CLEAR") == (None, None)

    def test_clear_is_case_insensitive(self):
        assert coerce_native_value("Variant Barcode", "clear") == (None, None)

    def test_clear_rejected_on_price(self):
        value, error = coerce_native_value("Variant Price", "CLEAR")
        assert value is None
        assert "CLEAR is not supported" in error


class TestBooleanCoercion:
    @pytest.mark.parametrize("raw", ["TRUE", "true", "1", "yes", "Yes"])
    def test_truthy(self, raw):
        assert coerce_native_value("Variant Taxable", raw) == (True, None)

    @pytest.mark.parametrize("raw", ["FALSE", "false", "0", "no"])
    def test_falsy(self, raw):
        assert coerce_native_value("Variant Requires Shipping", raw) == (False, None)

    def test_unrecognised_boolean_is_an_error(self):
        value, error = coerce_native_value("Variant Taxable", "maybe")
        assert value is None
        assert "not a valid true/false" in error


class TestEnumCoercion:
    def test_inventory_policy_uppercased(self):
        assert coerce_native_value("Variant Inventory Policy", "deny") == ("DENY", None)

    def test_invalid_inventory_policy(self):
        value, error = coerce_native_value("Variant Inventory Policy", "whatever")
        assert value is None
        assert "DENY" in error

    def test_status_uppercased(self):
        assert coerce_native_value("Status", "active") == ("ACTIVE", None)

    def test_invalid_status(self):
        value, error = coerce_native_value("Status", "live")
        assert value is None
        assert "ACTIVE" in error


class TestWeightCoercion:
    def test_grams_always_sent_as_grams(self):
        value, error = coerce_native_value("Variant Grams", "1000")
        assert error is None
        assert value == {"value": 1000.0, "unit": "GRAMS"}

    def test_grams_strips_commas(self):
        value, _ = coerce_native_value("Variant Grams", "1,250.5")
        assert math.isclose(value["value"], 1250.5)

    def test_invalid_weight_is_an_error(self):
        value, error = coerce_native_value("Variant Grams", "heavy")
        assert value is None
        assert "not a valid weight" in error


class TestTrackerCoercion:
    @pytest.mark.parametrize("raw", ["shopify", "SHOPIFY", "true", "1", "yes", "tracked"])
    def test_tracked_true(self, raw):
        assert coerce_native_value("Variant Inventory Tracker", raw) == (True, None)

    @pytest.mark.parametrize("raw", ["false", "0", "no", "untracked"])
    def test_tracked_false(self, raw):
        assert coerce_native_value("Variant Inventory Tracker", raw) == (False, None)

    def test_unrecognised_tracker_is_an_error(self):
        value, error = coerce_native_value("Variant Inventory Tracker", "somethingelse")
        assert value is None
        assert "not a valid inventory tracker" in error


class TestTagsCoercion:
    def test_tags_split_on_commas_and_trimmed(self):
        assert coerce_native_value("Tags", "gold, diamond ,  ring") == (
            ["gold", "diamond", "ring"],
            None,
        )

    def test_empty_fragments_dropped(self):
        assert coerce_native_value("Tags", "gold,,ring,") == (["gold", "ring"], None)


class TestPassthrough:
    def test_plain_text_trimmed(self):
        assert coerce_native_value("Title", "  Gold Earrings  ") == ("Gold Earrings", None)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m pytest tests/test_native_update.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'native_update'`

- [ ] **Step 4: Write the implementation**

Create `native_update.py`:

```python
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
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_native_update.py -q`
Expected: PASS, all tests green

- [ ] **Step 6: Commit**

```bash
git add requirements.txt native_update.py tests/__init__.py tests/test_native_update.py
git commit -m "feat: add native field value coercion for bulk update"
```

---

### Task 2: Build GraphQL input dicts from CSV rows

**Files:**
- Modify: `native_update.py`
- Modify: `tests/test_native_update.py`

**Interfaces:**
- Consumes: `is_blank`, `coerce_native_value`, `NATIVE_VARIANT_FIELDS`, `NATIVE_PRODUCT_FIELDS` from Task 1
- Produces:
  - `build_variant_input(row: dict, variant_gid: str) -> tuple[dict | None, list[str]]` — the dict always contains `id`; returns `None` when no field was set. Second element is a list of per-column error strings.
  - `build_product_input(row: dict, product_gid: str) -> tuple[dict | None, list[str]]` — same contract.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_native_update.py`:

```python
from native_update import build_product_input, build_variant_input

VARIANT_GID = "gid://shopify/ProductVariant/111"
PRODUCT_GID = "gid://shopify/Product/222"


class TestBuildVariantInput:
    def test_price_only(self):
        result, errors = build_variant_input({"Variant Price": "1999"}, VARIANT_GID)
        assert errors == []
        assert result == {"id": VARIANT_GID, "price": "1999"}

    def test_absent_column_never_sent(self):
        result, _ = build_variant_input({"Variant Price": "1999"}, VARIANT_GID)
        assert "compareAtPrice" not in result
        assert "inventoryItem" not in result

    def test_blank_cell_never_sent(self):
        row = {"Variant Price": "1999", "Variant Compare At Price": "", "Variant Barcode": float("nan")}
        result, errors = build_variant_input(row, VARIANT_GID)
        assert errors == []
        assert result == {"id": VARIANT_GID, "price": "1999"}

    def test_clear_sends_explicit_null(self):
        result, errors = build_variant_input({"Variant Compare At Price": "CLEAR"}, VARIANT_GID)
        assert errors == []
        assert result == {"id": VARIANT_GID, "compareAtPrice": None}

    def test_inventory_item_fields_nested(self):
        row = {"Cost per item": "500", "Variant Requires Shipping": "TRUE", "Variant Inventory Tracker": "shopify"}
        result, errors = build_variant_input(row, VARIANT_GID)
        assert errors == []
        assert result["inventoryItem"] == {
            "cost": "500",
            "requiresShipping": True,
            "tracked": True,
        }

    def test_weight_nested_under_measurement(self):
        result, errors = build_variant_input({"Variant Grams": "1000"}, VARIANT_GID)
        assert errors == []
        assert result["inventoryItem"] == {"measurement": {"weight": {"value": 1000.0, "unit": "GRAMS"}}}

    def test_weight_and_cost_coexist(self):
        result, _ = build_variant_input({"Variant Grams": "50", "Cost per item": "10"}, VARIANT_GID)
        assert result["inventoryItem"]["cost"] == "10"
        assert result["inventoryItem"]["measurement"]["weight"]["value"] == 50.0

    def test_weight_unit_column_is_ignored(self):
        row = {"Variant Grams": "1000", "Variant Weight Unit": "kg"}
        result, errors = build_variant_input(row, VARIANT_GID)
        assert errors == []
        assert result["inventoryItem"]["measurement"]["weight"] == {"value": 1000.0, "unit": "GRAMS"}

    def test_no_updatable_fields_returns_none(self):
        result, errors = build_variant_input({"Handle": "some-handle", "Variant SKU": "ABC"}, VARIANT_GID)
        assert result is None
        assert errors == []

    def test_bad_value_reported_and_other_fields_still_built(self):
        row = {"Variant Price": "abc", "Variant Barcode": "XYZ"}
        result, errors = build_variant_input(row, VARIANT_GID)
        assert result == {"id": VARIANT_GID, "barcode": "XYZ"}
        assert len(errors) == 1
        assert "Variant Price" in errors[0]


class TestBuildProductInput:
    def test_title_and_tags(self):
        row = {"Title": "Gold Earrings", "Tags": "gold, diamond"}
        result, errors = build_product_input(row, PRODUCT_GID)
        assert errors == []
        assert result == {"id": PRODUCT_GID, "title": "Gold Earrings", "tags": ["gold", "diamond"]}

    def test_seo_nested(self):
        row = {"SEO Title": "Buy Gold", "SEO Description": "Best gold"}
        result, errors = build_product_input(row, PRODUCT_GID)
        assert errors == []
        assert result == {"id": PRODUCT_GID, "seo": {"title": "Buy Gold", "description": "Best gold"}}

    def test_body_html_mapped_to_description_html(self):
        result, _ = build_product_input({"Body (HTML)": "<p>hi</p>"}, PRODUCT_GID)
        assert result["descriptionHtml"] == "<p>hi</p>"

    def test_variant_columns_ignored_at_product_level(self):
        result, errors = build_product_input({"Variant Price": "1999"}, PRODUCT_GID)
        assert result is None
        assert errors == []

    def test_bad_status_reported(self):
        result, errors = build_product_input({"Status": "live"}, PRODUCT_GID)
        assert result is None
        assert len(errors) == 1
        assert "Status" in errors[0]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_native_update.py -q`
Expected: FAIL — `ImportError: cannot import name 'build_variant_input'`

- [ ] **Step 3: Write the implementation**

Append to `native_update.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_native_update.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add native_update.py tests/test_native_update.py
git commit -m "feat: build variant and product GraphQL inputs from CSV rows"
```

---

### Task 3: Group rows by product and build aliased mutations

**Files:**
- Modify: `native_update.py`
- Modify: `tests/test_native_update.py`

**Interfaces:**
- Consumes: `NATIVE_BATCH_SIZE` from Task 1
- Produces:
  - `group_by_product(resolved: list[dict]) -> list[dict]` — each input item is `{"product_gid": str, "variant_input": dict, "meta": dict}`; each output group is `{"product_gid": str, "variants": list[dict], "metas": list[dict]}`. Input order is preserved.
  - `chunk(items: list, size: int) -> list[list]`
  - `build_aliased_variant_mutation(groups) -> tuple[str, dict]`
  - `build_aliased_product_mutation(inputs, metas) -> tuple[str, dict]` where `inputs` is a list of ProductInput dicts
  - Alias naming is always `m0`, `m1`, … matching list index — Task 4 relies on this.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_native_update.py`:

```python
from native_update import (
    build_aliased_product_mutation,
    build_aliased_variant_mutation,
    chunk,
    group_by_product,
)


class TestChunk:
    def test_splits_evenly(self):
        assert chunk([1, 2, 3, 4], 2) == [[1, 2], [3, 4]]

    def test_last_chunk_partial(self):
        assert chunk([1, 2, 3], 2) == [[1, 2], [3]]

    def test_empty_list(self):
        assert chunk([], 10) == []


class TestGroupByProduct:
    def test_single_variant_products_become_one_group_each(self):
        resolved = [
            {"product_gid": "gid://shopify/Product/1", "variant_input": {"id": "v1"}, "meta": {"SKU": "A"}},
            {"product_gid": "gid://shopify/Product/2", "variant_input": {"id": "v2"}, "meta": {"SKU": "B"}},
        ]
        groups = group_by_product(resolved)
        assert len(groups) == 2
        assert groups[0]["product_gid"] == "gid://shopify/Product/1"
        assert groups[0]["variants"] == [{"id": "v1"}]
        assert groups[0]["metas"] == [{"SKU": "A"}]

    def test_variants_of_same_product_merged(self):
        resolved = [
            {"product_gid": "gid://shopify/Product/1", "variant_input": {"id": "v1"}, "meta": {"SKU": "A"}},
            {"product_gid": "gid://shopify/Product/1", "variant_input": {"id": "v2"}, "meta": {"SKU": "B"}},
        ]
        groups = group_by_product(resolved)
        assert len(groups) == 1
        assert groups[0]["variants"] == [{"id": "v1"}, {"id": "v2"}]
        assert groups[0]["metas"] == [{"SKU": "A"}, {"SKU": "B"}]

    def test_input_order_preserved(self):
        resolved = [
            {"product_gid": "p2", "variant_input": {"id": "v1"}, "meta": {}},
            {"product_gid": "p1", "variant_input": {"id": "v2"}, "meta": {}},
        ]
        assert [g["product_gid"] for g in group_by_product(resolved)] == ["p2", "p1"]


class TestAliasedVariantMutation:
    def test_one_alias_per_group(self):
        groups = [
            {"product_gid": "p0", "variants": [{"id": "v0", "price": "10"}], "metas": [{}]},
            {"product_gid": "p1", "variants": [{"id": "v1", "price": "20"}], "metas": [{}]},
        ]
        query, variables = build_aliased_variant_mutation(groups)
        assert "m0: productVariantsBulkUpdate(productId: $p0, variants: $v0)" in query
        assert "m1: productVariantsBulkUpdate(productId: $p1, variants: $v1)" in query
        assert "$p0: ID!" in query
        assert "$v0: [ProductVariantsBulkInput!]!" in query
        assert variables == {
            "p0": "p0", "v0": [{"id": "v0", "price": "10"}],
            "p1": "p1", "v1": [{"id": "v1", "price": "20"}],
        }

    def test_requests_user_errors(self):
        groups = [{"product_gid": "p0", "variants": [{"id": "v0"}], "metas": [{}]}]
        query, _ = build_aliased_variant_mutation(groups)
        assert "userErrors" in query
        assert "productVariants" in query


class TestAliasedProductMutation:
    def test_one_alias_per_input(self):
        inputs = [{"id": "p0", "title": "A"}, {"id": "p1", "title": "B"}]
        query, variables = build_aliased_product_mutation(inputs)
        assert "m0: productUpdate(input: $i0)" in query
        assert "m1: productUpdate(input: $i1)" in query
        assert "$i0: ProductInput!" in query
        assert variables == {"i0": {"id": "p0", "title": "A"}, "i1": {"id": "p1", "title": "B"}}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_native_update.py -q`
Expected: FAIL — `ImportError: cannot import name 'group_by_product'`

- [ ] **Step 3: Write the implementation**

Append to `native_update.py`:

```python
def chunk(items, size):
    """Split a list into fixed-size lists."""
    return [items[i:i + size] for i in range(0, len(items), size)]


def group_by_product(resolved):
    """Group resolved variant rows by parent product, preserving input order.

    productVariantsBulkUpdate takes one productId and a list of that product's
    variants, so rows must be grouped before they can be sent.
    """
    groups = {}
    order = []
    for item in resolved:
        gid = item["product_gid"]
        if gid not in groups:
            groups[gid] = {"product_gid": gid, "variants": [], "metas": []}
            order.append(gid)
        groups[gid]["variants"].append(item["variant_input"])
        groups[gid]["metas"].append(item["meta"])
    return [groups[gid] for gid in order]


def build_aliased_variant_mutation(groups):
    """Pack several productVariantsBulkUpdate calls into one GraphQL document.

    This catalog is mostly single-variant, so one mutation per product would mean
    one HTTP request per product. Aliasing collapses NATIVE_BATCH_SIZE products
    into a single request. Alias names are m0..mN matching the group index, which
    is how send_native_batch attributes userErrors back to rows.
    """
    var_defs = []
    selections = []
    variables = {}
    for i, group in enumerate(groups):
        var_defs.append(f"$p{i}: ID!")
        var_defs.append(f"$v{i}: [ProductVariantsBulkInput!]!")
        variables[f"p{i}"] = group["product_gid"]
        variables[f"v{i}"] = group["variants"]
        selections.append(
            f"  m{i}: productVariantsBulkUpdate(productId: $p{i}, variants: $v{i}) {{\n"
            f"    productVariants {{ id }}\n"
            f"    userErrors {{ field message }}\n"
            f"  }}"
        )
    query = (
        "mutation NativeVariantBulk(" + ", ".join(var_defs) + ") {\n"
        + "\n".join(selections)
        + "\n}"
    )
    return query, variables


def build_aliased_product_mutation(inputs):
    """Pack several productUpdate calls into one GraphQL document.

    API version 2025-01 takes `input: ProductInput!`. Later versions renamed this
    to `product: ProductUpdateInput!` — do not bump the version without changing
    this signature.
    """
    var_defs = []
    selections = []
    variables = {}
    for i, product_input in enumerate(inputs):
        var_defs.append(f"$i{i}: ProductInput!")
        variables[f"i{i}"] = product_input
        selections.append(
            f"  m{i}: productUpdate(input: $i{i}) {{\n"
            f"    product {{ id }}\n"
            f"    userErrors {{ field message }}\n"
            f"  }}"
        )
    query = (
        "mutation NativeProductBulk(" + ", ".join(var_defs) + ") {\n"
        + "\n".join(selections)
        + "\n}"
    )
    return query, variables
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_native_update.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add native_update.py tests/test_native_update.py
git commit -m "feat: group rows by product and build aliased GraphQL mutations"
```

---

### Task 4: Send a batch with throttle retry and per-row error attribution

**Files:**
- Modify: `native_update.py`
- Modify: `tests/test_native_update.py`

**Interfaces:**
- Consumes: alias naming convention `m0..mN` from Task 3
- Produces:
  - `send_native_batch(headers: dict, gql_url: str, query: str, variables: dict, alias_metas: list[list[dict]], http_post=None, sleep=None) -> tuple[list[dict], list[dict]]` — returns `(success_metas, failed_metas)`. Failed metas are copies of the input meta dicts with an added `"Error"` key. `alias_metas[i]` holds the meta dicts for alias `m{i}`. `http_post` and `sleep` are injection points for tests; they default to `requests.post` and `time.sleep`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_native_update.py`:

```python
from native_update import send_native_batch


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class FakePoster:
    """Returns queued responses in order and records how many calls happened."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, headers=None, json=None, timeout=None):
        self.calls.append({"url": url, "json": json})
        return self.responses.pop(0)


def make_sleep_spy():
    slept = []
    return slept, slept.append


HEADERS = {"X-Shopify-Access-Token": "tok"}
URL = "https://example.myshopify.com/admin/api/2025-01/graphql.json"


class TestSendNativeBatch:
    def test_all_success(self):
        poster = FakePoster([FakeResponse(payload={"data": {
            "m0": {"productVariants": [{"id": "v0"}], "userErrors": []},
            "m1": {"productVariants": [{"id": "v1"}], "userErrors": []},
        }})])
        alias_metas = [[{"SKU": "A"}], [{"SKU": "B"}]]
        ok, failed = send_native_batch(HEADERS, URL, "query", {}, alias_metas, http_post=poster)
        assert ok == [{"SKU": "A"}, {"SKU": "B"}]
        assert failed == []

    def test_user_error_attributed_to_correct_alias(self):
        poster = FakePoster([FakeResponse(payload={"data": {
            "m0": {"productVariants": [], "userErrors": [{"field": "price", "message": "Bad price"}]},
            "m1": {"productVariants": [{"id": "v1"}], "userErrors": []},
        }})])
        alias_metas = [[{"SKU": "A"}], [{"SKU": "B"}]]
        ok, failed = send_native_batch(HEADERS, URL, "query", {}, alias_metas, http_post=poster)
        assert ok == [{"SKU": "B"}]
        assert len(failed) == 1
        assert failed[0]["SKU"] == "A"
        assert "Bad price" in failed[0]["Error"]

    def test_multi_variant_group_all_metas_marked(self):
        poster = FakePoster([FakeResponse(payload={"data": {
            "m0": {"productVariants": [], "userErrors": [{"field": "price", "message": "Bad"}]},
        }})])
        alias_metas = [[{"SKU": "A"}, {"SKU": "B"}]]
        ok, failed = send_native_batch(HEADERS, URL, "query", {}, alias_metas, http_post=poster)
        assert ok == []
        assert [f["SKU"] for f in failed] == ["A", "B"]

    def test_http_429_retries_then_succeeds(self):
        poster = FakePoster([
            FakeResponse(status_code=429, text="rate limited"),
            FakeResponse(payload={"data": {"m0": {"productVariants": [{"id": "v0"}], "userErrors": []}}}),
        ])
        slept, sleep = make_sleep_spy()
        ok, failed = send_native_batch(HEADERS, URL, "q", {}, [[{"SKU": "A"}]], http_post=poster, sleep=sleep)
        assert ok == [{"SKU": "A"}]
        assert failed == []
        assert slept == [3]
        assert len(poster.calls) == 2

    def test_throttled_extension_retries_using_retry_after(self):
        poster = FakePoster([
            FakeResponse(payload={"errors": [{"extensions": {"code": "THROTTLED", "retryAfter": 1.5}}]}),
            FakeResponse(payload={"data": {"m0": {"productVariants": [{"id": "v0"}], "userErrors": []}}}),
        ])
        slept, sleep = make_sleep_spy()
        ok, _ = send_native_batch(HEADERS, URL, "q", {}, [[{"SKU": "A"}]], http_post=poster, sleep=sleep)
        assert ok == [{"SKU": "A"}]
        assert slept == [2.0]

    def test_gives_up_after_three_attempts(self):
        poster = FakePoster([FakeResponse(status_code=429, text="x") for _ in range(3)])
        slept, sleep = make_sleep_spy()
        ok, failed = send_native_batch(HEADERS, URL, "q", {}, [[{"SKU": "A"}]], http_post=poster, sleep=sleep)
        assert ok == []
        assert len(failed) == 1
        assert "3 attempts" in failed[0]["Error"]
        assert len(poster.calls) == 3

    def test_non_200_fails_whole_batch_without_retry(self):
        poster = FakePoster([FakeResponse(status_code=500, text="boom")])
        ok, failed = send_native_batch(HEADERS, URL, "q", {}, [[{"SKU": "A"}], [{"SKU": "B"}]], http_post=poster)
        assert ok == []
        assert len(failed) == 2
        assert "HTTP 500" in failed[0]["Error"]

    def test_top_level_graphql_error_fails_batch(self):
        poster = FakePoster([FakeResponse(payload={"errors": [{"message": "Field 'nope' doesn't exist"}]})])
        ok, failed = send_native_batch(HEADERS, URL, "q", {}, [[{"SKU": "A"}]], http_post=poster)
        assert ok == []
        assert "doesn't exist" in failed[0]["Error"]

    def test_missing_alias_in_response_is_a_failure(self):
        poster = FakePoster([FakeResponse(payload={"data": {"m0": None}})])
        ok, failed = send_native_batch(HEADERS, URL, "q", {}, [[{"SKU": "A"}]], http_post=poster)
        assert ok == []
        assert "no response" in failed[0]["Error"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_native_update.py -q`
Expected: FAIL — `ImportError: cannot import name 'send_native_batch'`

- [ ] **Step 3: Write the implementation**

Add `import time` and `import requests` to the top of `native_update.py` (after the `decimal` import), then append:

```python
MAX_ATTEMPTS = 3


def _fail_all(alias_metas, reason):
    """Mark every row in a batch failed with the same reason."""
    return [dict(meta, Error=reason) for metas in alias_metas for meta in metas]


def send_native_batch(headers, gql_url, query, variables, alias_metas,
                      http_post=None, sleep=None):
    """POST one aliased mutation document and attribute results back to rows.

    alias_metas[i] holds the meta dicts belonging to alias m{i}, so a userError
    on m2 is reported against exactly the rows that produced m2.

    Retry policy matches the metafield bulk path in app.py: HTTP 429 sleeps 3s,
    a GraphQL THROTTLED extension sleeps retryAfter + 0.5, up to MAX_ATTEMPTS.
    """
    post  = http_post or requests.post
    pause = sleep or time.sleep

    for attempt in range(MAX_ATTEMPTS):
        resp = post(gql_url, headers=headers,
                    json={"query": query, "variables": variables}, timeout=60)

        if resp.status_code == 429:
            pause(3)
            continue

        if resp.status_code != 200:
            return [], _fail_all(alias_metas, f"HTTP {resp.status_code}: {resp.text[:120]}")

        data   = resp.json()
        errors = data.get("errors") or []

        if errors and any(e.get("extensions", {}).get("code") == "THROTTLED" for e in errors):
            retry_after = float(errors[0].get("extensions", {}).get("retryAfter", 2))
            pause(retry_after + 0.5)
            continue

        if errors:
            return [], _fail_all(alias_metas, str(errors[0].get("message", "GraphQL error"))[:160])

        payload   = data.get("data") or {}
        successes = []
        failures  = []

        for i, metas in enumerate(alias_metas):
            result = payload.get(f"m{i}")
            if not result:
                failures.extend(dict(m, Error="Shopify returned no response for this product") for m in metas)
                continue
            user_errors = result.get("userErrors") or []
            if user_errors:
                reason = "; ".join(
                    f"{ue.get('field') or 'error'}: {ue.get('message', '')}" for ue in user_errors
                )[:200]
                failures.extend(dict(m, Error=reason) for m in metas)
            else:
                successes.extend(metas)

        return successes, failures

    return [], _fail_all(alias_metas, f"Rate limited — gave up after {MAX_ATTEMPTS} attempts")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_native_update.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add native_update.py tests/test_native_update.py
git commit -m "feat: send aliased native batches with throttle retry and per-row errors"
```

---

### Task 5: Dry-run diff against the cached product data

**Files:**
- Modify: `native_update.py`
- Modify: `tests/test_native_update.py`

**Interfaces:**
- Consumes: `NATIVE_VARIANT_FIELDS`, `NATIVE_PRODUCT_FIELDS`, `is_blank`, `coerce_native_value` from Tasks 1-2
- Produces:
  - `VARIANT_CACHE_KEYS`, `PRODUCT_CACHE_KEYS`, `UNKNOWN_CURRENT` constants
  - `current_value(column, variant: dict, product: dict) -> str` — returns the store's current value as a display string, or `"unknown"` for fields absent from the REST payload
  - `diff_row(row: dict, variant: dict, product: dict) -> list[dict]` — one record per column being written, each `{"Field", "Current", "New", "Changed"}`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_native_update.py`:

```python
from native_update import UNKNOWN_CURRENT, current_value, diff_row

VARIANT = {
    "price": "287093.00",
    "compare_at_price": "300000.00",
    "barcode": "",
    "taxable": True,
    "inventory_policy": "continue",
    "grams": 0,
    "requires_shipping": True,
    "inventory_management": "shopify",
}
PRODUCT = {
    "title": "Arias by Lara Dutta Brilliant Linear Diamond Earrings",
    "body_html": "<p>old</p>",
    "vendor": "Arias",
    "product_type": "Earrings",
    "tags": "gold, diamond",
    "status": "active",
}


class TestCurrentValue:
    def test_reads_variant_price(self):
        assert current_value("Variant Price", VARIANT, PRODUCT) == "287093.00"

    def test_reads_product_title(self):
        assert current_value("Title", VARIANT, PRODUCT) == PRODUCT["title"]

    def test_cost_is_unknown(self):
        assert current_value("Cost per item", VARIANT, PRODUCT) == "unknown"

    def test_tax_code_is_unknown(self):
        assert current_value("Variant Tax Code", VARIANT, PRODUCT) == "unknown"

    def test_seo_fields_are_unknown(self):
        assert current_value("SEO Title", VARIANT, PRODUCT) == "unknown"

    def test_unknown_set_matches(self):
        assert UNKNOWN_CURRENT == {
            "Cost per item",
            "Variant Tax Code",
            "SEO Title",
            "SEO Description",
        }


class TestDiffRow:
    def test_changed_price_flagged(self):
        records = diff_row({"Variant Price": "199999"}, VARIANT, PRODUCT)
        assert records == [{
            "Field": "Variant Price",
            "Current": "287093.00",
            "New": "199999",
            "Changed": True,
        }]

    def test_identical_price_not_flagged(self):
        records = diff_row({"Variant Price": "287093.00"}, VARIANT, PRODUCT)
        assert records[0]["Changed"] is False

    def test_money_formatting_ignored_when_comparing(self):
        records = diff_row({"Variant Price": "₹ 287,093.00"}, VARIANT, PRODUCT)
        assert records[0]["Changed"] is False

    def test_blank_cells_produce_no_records(self):
        assert diff_row({"Variant Price": "", "Title": float("nan")}, VARIANT, PRODUCT) == []

    def test_absent_columns_produce_no_records(self):
        assert diff_row({"Variant SKU": "ABC"}, VARIANT, PRODUCT) == []

    def test_unknown_current_always_counts_as_changed(self):
        records = diff_row({"Cost per item": "500"}, VARIANT, PRODUCT)
        assert records[0]["Current"] == "unknown"
        assert records[0]["Changed"] is True

    def test_clear_shows_as_clear(self):
        records = diff_row({"Variant Compare At Price": "CLEAR"}, VARIANT, PRODUCT)
        assert records[0]["New"] == "(cleared)"
        assert records[0]["Changed"] is True

    def test_bad_value_reported_as_error_record(self):
        records = diff_row({"Variant Price": "abc"}, VARIANT, PRODUCT)
        assert records[0]["New"].startswith("ERROR")
        assert records[0]["Changed"] is False

    def test_variant_and_product_fields_both_included(self):
        records = diff_row({"Variant Price": "1", "Title": "New Title"}, VARIANT, PRODUCT)
        fields = [r["Field"] for r in records]
        assert "Variant Price" in fields
        assert "Title" in fields
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_native_update.py -q`
Expected: FAIL — `ImportError: cannot import name 'current_value'`

- [ ] **Step 3: Write the implementation**

Append to `native_update.py`:

```python
# CSV column -> key in the REST products.json variant payload.
VARIANT_CACHE_KEYS = {
    "Variant Price":             "price",
    "Variant Compare At Price":  "compare_at_price",
    "Variant Barcode":           "barcode",
    "Variant Taxable":           "taxable",
    "Variant Inventory Policy":  "inventory_policy",
    "Variant Grams":             "grams",
    "Variant Requires Shipping": "requires_shipping",
    "Variant Inventory Tracker": "inventory_management",
}

# CSV column -> key in the REST products.json product payload.
PRODUCT_CACHE_KEYS = {
    "Title":       "title",
    "Body (HTML)": "body_html",
    "Vendor":      "vendor",
    "Type":        "product_type",
    "Tags":        "tags",
    "Status":      "status",
}

# REST products.json does not return these, so the diff cannot show a before value.
UNKNOWN_CURRENT = {"Cost per item", "Variant Tax Code", "SEO Title", "SEO Description"}

UNKNOWN = "unknown"
CLEARED = "(cleared)"


def current_value(column, variant, product):
    """The store's present value for a column, as a display string."""
    if column in UNKNOWN_CURRENT:
        return UNKNOWN
    if column in VARIANT_CACHE_KEYS:
        return str((variant or {}).get(VARIANT_CACHE_KEYS[column], ""))
    if column in PRODUCT_CACHE_KEYS:
        return str((product or {}).get(PRODUCT_CACHE_KEYS[column], ""))
    return UNKNOWN


def _comparable(text):
    """Normalise for change detection: case, spacing, money symbols, commas."""
    return (
        str(text).strip().lower()
        .replace("₹", "")
        .replace(",", "")
        .replace(" ", "")
    )


def _display_new(column, value):
    """Render a coerced value the way the diff table should show it."""
    if value is None:
        return CLEARED
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return ", ".join(value)
    if isinstance(value, dict):  # weight measurement
        return f"{value.get('value')} {value.get('unit', '').lower()}".strip()
    return str(value)


def diff_row(row, variant, product):
    """One record per column this row would write.

    Current values come from the already-fetched product cache, so the dry run
    costs no extra API calls. Columns in UNKNOWN_CURRENT always report Changed
    because there is nothing to compare against.
    """
    records = []
    all_columns = list(NATIVE_VARIANT_FIELDS) + list(NATIVE_PRODUCT_FIELDS)

    for column in all_columns:
        if column not in row:
            continue
        raw = row[column]
        if is_blank(raw):
            continue

        value, error = coerce_native_value(column, raw)
        present = current_value(column, variant, product)

        if error:
            records.append({
                "Field": column, "Current": present,
                "New": f"ERROR — {error}", "Changed": False,
            })
            continue

        shown = _display_new(column, value)
        if present == UNKNOWN:
            changed = True
        elif value is None:
            changed = _comparable(present) != ""
        else:
            changed = _comparable(present) != _comparable(shown)

        records.append({
            "Field": column, "Current": present, "New": shown, "Changed": changed,
        })

    return records
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_native_update.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add native_update.py tests/test_native_update.py
git commit -m "feat: add dry-run diff against cached product data"
```

---

### Task 6: Row resolution — map CSV rows to GIDs and bucket the outcomes

**Files:**
- Modify: `native_update.py`
- Modify: `tests/test_native_update.py`

**Interfaces:**
- Consumes: `build_variant_input`, `build_product_input`, `diff_row` from Tasks 2 and 5
- Produces:
  - `build_lookup_index(products: list[dict]) -> tuple[dict, dict]` — returns `(sku_map, handle_map)`. `sku_map[sku]` is `{"variant_gid", "product_gid", "variant", "product"}`; `handle_map[handle]` is `{"product_gid", "product", "variant"}` using the product's first variant.
  - `resolve_rows(rows: list[dict], sku_map: dict, handle_map: dict) -> dict` with keys `variant_updates`, `product_updates`, `diff_records`, `skipped`, `notfound`, `errors`
  - `recognised_native_columns(columns) -> list[str]`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_native_update.py`:

```python
from native_update import build_lookup_index, recognised_native_columns, resolve_rows

STORE_PRODUCTS = [
    {
        "id": 222,
        "handle": "arias-linear-diamond-earrings",
        "title": "Arias by Lara Dutta Brilliant Linear Diamond Earrings",
        "body_html": "<p>old</p>",
        "vendor": "Arias",
        "product_type": "Earrings",
        "tags": "gold",
        "status": "active",
        "variants": [{"id": 111, "sku": "SPLDT19906-14KY-4.91CT", "price": "287093.00"}],
    }
]


class TestBuildLookupIndex:
    def test_sku_map_holds_both_gids(self):
        sku_map, _ = build_lookup_index(STORE_PRODUCTS)
        entry = sku_map["SPLDT19906-14KY-4.91CT"]
        assert entry["variant_gid"] == "gid://shopify/ProductVariant/111"
        assert entry["product_gid"] == "gid://shopify/Product/222"
        assert entry["variant"]["price"] == "287093.00"
        assert entry["product"]["title"].startswith("Arias")

    def test_handle_map_uses_first_variant(self):
        _, handle_map = build_lookup_index(STORE_PRODUCTS)
        entry = handle_map["arias-linear-diamond-earrings"]
        assert entry["product_gid"] == "gid://shopify/Product/222"
        assert entry["variant"]["id"] == 111

    def test_blank_skus_not_indexed(self):
        products = [{"id": 1, "handle": "h", "variants": [{"id": 2, "sku": ""}]}]
        sku_map, _ = build_lookup_index(products)
        assert sku_map == {}


class TestRecognisedNativeColumns:
    def test_finds_native_columns(self):
        cols = ["Handle", "Variant SKU", "Variant Price", "Title"]
        assert recognised_native_columns(cols) == ["Variant Price", "Title"]

    def test_metafield_csv_has_none(self):
        cols = ["Handle", "Variant SKU", "Metafield namespace", "Metafield Key", "Metafield Value"]
        assert recognised_native_columns(cols) == []


class TestResolveRows:
    def setup_method(self):
        self.sku_map, self.handle_map = build_lookup_index(STORE_PRODUCTS)

    def test_price_row_becomes_variant_update(self):
        rows = [{"Variant SKU": "SPLDT19906-14KY-4.91CT", "Variant Price": "199999"}]
        out = resolve_rows(rows, self.sku_map, self.handle_map)
        assert len(out["variant_updates"]) == 1
        update = out["variant_updates"][0]
        assert update["product_gid"] == "gid://shopify/Product/222"
        assert update["variant_input"] == {
            "id": "gid://shopify/ProductVariant/111", "price": "199999",
        }
        assert update["meta"]["Variant SKU"] == "SPLDT19906-14KY-4.91CT"
        assert out["product_updates"] == []

    def test_title_row_becomes_product_update(self):
        rows = [{"Variant SKU": "SPLDT19906-14KY-4.91CT", "Title": "New Title"}]
        out = resolve_rows(rows, self.sku_map, self.handle_map)
        assert out["variant_updates"] == []
        assert out["product_updates"][0]["product_input"] == {
            "id": "gid://shopify/Product/222", "title": "New Title",
        }

    def test_row_can_produce_both_updates(self):
        rows = [{"Variant SKU": "SPLDT19906-14KY-4.91CT", "Variant Price": "1", "Title": "T"}]
        out = resolve_rows(rows, self.sku_map, self.handle_map)
        assert len(out["variant_updates"]) == 1
        assert len(out["product_updates"]) == 1

    def test_handle_fallback_when_sku_absent(self):
        rows = [{"Handle": "arias-linear-diamond-earrings", "Title": "New Title"}]
        out = resolve_rows(rows, self.sku_map, self.handle_map)
        assert out["product_updates"][0]["product_input"]["id"] == "gid://shopify/Product/222"

    def test_unknown_sku_goes_to_notfound(self):
        rows = [{"Variant SKU": "DOES-NOT-EXIST", "Variant Price": "1"}]
        out = resolve_rows(rows, self.sku_map, self.handle_map)
        assert out["variant_updates"] == []
        assert len(out["notfound"]) == 1
        assert "not in store" in out["notfound"][0]["Reason"]

    def test_row_with_no_native_values_is_skipped(self):
        rows = [{"Variant SKU": "SPLDT19906-14KY-4.91CT", "Variant Price": ""}]
        out = resolve_rows(rows, self.sku_map, self.handle_map)
        assert out["variant_updates"] == []
        assert len(out["skipped"]) == 1
        assert "no updatable" in out["skipped"][0]["Reason"]

    def test_bad_value_goes_to_errors(self):
        rows = [{"Variant SKU": "SPLDT19906-14KY-4.91CT", "Variant Price": "abc"}]
        out = resolve_rows(rows, self.sku_map, self.handle_map)
        assert out["variant_updates"] == []
        assert len(out["errors"]) == 1
        assert "not a valid amount" in out["errors"][0]["Error"]

    def test_diff_records_carry_sku_and_title(self):
        rows = [{"Variant SKU": "SPLDT19906-14KY-4.91CT", "Variant Price": "199999"}]
        out = resolve_rows(rows, self.sku_map, self.handle_map)
        record = out["diff_records"][0]
        assert record["Variant SKU"] == "SPLDT19906-14KY-4.91CT"
        assert record["Field"] == "Variant Price"
        assert record["Current"] == "287093.00"
        assert record["New"] == "199999"
        assert record["Changed"] is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_native_update.py -q`
Expected: FAIL — `ImportError: cannot import name 'build_lookup_index'`

- [ ] **Step 3: Write the implementation**

Append to `native_update.py`:

```python
KEY_COLUMNS = ("Variant SKU", "Handle")


def recognised_native_columns(columns):
    """Native field columns present in an uploaded CSV, in mapping order."""
    known = list(NATIVE_VARIANT_FIELDS) + list(NATIVE_PRODUCT_FIELDS)
    return [column for column in known if column in columns]


def build_lookup_index(products):
    """Build O(1) SKU and handle lookups from the cached product list.

    Mirrors the index built for the metafield bulk path in app.py, but also
    carries the raw variant and product dicts so the dry-run diff can read
    current values without extra API calls.
    """
    sku_map = {}
    handle_map = {}
    for product in products:
        product_gid = f"gid://shopify/Product/{product['id']}"
        variants = product.get("variants") or []
        first_variant = variants[0] if variants else {}

        handle = str(product.get("handle", "")).strip()
        if handle:
            handle_map[handle] = {
                "product_gid": product_gid,
                "product": product,
                "variant": first_variant,
            }

        for variant in variants:
            sku = str(variant.get("sku", "")).strip()
            if not sku:
                continue
            sku_map[sku] = {
                "variant_gid": f"gid://shopify/ProductVariant/{variant['id']}",
                "product_gid": product_gid,
                "variant": variant,
                "product": product,
            }
    return sku_map, handle_map


def _row_meta(row, product):
    """Identifying columns carried through to every result table."""
    return {
        "Variant SKU": str(row.get("Variant SKU", "") or "").strip(),
        "Handle": str(row.get("Handle", "") or "").strip(),
        "Product": str((product or {}).get("title", ""))[:60],
    }


def resolve_rows(rows, sku_map, handle_map):
    """Turn CSV rows into GraphQL inputs, bucketing every row into an outcome.

    Every input row lands in exactly one of: variant_updates and/or
    product_updates (success), skipped, notfound, or errors.
    """
    variant_updates = []
    product_updates = []
    diff_records = []
    skipped = []
    notfound = []
    errors = []

    for row in rows:
        sku = str(row.get("Variant SKU", "") or "").strip()
        handle = str(row.get("Handle", "") or "").strip()

        target = None
        if sku and sku.lower() not in _BLANK_WORDS:
            target = sku_map.get(sku)
        if target is None and handle and handle.lower() not in _BLANK_WORDS:
            target = handle_map.get(handle)

        if target is None:
            notfound.append({
                **_row_meta(row, None),
                "Reason": "SKU/handle not in store",
            })
            continue

        product = target["product"]
        variant = target["variant"]
        meta = _row_meta(row, product)

        variant_gid = target.get("variant_gid")
        if variant_gid is None and variant:
            variant_gid = f"gid://shopify/ProductVariant/{variant['id']}"

        variant_input, variant_errors = (
            build_variant_input(row, variant_gid) if variant_gid else (None, [])
        )
        product_input, product_errors = build_product_input(row, target["product_gid"])

        row_errors = variant_errors + product_errors
        if row_errors:
            errors.append({**meta, "Error": "; ".join(row_errors)[:250]})
            continue

        if variant_input is None and product_input is None:
            skipped.append({**meta, "Reason": "no updatable native fields in row"})
            continue

        if variant_input is not None:
            variant_updates.append({
                "product_gid": target["product_gid"],
                "variant_input": variant_input,
                "meta": meta,
            })
        if product_input is not None:
            product_updates.append({
                "product_gid": target["product_gid"],
                "product_input": product_input,
                "meta": meta,
            })

        for record in diff_row(row, variant, product):
            diff_records.append({**meta, **record})

    return {
        "variant_updates": variant_updates,
        "product_updates": product_updates,
        "diff_records": diff_records,
        "skipped": skipped,
        "notfound": notfound,
        "errors": errors,
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_native_update.py -q`
Expected: PASS

- [ ] **Step 5: Run the whole suite**

Run: `python -m pytest tests/ -q`
Expected: PASS, no failures

- [ ] **Step 6: Commit**

```bash
git add native_update.py tests/test_native_update.py
git commit -m "feat: resolve CSV rows to GIDs and bucket update outcomes"
```

---

### Task 7: Tab 6 UI — upload, validate, dry run

**Files:**
- Modify: `app.py:633` (tab list), `app.py:493-499` (session state), end of file after `app.py:1484`

**Interfaces:**
- Consumes: `build_lookup_index`, `resolve_rows`, `recognised_native_columns`, `NATIVE_VARIANT_FIELDS`, `NATIVE_PRODUCT_FIELDS`, `NATIVE_BATCH_SIZE` from Tasks 1-6; existing `fetch_all_products(headers, store_url)` from `app.py:288`
- Produces: `st.session_state.native_plan` holding the resolved plan across Streamlit reruns, consumed by Task 8

- [ ] **Step 1: Add the module import**

Find the existing import block at the top of `app.py` and add:

```python
from native_update import (
    NATIVE_BATCH_SIZE,
    NATIVE_PRODUCT_FIELDS,
    NATIVE_VARIANT_FIELDS,
    build_aliased_product_mutation,
    build_aliased_variant_mutation,
    build_lookup_index,
    chunk,
    group_by_product,
    recognised_native_columns,
    resolve_rows,
    send_native_batch,
)
```

- [ ] **Step 2: Add session state keys**

At `app.py:499`, after the `bulk_results` line, add:

```python
if "native_plan"    not in st.session_state: st.session_state.native_plan    = None
if "native_results" not in st.session_state: st.session_state.native_results = None
```

- [ ] **Step 3: Add the sixth tab**

Replace line `app.py:633`:

```python
tab1, tab2, tab3, tab4, tab5 = st.tabs(["📥  Import Metafields", "📤  Export Metafields", "📋  View Products", "🔄  Update Metafields", "⚡  Bulk Update (40k+)"])
```

with:

```python
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["📥  Import Metafields", "📤  Export Metafields", "📋  View Products", "🔄  Update Metafields", "⚡  Bulk Update (40k+)", "🏷️  Update Native Fields"])
```

- [ ] **Step 4: Append the tab 6 block at the end of app.py**

Add after the final line of the tab 5 block (currently `app.py:1484`):

```python
# ─────────────────────────────────────────────────────────
# TAB 6 — UPDATE NATIVE FIELDS (price, compare-at, cost, title, tags …)
# ─────────────────────────────────────────────────────────
with tab6:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.markdown('<div class="section-title">🏷️ Update Native Fields</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-subtitle">Changes real Shopify fields — price, compare-at, '
        'barcode, cost, weight, title, tags, status — on products that already exist. '
        'Uses GraphQL <code>productVariantsBulkUpdate</code> and <code>productUpdate</code>. '
        'You will see a diff and must press Apply before anything is written.</div>',
        unsafe_allow_html=True
    )

    with st.expander("📋 CSV Format", expanded=False):
        st.markdown("""
        **Key column** — `Variant SKU` (preferred) or `Handle`.

        **Then any of these columns.** Include only the ones you want to change:
        """)
        st.dataframe(
            pd.DataFrame({
                "Column": list(NATIVE_VARIANT_FIELDS) + list(NATIVE_PRODUCT_FIELDS),
                "Level":  ["variant"] * len(NATIVE_VARIANT_FIELDS) + ["product"] * len(NATIVE_PRODUCT_FIELDS),
            }),
            use_container_width=True, hide_index=True
        )
        st.markdown("""
        **Rules**
        - **Blank cell = field left alone.** Nothing is ever written as empty.
        - **Column not in your CSV = field never touched.**
        - To deliberately empty Compare At Price or Barcode, type `CLEAR`.
        - `Variant Grams` is always grams. `Variant Weight Unit` is ignored.
        - `Variant Inventory Policy`: `DENY` or `CONTINUE`. `Status`: `ACTIVE`, `DRAFT`, `ARCHIVED`.
        - Inventory **quantity** is not supported here — use Shopify admin.

        Tip: run the Export tab, edit the columns you need in Excel, upload the file here.
        """)
        st.dataframe(
            pd.DataFrame([
                {"Variant SKU": "SPLDT19906-14KY-4.91CT", "Variant Price": "199999", "Variant Compare At Price": "250000"},
                {"Variant SKU": "SQT19349-EG-925S-0.8CT", "Variant Price": "8999",   "Variant Compare At Price": "CLEAR"},
            ]),
            use_container_width=True, hide_index=True
        )

    st.warning(
        "⚠️ This writes the real Shopify price. If your theme also shows a "
        "`Display Price` metafield, update that separately in the Bulk Update tab "
        "or the two numbers will disagree."
    )

    st.markdown("<br>", unsafe_allow_html=True)

    native_file = st.file_uploader("Upload CSV", type=["csv"], key="native_file")

    if native_file:
        df_native = pd.read_csv(native_file, encoding="utf-8-sig", dtype=str)
        df_native = df_native.loc[:, ~df_native.columns.str.startswith("Unnamed")]

        found_cols = recognised_native_columns(list(df_native.columns))
        has_key    = any(c in df_native.columns for c in ("Variant SKU", "Handle"))

        if not has_key:
            st.error("❌ CSV needs a `Variant SKU` or `Handle` column to identify each product.")
        elif not found_cols:
            st.error(
                "❌ No native field columns found. This tab updates native fields — "
                "for metafields use the Bulk Update tab. Expected one of: "
                f"{', '.join(list(NATIVE_VARIANT_FIELDS) + list(NATIVE_PRODUCT_FIELDS))}"
            )
        else:
            st.success(f"✅ Will update: **{', '.join(found_cols)}**")

            n1, n2 = st.columns(2)
            n1.metric("Rows in CSV", len(df_native))
            row_limit = n2.number_input(
                "Limit to first N rows (0 = all) — use a small number to test first",
                min_value=0, max_value=len(df_native), value=0, step=1, key="native_limit"
            )

            with st.expander("👁️ Preview upload", expanded=False):
                st.dataframe(df_native.head(10), use_container_width=True)

            st.markdown("<br>", unsafe_allow_html=True)

            if st.button("🔍 Step 1 — Preview changes (nothing is written)", key="btn_native_dryrun"):
                st.session_state.native_results = None

                rows = df_native.to_dict("records")
                if row_limit:
                    rows = rows[:int(row_limit)]

                with st.spinner("Loading products from store..."):
                    products_cache = fetch_all_products(
                        st.session_state.headers, st.session_state.store_url
                    )

                with st.spinner(f"Matching {len(rows)} rows against {len(products_cache)} products..."):
                    sku_map, handle_map = build_lookup_index(products_cache)
                    plan = resolve_rows(rows, sku_map, handle_map)

                st.session_state.native_plan = plan

            # ── Dry-run report (persists across reruns) ───────────
            if st.session_state.native_plan:
                plan     = st.session_state.native_plan
                diff_df  = pd.DataFrame(plan["diff_records"])
                changed  = diff_df[diff_df["Changed"]] if not diff_df.empty else diff_df
                unchanged_count = 0 if diff_df.empty else int((~diff_df["Changed"]).sum())

                st.markdown("<br>", unsafe_allow_html=True)
                p1, p2, p3, p4 = st.columns(4)
                p1.metric("✏️ Fields to change", 0 if diff_df.empty else len(changed))
                p2.metric("➖ Already correct",  unchanged_count)
                p3.metric("⚠️ Bad values",       len(plan["errors"]))
                p4.metric("🔍 Not found",        len(plan["notfound"]))

                if not diff_df.empty and len(changed):
                    with st.expander(f"✏️ Changes to apply ({len(changed)})", expanded=True):
                        st.dataframe(changed, use_container_width=True, height=320)
                        st.download_button(
                            "⬇️ Download planned changes",
                            data=changed.to_csv(index=False).encode("utf-8"),
                            file_name=f"native_planned_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                            mime="text/csv", key="dl_native_planned"
                        )

                if unchanged_count:
                    with st.expander(f"➖ Already matching the store ({unchanged_count}) — will still be sent", expanded=False):
                        st.dataframe(diff_df[~diff_df["Changed"]], use_container_width=True, height=240)

                if plan["errors"]:
                    with st.expander(f"⚠️ Rows with bad values — skipped entirely ({len(plan['errors'])})", expanded=True):
                        st.dataframe(pd.DataFrame(plan["errors"]), use_container_width=True, height=240)

                if plan["notfound"]:
                    with st.expander(f"🔍 Not found in store ({len(plan['notfound'])})", expanded=True):
                        st.dataframe(pd.DataFrame(plan["notfound"]), use_container_width=True, height=240)

                if plan["skipped"]:
                    with st.expander(f"⏭️ Skipped — no native values ({len(plan['skipped'])})", expanded=False):
                        st.dataframe(pd.DataFrame(plan["skipped"]), use_container_width=True, height=240)

                if "Cost per item" in found_cols or "Variant Tax Code" in found_cols \
                        or "SEO Title" in found_cols or "SEO Description" in found_cols:
                    st.info(
                        "ℹ️ Cost per item, Variant Tax Code, SEO Title and SEO Description "
                        "are not returned by the product list API, so their current values "
                        "show as `unknown`. They will still be overwritten."
                    )

    st.markdown('</div>', unsafe_allow_html=True)
```

- [ ] **Step 5: Verify the app still starts and the tab renders**

Run: `python -m streamlit run app.py --server.headless true`
Then open the app, connect to the store, and click the "🏷️ Update Native Fields" tab.
Expected: the tab renders, the CSV format expander lists all 18 columns, and no traceback appears in the terminal. Stop the server with Ctrl+C.

- [ ] **Step 6: Verify validation rejects a metafield CSV**

Upload the existing `Metafield_updates.csv` to tab 6.
Expected: red error "No native field columns found... for metafields use the Bulk Update tab".

- [ ] **Step 7: Commit**

```bash
git add app.py
git commit -m "feat: add native fields tab with dry-run diff preview"
```

---

### Task 8: Tab 6 — apply, report, and verify

**Files:**
- Modify: `app.py` (inside the tab 6 block added in Task 7)

**Interfaces:**
- Consumes: `st.session_state.native_plan` from Task 7; `group_by_product`, `chunk`, `build_aliased_variant_mutation`, `build_aliased_product_mutation`, `send_native_batch` from Tasks 3-4
- Produces: `st.session_state.native_results`

- [ ] **Step 1: Add the Apply block**

Inside the `if st.session_state.native_plan:` block from Task 7, immediately before the final `st.markdown('</div>', unsafe_allow_html=True)`, insert:

```python
                total_mutations = len(plan["variant_updates"]) + len(plan["product_updates"])

                if total_mutations:
                    st.markdown("<br>", unsafe_allow_html=True)
                    st.markdown("---")

                    variant_groups   = group_by_product(plan["variant_updates"])
                    variant_batches  = chunk(variant_groups, NATIVE_BATCH_SIZE)
                    product_batches  = chunk(plan["product_updates"], NATIVE_BATCH_SIZE)
                    total_batches    = len(variant_batches) + len(product_batches)
                    est_seconds      = total_batches * 1.2
                    est_label        = (f"~{round(est_seconds / 60, 1)} min"
                                        if est_seconds >= 60 else f"~{int(est_seconds)}s")

                    a1, a2, a3 = st.columns(3)
                    a1.metric("Variant writes", len(plan["variant_updates"]))
                    a2.metric("Product writes", len(plan["product_updates"]))
                    a3.metric("Estimated time", est_label)

                    verify_after = st.checkbox(
                        "Verify after applying (re-reads each touched product)",
                        value=total_mutations <= 500, key="native_verify"
                    )

                    confirm = st.checkbox(
                        f"I have reviewed the diff above and want to write {total_mutations} change(s) to Shopify",
                        key="native_confirm"
                    )

                    if st.button("🚀 Step 2 — Apply to Shopify", key="btn_native_apply", disabled=not confirm):
                        gql_url = f"https://{st.session_state.store_url}/admin/api/2025-01/graphql.json"

                        native_log    = st.empty()
                        native_prog   = st.progress(0)
                        native_status = st.empty()
                        n_logs        = []

                        def nlog(msg):
                            n_logs.append(msg)
                            native_log.markdown(
                                f'<div class="log-box">{"<br>".join(n_logs[-50:])}</div>',
                                unsafe_allow_html=True
                            )

                        ok_rows, fail_rows = [], []
                        done_batches = 0

                        nlog(f"🚀 {total_batches} batches "
                             f"({NATIVE_BATCH_SIZE} aliased mutations each)")
                        nlog("─────────────────────────────────────")

                        # ── Variant field batches ─────────────────
                        for batch in variant_batches:
                            query, variables = build_aliased_variant_mutation(batch)
                            alias_metas      = [g["metas"] for g in batch]
                            ok, failed = send_native_batch(
                                st.session_state.headers, gql_url, query, variables, alias_metas
                            )
                            ok_rows.extend(ok)
                            fail_rows.extend(failed)
                            done_batches += 1
                            native_prog.progress(done_batches / total_batches)
                            native_status.markdown(
                                f"**Variant batch {done_batches}/{total_batches}** — "
                                f"{len(ok_rows)} ok, {len(fail_rows)} failed"
                            )
                            nlog(f"  {'✅' if not failed else '⚠️'} variant batch "
                                 f"{done_batches} — {len(ok)} ok, {len(failed)} failed")
                            time.sleep(0.5)

                        # ── Product field batches ─────────────────
                        for batch in product_batches:
                            inputs      = [item["product_input"] for item in batch]
                            alias_metas = [[item["meta"]] for item in batch]
                            query, variables = build_aliased_product_mutation(inputs)
                            ok, failed = send_native_batch(
                                st.session_state.headers, gql_url, query, variables, alias_metas
                            )
                            ok_rows.extend(ok)
                            fail_rows.extend(failed)
                            done_batches += 1
                            native_prog.progress(done_batches / total_batches)
                            native_status.markdown(
                                f"**Product batch {done_batches}/{total_batches}** — "
                                f"{len(ok_rows)} ok, {len(fail_rows)} failed"
                            )
                            nlog(f"  {'✅' if not failed else '⚠️'} product batch "
                                 f"{done_batches} — {len(ok)} ok, {len(failed)} failed")
                            time.sleep(0.5)

                        # ── Verification re-read ──────────────────
                        verified_rows, mismatch_rows = [], []
                        if verify_after and ok_rows:
                            nlog("─────────────────────────────────────")
                            nlog(f"🔎 Verifying {len(ok_rows)} written rows...")
                            wanted = {}
                            for record in plan["diff_records"]:
                                wanted.setdefault(record["Variant SKU"], []).append(record)

                            fresh = fetch_all_products(
                                st.session_state.headers, st.session_state.store_url
                            )
                            fresh_sku, fresh_handle = build_lookup_index(fresh)

                            for sku, records in wanted.items():
                                entry = fresh_sku.get(sku)
                                if not entry:
                                    continue
                                for record in records:
                                    if str(record["New"]).startswith("ERROR"):
                                        continue
                                    now = current_value(
                                        record["Field"], entry["variant"], entry["product"]
                                    )
                                    if now == "unknown":
                                        continue
                                    expected = record["New"]
                                    same = (str(now).strip().lower().replace(",", "")
                                            == str(expected).strip().lower().replace(",", ""))
                                    row = {"Variant SKU": sku, "Field": record["Field"],
                                           "Expected": expected, "In store now": now}
                                    (verified_rows if same else mismatch_rows).append(row)

                            nlog(f"  ✅ {len(verified_rows)} verified | "
                                 f"⚠️ {len(mismatch_rows)} mismatched")

                        st.session_state.native_results = {
                            "ok_rows": ok_rows,
                            "fail_rows": fail_rows,
                            "skipped": plan["skipped"],
                            "notfound": plan["notfound"],
                            "errors": plan["errors"],
                            "verified": verified_rows,
                            "mismatched": mismatch_rows,
                        }

                        native_prog.progress(1.0)
                        native_status.markdown("**✅ Apply complete!**")
                        nlog("─────────────────────────────────────")
                        nlog(f"✅ Written  : {len(ok_rows)}")
                        nlog(f"❌ Failed   : {len(fail_rows)}")
                        nlog("─────────────────────────────────────")

            # ── Results (persist across reruns) ────────────────────
            if st.session_state.native_results:
                res = st.session_state.native_results

                st.markdown("<br>", unsafe_allow_html=True)
                r1, r2, r3, r4 = st.columns(4)
                r1.metric("✅ Written",   len(res["ok_rows"]))
                r2.metric("❌ Failed",    len(res["fail_rows"]))
                r3.metric("✔️ Verified",  len(res["verified"]))
                r4.metric("⚠️ Mismatch",  len(res["mismatched"]))

                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

                for label, rows, expanded, slug in [
                    (f"✅ Written ({len(res['ok_rows'])})",        res["ok_rows"],    False, "written"),
                    (f"❌ Failed ({len(res['fail_rows'])})",       res["fail_rows"],  True,  "failed"),
                    (f"⚠️ Mismatched after write ({len(res['mismatched'])})", res["mismatched"], True, "mismatched"),
                    (f"✔️ Verified ({len(res['verified'])})",      res["verified"],   False, "verified"),
                    (f"⚠️ Bad values ({len(res['errors'])})",      res["errors"],     False, "badvalues"),
                    (f"🔍 Not found ({len(res['notfound'])})",     res["notfound"],   False, "notfound"),
                    (f"⏭️ Skipped ({len(res['skipped'])})",        res["skipped"],    False, "skipped"),
                ]:
                    if not rows:
                        continue
                    with st.expander(label, expanded=expanded):
                        frame = pd.DataFrame(rows)
                        st.dataframe(frame, use_container_width=True, height=300)
                        st.download_button(
                            f"⬇️ Download {slug} rows",
                            data=frame.to_csv(index=False).encode("utf-8"),
                            file_name=f"native_{slug}_{stamp}.csv",
                            mime="text/csv", key=f"dl_native_{slug}"
                        )
```

- [ ] **Step 2: Add `current_value` to the import list**

The verification block calls `current_value`. Update the `from native_update import (...)` block added in Task 7 Step 1 to include it:

```python
    current_value,
```

- [ ] **Step 3: Verify the app starts with no syntax or import errors**

Run: `python -c "import ast, sys; ast.parse(open('app.py', encoding='utf-8').read()); print('app.py parses')"`
Expected: `app.py parses`

Run: `python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 4: Live test on one SKU**

Create `scratch_one_sku.csv` (do not commit it):

```csv
Variant SKU,Variant Price
SPLDT19906-14KY-4.91CT,287094
```

Run: `python -m streamlit run app.py`
Then: connect → tab 6 → upload the file → **Preview changes**.
Expected: diff shows one row, `Variant Price`, Current `287093.00`, New `287094`, Changed `True`.

Tick the confirm box → **Apply**.
Expected: Written 1, Failed 0, Verified 1, Mismatch 0. Confirm ₹287,094.00 in Shopify admin, then set it back to 287093 the same way.

- [ ] **Step 5: Live test that a blank cell does not wipe a value**

Create `scratch_blank.csv`:

```csv
Variant SKU,Variant Price,Variant Compare At Price
SPLDT19906-14KY-4.91CT,287093,
```

Preview.
Expected: the diff shows **only** `Variant Price` — no `Variant Compare At Price` row at all. Apply, then confirm in Shopify admin that Compare-at is unchanged.

- [ ] **Step 6: Live test the row limit**

Upload a CSV with 20 rows, set "Limit to first N rows" to 5, and preview.
Expected: the diff covers exactly 5 SKUs.

- [ ] **Step 7: Commit**

```bash
git add app.py
git commit -m "feat: apply native field updates with verification and per-row reporting"
```

---

### Task 9: Document the new tab

**Files:**
- Modify: `app.py` (the help text block at `app.py:565` listing what the app does)
- Create: `docs/native-fields.md`

**Interfaces:**
- Consumes: nothing
- Produces: nothing

- [ ] **Step 1: Read the existing help block**

Run: `python -c "print(open('app.py', encoding='utf-8').read().split(chr(10))[555:580])"`
Note the surrounding HTML so the addition matches its style.

- [ ] **Step 2: Add a line to the sidebar help block**

In the `<b style='color:#444'>Variant level:</b>` help block near `app.py:565`, append a sentence noting that native fields (price, compare-at, cost, weight) are updated in the **Update Native Fields** tab, not the metafield tabs.

- [ ] **Step 3: Write the user-facing doc**

Create `docs/native-fields.md`:

```markdown
# Updating native fields (price, compare-at, cost, title, tags)

The metafield tabs cannot change native Shopify fields. Use the
**🏷️ Update Native Fields** tab.

## Quick start — change prices

1. Export tab → download your products.
2. Keep only the `Variant SKU` and `Variant Price` columns, edit the prices.
3. Update Native Fields tab → upload → **Preview changes**.
4. Check the diff. Current value and new value are shown per SKU.
5. Tick the confirm box → **Apply to Shopify**.

## Supported columns

Key column: `Variant SKU` (preferred) or `Handle`.

Variant level: `Variant Price`, `Variant Compare At Price`, `Variant Barcode`,
`Variant Taxable`, `Variant Tax Code`, `Variant Inventory Policy`,
`Cost per item`, `Variant Grams`, `Variant Requires Shipping`,
`Variant Inventory Tracker`.

Product level: `Title`, `Body (HTML)`, `Vendor`, `Type`, `Tags`, `Status`,
`SEO Title`, `SEO Description`.

## Rules that prevent accidents

- A **blank cell leaves the field alone.** Nothing is written as empty.
- A **column you leave out is never touched.**
- To deliberately empty Compare At Price or Barcode, type `CLEAR`.
- `Variant Grams` is always grams; `Variant Weight Unit` is ignored.
- Nothing is written until you press **Apply** after seeing the diff.
- Use "Limit to first N rows" to prove a change on a few SKUs first.

## Not supported

- Inventory **quantity** — use Shopify admin.
- Changing a SKU — it is the key used to find the row.
- Images and option values.

## Display Price

If your theme reads a `Display Price` metafield, this tab does not update it.
Change it in the Bulk Update tab, or the displayed price and the real price
will disagree.
```

- [ ] **Step 4: Verify the app still parses**

Run: `python -c "import ast; ast.parse(open('app.py', encoding='utf-8').read()); print('ok')"`
Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add app.py docs/native-fields.md
git commit -m "docs: document the native fields tab"
```

---

## Self-Review Notes

**Spec coverage check:**

| Spec section | Task |
|---|---|
| Variant field mapping (10 columns) | 1, 2 |
| Product field mapping (8 columns) | 1, 2 |
| Value coercion (money, bool, enum, weight, tracker, tags) | 1 |
| Blank = skip, absent column = untouched | 2 (unit-tested), 7 (UI copy) |
| `CLEAR` sentinel, clearable columns only | 1, 2 |
| Weight always grams, unit column ignored | 1, 2 |
| Lookup index reuse (SKU then handle) | 6 |
| Grouping by product | 3 |
| Aliased mutations, `NATIVE_BATCH_SIZE = 10` | 3 |
| Rate-limit retry (429, THROTTLED, 3 attempts) | 4 |
| Per-alias error attribution | 4 |
| Dry-run diff, `unknown` for cost/tax code/SEO | 5, 7 |
| Row limit for testing | 7 |
| Separate Apply button | 8 |
| Four result tables + downloads | 8 |
| Progress per batch not per row | 8 |
| Post-apply verification | 8 |
| Metafield-CSV-uploaded-by-mistake guard | 7 |
| `taxCode` Plus-only risk | 8 Step 1 — surfaces as a `userErrors` row in the Failed table |
| `productUpdate` argument-name risk | 3 — documented in the docstring, pinned to 2025-01 |
| Display Price drift caution in UI | 7 |

**Type consistency:** `send_native_batch` adds the key `"Error"` to failed metas; the results table in Task 8 renders whatever keys exist, and Task 6 also uses `"Error"` for bad-value rows and `"Reason"` for skipped/not-found rows. Consistent across tasks. Alias naming `m{i}` is defined in Task 3 and consumed in Task 4. `_row_meta` produces `Variant SKU`, `Handle`, `Product`, which the verification step in Task 8 reads as `meta["Variant SKU"]`.

**Deliberate scope note:** rows whose values already match the store are still sent rather than filtered out. Filtering would be an optimisation, but sending them makes the applied set exactly equal to the previewed set, which is easier to reason about when something goes wrong.
