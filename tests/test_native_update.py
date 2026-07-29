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

    @pytest.mark.parametrize("raw", ["nan", "NaN", "Infinity", "Inf", "-Infinity"])
    def test_non_finite_amount_is_an_error(self, raw):
        value, error = coerce_native_value("Variant Price", raw)
        assert value is None
        assert error is not None
        assert "not a valid amount" in error


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

    @pytest.mark.parametrize("raw", ["nan", "NaN", "Infinity", "Inf", "-Infinity"])
    def test_non_finite_weight_is_an_error(self, raw):
        value, error = coerce_native_value("Variant Grams", raw)
        assert value is None
        assert error is not None
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


from native_update import build_product_input, build_variant_input
from native_update import (
    build_aliased_variant_mutation,
    build_lookup_index,
    current_value,
    diff_row,
    group_by_product,
    resolve_rows,
)

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


class TestBatchingAndResolution:
    def test_groups_variants_and_builds_aliases(self):
        groups = group_by_product([
            {"product_gid": "p1", "variant_input": {"id": "v1"}, "meta": {"SKU": "one"}},
            {"product_gid": "p1", "variant_input": {"id": "v2"}, "meta": {"SKU": "two"}},
        ])
        assert groups[0]["variants"] == [{"id": "v1"}, {"id": "v2"}]
        query, variables = build_aliased_variant_mutation(groups)
        assert "m0: productVariantsBulkUpdate" in query
        assert variables["v0"] == [{"id": "v1"}, {"id": "v2"}]

    def test_diff_normalises_money_and_marks_unknown_current_changed(self):
        variant = {"price": "287093.00"}
        assert diff_row({"Variant Price": "287,093.00"}, variant, [])[0]["Changed"] is False
        assert diff_row({"Cost per item": "10"}, variant, [])[0]["Changed"] is True
        assert current_value("Cost per item", variant, {}) == "unknown"

    def test_resolve_rows_buckets_native_updates(self):
        products = [{"id": 2, "handle": "ring", "title": "Ring", "variants": [{"id": 1, "sku": "SKU-1", "price": "10"}]}]
        sku_map, handle_map = build_lookup_index(products)
        resolved = resolve_rows([{"Variant SKU": "SKU-1", "Variant Price": "12", "Title": "New Ring"}], sku_map, handle_map)
        assert resolved["variant_updates"][0]["variant_input"]["price"] == "12"
        assert resolved["product_updates"][0]["product_input"]["title"] == "New Ring"
