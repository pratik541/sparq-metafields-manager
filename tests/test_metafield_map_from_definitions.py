from app import GOOGLE_SHOPPING_KEYS, metafield_map_from_definitions


def definition(owner, namespace, key, name=None):
    return {"Owner": owner, "Metafield namespace": namespace, "Metafield Key": key, "Name": name or key}


class TestMetafieldMapFromDefinitions:
    def test_product_owned_definition_is_included(self):
        result = metafield_map_from_definitions([definition("product", "custom", "ribbon_text", "Ribbon Text")])
        assert result == {("product", "custom", "ribbon_text"): "Ribbon Text (product.metafields.custom.ribbon_text)"}

    def test_variant_owned_definition_is_included(self):
        # Regression: variant-owned metafields used to be filtered out
        # entirely, so something like custom.product_variant_details never
        # had a column to export into.
        result = metafield_map_from_definitions([definition("variant", "custom", "product_variant_details", "Prod Var Details")])
        assert result == {
            ("variant", "custom", "product_variant_details"):
                "Prod Var Details (variant.metafields.custom.product_variant_details)"
        }

    def test_same_namespace_key_at_both_owner_levels_both_survive(self):
        # Regression: confirmed on a live store — the same namespace.key pair
        # can be defined at both product and variant level simultaneously.
        # Keying by (ns, key) alone would let one silently overwrite the other.
        defs = [
            definition("product", "custom", "product_variant_details", "Product Variant Details"),
            definition("variant", "custom", "product_variant_details", "Prod Var Details"),
        ]
        result = metafield_map_from_definitions(defs)
        assert len(result) == 2
        assert ("product", "custom", "product_variant_details") in result
        assert ("variant", "custom", "product_variant_details") in result

    def test_unrecognised_owner_is_skipped(self):
        result = metafield_map_from_definitions([definition("company", "custom", "a")])
        assert result == {}

    def test_google_shopping_keys_are_skipped(self):
        ns, key = next(iter(GOOGLE_SHOPPING_KEYS.values()))
        result = metafield_map_from_definitions([definition("product", ns, key)])
        assert result == {}

    def test_blank_namespace_or_key_is_skipped(self):
        result = metafield_map_from_definitions([
            definition("product", "", "a"), definition("product", "custom", ""),
        ])
        assert result == {}

    def test_missing_name_falls_back_to_key(self):
        row = {"Owner": "product", "Metafield namespace": "custom", "Metafield Key": "a"}
        result = metafield_map_from_definitions([row])
        assert result == {("product", "custom", "a"): "a (product.metafields.custom.a)"}
