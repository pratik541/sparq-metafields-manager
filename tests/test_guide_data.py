import pandas as pd

from guide_data import (
    GUIDE_COLUMNS,
    GUIDE_ROWS,
    compare_with_guide,
    guide_metafield_index,
    native_sample_rows,
)
from native_update import (
    NATIVE_PRODUCT_FIELDS,
    NATIVE_VARIANT_FIELDS,
    recognised_native_columns,
)


def definition(namespace, key, type_name, owner="product"):
    return {
        "Name": key,
        "Owner": owner,
        "Metafield namespace": namespace,
        "Metafield Key": key,
        "Metafield type": type_name,
        "Description": "",
    }


class TestGuideCoverage:
    """The guide must document every field the code can actually write."""

    def test_every_native_column_is_documented(self):
        documented = {row["Put this in your CSV"] for row in GUIDE_ROWS}
        in_code = set(NATIVE_VARIANT_FIELDS) | set(NATIVE_PRODUCT_FIELDS)
        assert in_code - documented == set()

    def test_every_row_has_all_guide_columns(self):
        for row in GUIDE_ROWS:
            assert list(row.keys()) == GUIDE_COLUMNS

    def test_no_row_has_a_blank_cell(self):
        for row in GUIDE_ROWS:
            for column, value in row.items():
                assert str(value).strip(), f"{row['I want to change']} has empty {column}"

    def test_kind_is_one_of_the_expected_labels(self):
        for row in GUIDE_ROWS:
            assert row["Kind"] in (
                "Native column", "Metafield", "Metafield (variant level)"
            )

    def test_native_rows_name_a_real_column(self):
        in_code = set(NATIVE_VARIANT_FIELDS) | set(NATIVE_PRODUCT_FIELDS)
        for row in GUIDE_ROWS:
            if row["Kind"] == "Native column":
                assert row["Put this in your CSV"] in in_code

    def test_metafield_rows_are_namespaced(self):
        for row in GUIDE_ROWS:
            if row["Kind"].startswith("Metafield"):
                assert "." in row["Put this in your CSV"]


class TestNativeSample:
    def test_sample_would_pass_tab_validation(self):
        df = pd.DataFrame(native_sample_rows())
        assert recognised_native_columns(df.columns)
        assert "Variant SKU" in df.columns

    def test_sample_columns_are_all_real_native_columns(self):
        df = pd.DataFrame(native_sample_rows())
        in_code = set(NATIVE_VARIANT_FIELDS) | set(NATIVE_PRODUCT_FIELDS)
        for column in df.columns:
            assert column == "Variant SKU" or column in in_code

    def test_sample_demonstrates_the_clear_sentinel(self):
        values = {str(v) for row in native_sample_rows() for v in row.values()}
        assert "CLEAR" in values


class TestGuideMetafieldIndex:
    def test_indexes_only_metafields(self):
        index = guide_metafield_index()
        assert all("." in key for key in index)
        assert "Variant Price" not in index

    def test_display_price_is_present(self):
        assert "custom.display_price" in guide_metafield_index()


class TestCompareWithGuide:
    def test_matching_type_produces_no_findings(self):
        unlisted, mismatched = compare_with_guide([
            definition("custom", "product_rating", "number_decimal")
        ])
        assert unlisted == []
        assert mismatched == []

    def test_unknown_metafield_is_unlisted(self):
        unlisted, mismatched = compare_with_guide([
            definition("custom", "internal_note", "single_line_text_field")
        ])
        assert mismatched == []
        assert unlisted == [{
            "Metafield": "custom.internal_note",
            "Owner": "product",
            "Real type": "single_line_text_field",
        }]

    def test_wrong_type_is_mismatched(self):
        """The shopify.* case: guide says text, store says metaobject reference."""
        unlisted, mismatched = compare_with_guide([
            definition("shopify", "color-pattern", "list.metaobject_reference")
        ])
        assert unlisted == []
        assert len(mismatched) == 1
        assert mismatched[0]["Metafield"] == "shopify.color-pattern"
        assert mismatched[0]["Store actually says"] == "list.metaobject_reference"
        assert "single_line_text_field" in mismatched[0]["Guide says"]

    def test_prose_type_cell_still_matches(self):
        """custom_product's guide cell reads 'boolean — TRUE or FALSE'."""
        _, mismatched = compare_with_guide([
            definition("mm-google-shopping", "custom_product", "boolean")
        ])
        assert mismatched == []

    def test_money_type_matches_display_price(self):
        _, mismatched = compare_with_guide([
            definition("custom", "display_price", "money", owner="variant")
        ])
        assert mismatched == []

    def test_blank_real_type_is_not_reported_as_mismatch(self):
        _, mismatched = compare_with_guide([
            definition("custom", "product_rating", "")
        ])
        assert mismatched == []

    def test_owner_is_carried_through(self):
        unlisted, _ = compare_with_guide([
            definition("custom", "brand_new", "money", owner="variant")
        ])
        assert unlisted[0]["Owner"] == "variant"

    def test_empty_input_produces_no_findings(self):
        assert compare_with_guide([]) == ([], [])
