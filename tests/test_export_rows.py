from app import build_export_rows


def variant(sku, option1, option2="", price="0.00", image_id="", title="", position="",
           admin_graphql_api_id=""):
    return {
        "id": sku, "sku": sku, "option1": option1, "option2": option2,
        "price": price, "compare_at_price": "", "grams": 10,
        "inventory_management": "shopify", "inventory_quantity": 5,
        "inventory_policy": "deny", "fulfillment_service": "manual",
        "requires_shipping": True, "taxable": True, "barcode": "",
        "image_id": image_id, "weight_unit": "g",
        "title": title, "position": position, "admin_graphql_api_id": admin_graphql_api_id,
    }


def product(variants, images=None, options=None):
    return {
        "id": 1, "handle": "ring", "title": "Ring", "body_html": "", "vendor": "V",
        "product_type": "Ring", "tags": "", "published_at": "2020-01-01",
        "status": "active",
        "options": options if options is not None else [{"name": "Metal"}, {"name": "Size"}],
        "variants": variants,
        "images": images or [],
    }


class TestVariantRows:
    """A product's export must carry every variant, not just the first."""

    def test_each_variant_gets_its_own_row(self):
        p = product([
            variant("SKU-G-5", "Gold", "5", price="100.00", image_id=111),
            variant("SKU-WG-5", "White Gold", "5", price="110.00", image_id=112),
            variant("SKU-RG-6", "Rose Gold", "6", price="120.00", image_id=113),
        ])
        rows = build_export_rows(p, [], metafield_map={})

        assert [r["Variant SKU"] for r in rows] == ["SKU-G-5", "SKU-WG-5", "SKU-RG-6"]
        assert [r["Option1 Value"] for r in rows] == ["Gold", "White Gold", "Rose Gold"]
        assert [r["Option2 Value"] for r in rows] == ["5", "5", "6"]
        assert [r["Variant Price"] for r in rows] == ["100.00", "110.00", "120.00"]
        assert [r["Variant Image"] for r in rows] == [111, 112, 113]
        assert all(r["Handle"] == "ring" for r in rows)

    def test_product_level_fields_only_on_first_row(self):
        p = product([
            variant("SKU-G-5", "Gold", "5"),
            variant("SKU-WG-5", "White Gold", "5"),
        ])
        rows = build_export_rows(p, [], metafield_map={})

        assert rows[0]["Title"] == "Ring"
        assert rows[1]["Title"] == ""
        assert rows[1]["Vendor"] == ""
        assert rows[1]["Status"] == ""

    def test_metafields_only_populate_first_row(self):
        p = product([
            variant("SKU-G-5", "Gold", "5"),
            variant("SKU-WG-5", "White Gold", "5"),
        ])
        metafields = [{"namespace": "custom", "key": "material", "value": "18k"}]
        rows = build_export_rows(p, metafields, metafield_map={("custom", "material"): "Material (product.metafields.custom.material)"})

        assert rows[0]["Material (product.metafields.custom.material)"] == "18k"
        assert rows[1]["Material (product.metafields.custom.material)"] == ""

    def test_single_variant_product_still_yields_one_row(self):
        p = product([variant("SKU-ONLY", "Default Title")])
        rows = build_export_rows(p, [], metafield_map={})

        assert len(rows) == 1
        assert rows[0]["Variant SKU"] == "SKU-ONLY"

    def test_no_variants_still_yields_one_row(self):
        p = product([])
        rows = build_export_rows(p, [], metafield_map={})

        assert len(rows) == 1
        assert rows[0]["Variant SKU"] == ""

    def test_variant_rows_precede_extra_image_rows(self):
        p = product(
            [variant("SKU-G-5", "Gold", "5"), variant("SKU-WG-5", "White Gold", "5")],
            images=[{"src": "img1.jpg", "position": 1}, {"src": "img2.jpg", "position": 2}],
        )
        rows = build_export_rows(p, [], metafield_map={})

        assert len(rows) == 3  # 2 variants + 1 extra image row
        assert rows[0]["Variant SKU"] == "SKU-G-5"
        assert rows[1]["Variant SKU"] == "SKU-WG-5"
        assert rows[2]["Variant SKU"] == ""
        assert rows[2]["Image Src"] == "img2.jpg"


