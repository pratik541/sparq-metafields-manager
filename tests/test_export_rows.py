from app import build_export_rows


def variant(sku, option1, option2="", price="0.00", image_id=""):
    return {
        "id": sku, "sku": sku, "option1": option1, "option2": option2,
        "price": price, "compare_at_price": "", "grams": 10,
        "inventory_management": "shopify", "inventory_quantity": 5,
        "inventory_policy": "deny", "fulfillment_service": "manual",
        "requires_shipping": True, "taxable": True, "barcode": "",
        "image_id": image_id, "weight_unit": "g",
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
