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