class TestNoExtras:
    """Without a fetch_native_extras_bulk result, every extra-native column
    falls back exactly the way it always did before that pass existed.
    """

    def test_product_category_falls_back_to_product_type(self):
        p = product([variant("SKU-G-5", "Gold")])
        rows = build_export_rows(p, [], metafield_map={})
        assert rows[0]["Product Category"] == "Ring"

    def test_gift_card_defaults_to_false(self):
        p = product([variant("SKU-G-5", "Gold")])
        rows = build_export_rows(p, [], metafield_map={})
        assert rows[0]["Gift Card"] == "FALSE"

    def test_cost_and_customs_columns_blank(self):
        p = product([variant("SKU-G-5", "Gold")])
        rows = build_export_rows(p, [], metafield_map={})
        assert rows[0]["Cost per item"] == ""
        assert rows[0]["Variant Country Of Origin"] == ""
        assert rows[0]["Variant Requires Components"] == ""


class TestWithExtras:
    """fetch_native_extras_bulk's per-product dict, as build_export_rows expects it."""

    def extras(self, **overrides):
        base = {
            "category_full_name": "Apparel & Accessories > Jewelry > Rings",
            "is_gift_card": True,
            "template_suffix": "custom",
            "gift_card_template_suffix": "",
            "requires_selling_plan": False,
            "combined_listing_role": None,
            "variants": {},
        }
        base.update(overrides)
        return base

    def test_product_category_uses_real_taxonomy_name(self):
        p = product([variant("SKU-G-5", "Gold")])
        rows = build_export_rows(p, [], metafield_map={}, extras=self.extras())
        assert rows[0]["Product Category"] == "Apparel & Accessories > Jewelry > Rings"

    def test_gift_card_reflects_real_value(self):
        p = product([variant("SKU-G-5", "Gold")])
        rows = build_export_rows(p, [], metafield_map={}, extras=self.extras(is_gift_card=True))
        assert rows[0]["Gift Card"] == "TRUE"

    def test_product_level_extras_only_populate_first_row(self):
        p = product([variant("SKU-G-5", "Gold"), variant("SKU-WG-5", "White Gold")])
        rows = build_export_rows(p, [], metafield_map={}, extras=self.extras())
        assert rows[0]["Template Suffix"] == "custom"
        assert rows[1]["Template Suffix"] == ""

    def test_variant_level_extras_matched_by_variant_id(self):
        p = product([
            variant("SKU-G-5", "Gold"),
            variant("SKU-WG-5", "White Gold"),
        ])
        extras = self.extras(variants={
            "SKU-G-5": {
                "unit_cost": "150.00", "country_code_of_origin": "IN",
                "harmonized_system_code": "7113", "province_code_of_origin": "MH",
                "requires_components": False, "show_unit_price": True,
            },
        })
        rows = build_export_rows(p, [], metafield_map={}, extras=extras)
        # Matched variant gets its own extras...
        assert rows[0]["Cost per item"] == "150.00"
        assert rows[0]["Variant Country Of Origin"] == "IN"
        assert rows[0]["Variant Requires Components"] == "FALSE"
        assert rows[0]["Variant Show Unit Price"] == "TRUE"
        # ...the unmatched one falls back to blank, not the matched variant's values.
        assert rows[1]["Cost per item"] == ""
        assert rows[1]["Variant Country Of Origin"] == ""


class TestVariantTitlePositionAndId:
    """Title, Position and the GID are free on every REST variant payload —
    they shouldn't need the extras pass at all, unlike the two below them.
    """

    def test_read_straight_from_rest_with_no_extras_needed(self):
        p = product([variant("SKU-G-5", "Gold", title="14K Yellow Gold / 0.15CT",
                             position=2, admin_graphql_api_id="gid://shopify/ProductVariant/999")])
        rows = build_export_rows(p, [], metafield_map={})
        assert rows[0]["Variant Title"] == "14K Yellow Gold / 0.15CT"
        assert rows[0]["Variant Position"] == 2
        assert rows[0]["Variant ID"] == "gid://shopify/ProductVariant/999"


class TestVariantAvailabilityExtras:
    def test_blank_without_extras(self):
        p = product([variant("SKU-G-5", "Gold")])
        rows = build_export_rows(p, [], metafield_map={})
        assert rows[0]["Variant Available For Sale"] == ""
        assert rows[0]["Variant Sellable Online Quantity"] == ""

    def test_populated_from_extras(self):
        p = product([variant("SKU-G-5", "Gold")])
        extras = {"variants": {"SKU-G-5": {
            "available_for_sale": True, "sellable_online_quantity": 7,
        }}}
        rows = build_export_rows(p, [], metafield_map={}, extras=extras)
        assert rows[0]["Variant Available For Sale"] == "TRUE"
        assert rows[0]["Variant Sellable Online Quantity"] == 7

    def test_zero_sellable_quantity_is_not_treated_as_blank(self):
        # Regression guard: 0 is falsy in Python but a real, meaningful value
        # here (out of stock), not "unknown" — must not collapse to "".
        p = product([variant("SKU-G-5", "Gold")])
        extras = {"variants": {"SKU-G-5": {"sellable_online_quantity": 0}}}
        rows = build_export_rows(p, [], metafield_map={}, extras=extras)
        assert rows[0]["Variant Sellable Online Quantity"] == 0


class TestVariantOwnedMetafields:
    """Variant-owned metafields (e.g. custom.product_variant_details) get
    their own column, populated per-variant from fetch_variant_metafields_bulk
    — not from the product-level metafields list, and not just on row 0.
    """

    def test_populated_on_the_matching_variant(self):
        p = product([variant("SKU-G-5", "Gold")])
        vmap = {("custom", "product_variant_details"): "Product Variant Details (variant.metafields.custom.product_variant_details)"}
        vmf_by_id = {"SKU-G-5": [{"namespace": "custom", "key": "product_variant_details", "value": "Diamond Shape: Round"}]}
        rows = build_export_rows(p, [], metafield_map={},
                                 variant_metafield_map=vmap, variant_metafields_by_id=vmf_by_id)
        assert rows[0]["Product Variant Details (variant.metafields.custom.product_variant_details)"] == "Diamond Shape: Round"

    def test_each_variant_gets_its_own_value_not_just_the_first(self):
        p = product([
            variant("SKU-G-5", "Gold"),
            variant("SKU-WG-5", "White Gold"),
        ])
        vmap = {("custom", "product_variant_details"): "Details"}
        vmf_by_id = {
            "SKU-G-5": [{"namespace": "custom", "key": "product_variant_details", "value": "Gold details"}],
            "SKU-WG-5": [{"namespace": "custom", "key": "product_variant_details", "value": "White gold details"}],
        }
        rows = build_export_rows(p, [], metafield_map={},
                                 variant_metafield_map=vmap, variant_metafields_by_id=vmf_by_id)
        assert rows[0]["Details"] == "Gold details"
        assert rows[1]["Details"] == "White gold details"

    def test_blank_when_not_fetched(self):
        p = product([variant("SKU-G-5", "Gold")])
        vmap = {("custom", "product_variant_details"): "Details"}
        rows = build_export_rows(p, [], metafield_map={}, variant_metafield_map=vmap)
        assert rows[0]["Details"] == ""

    def test_product_and_variant_definitions_with_the_same_namespace_key_dont_collide(self):
        # Regression guard: custom.product_variant_details exists as both a
        # product-owned and a separate variant-owned definition on a live
        # store — they must populate independently, not overwrite each other.
        p = product([variant("SKU-G-5", "Gold")])
        product_map = {("custom", "product_variant_details"): "Product Variant Details (product.metafields.custom.product_variant_details)"}
        variant_map = {("custom", "product_variant_details"): "Product Variant Details (variant.metafields.custom.product_variant_details)"}
        product_metafields = [{"namespace": "custom", "key": "product_variant_details", "value": "Product-level text"}]
        vmf_by_id = {"SKU-G-5": [{"namespace": "custom", "key": "product_variant_details", "value": "Variant-level text"}]}
        rows = build_export_rows(p, product_metafields, metafield_map=product_map,
                                 variant_metafield_map=variant_map, variant_metafields_by_id=vmf_by_id)
        assert rows[0]["Product Variant Details (product.metafields.custom.product_variant_details)"] == "Product-level text"
        assert rows[0]["Product Variant Details (variant.metafields.custom.product_variant_details)"] == "Variant-level text"
