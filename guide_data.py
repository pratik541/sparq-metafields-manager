"""Lookup table for the Guide tab.

Answers one question: "I want to change X — what do I put in my CSV?"
So nobody has to open Shopify admin to find a metafield key.

Plain data only, no Streamlit, so it can be rendered or exported anywhere.
"""

# Each row: what the user wants to change, which tab does it, and the exact
# thing they type into the CSV.
GUIDE_ROWS = [
    # ── Prices and money ──────────────────────────────────────────────
    {
        "I want to change": "The real selling price (checkout price)",
        "Use this tab": "Update Native Fields",
        "Put this in your CSV": "Variant Price",
        "Kind": "Native column",
        "Type / allowed values": "Number. ₹ and commas are fine",
        "Example": "287093",
    },
    {
        "I want to change": "The displayed price (theme only, not checkout)",
        "Use this tab": "Update Metafields / Bulk Update",
        "Put this in your CSV": "custom.display_price",
        "Kind": "Metafield",
        "Type / allowed values": "Check the type in Shopify admin once, then reuse it",
        "Example": "287093",
    },
    {
        "I want to change": "The struck-through / MRP price",
        "Use this tab": "Update Native Fields",
        "Put this in your CSV": "Variant Compare At Price",
        "Kind": "Native column",
        "Type / allowed values": "Number, or CLEAR to empty it",
        "Example": "300000",
    },
    {
        "I want to change": "Cost per item (what you paid)",
        "Use this tab": "Update Native Fields",
        "Put this in your CSV": "Cost per item",
        "Kind": "Native column",
        "Type / allowed values": "Number",
        "Example": "150000",
    },
    # ── Product page content ──────────────────────────────────────────
    {
        "I want to change": "Product name / title",
        "Use this tab": "Update Native Fields",
        "Put this in your CSV": "Title",
        "Kind": "Native column",
        "Type / allowed values": "Text",
        "Example": "Arias Brilliant Linear Diamond Earrings",
    },
    {
        "I want to change": "Main product description (the Shopify one)",
        "Use this tab": "Update Native Fields",
        "Put this in your CSV": "Body (HTML)",
        "Kind": "Native column",
        "Type / allowed values": "HTML text",
        "Example": "<p>14K gold diamond earrings</p>",
    },
    {
        "I want to change": "The extra product details block",
        "Use this tab": "Update Metafields / Bulk Update",
        "Put this in your CSV": "custom.product_details",
        "Kind": "Metafield",
        "Type / allowed values": "rich_text_field",
        "Example": "Handcrafted in 14K gold",
    },
    {
        "I want to change": "Details for one specific SKU only",
        "Use this tab": "Update Metafields / Bulk Update",
        "Put this in your CSV": "custom.prod_var_details",
        "Kind": "Metafield (variant level)",
        "Type / allowed values": "rich_text_field",
        "Example": "4.91 CT, VVS clarity",
    },
    {
        "I want to change": "Badge / ribbon text on the product card",
        "Use this tab": "Update Metafields / Bulk Update",
        "Put this in your CSV": "custom.ribbon_text",
        "Kind": "Metafield",
        "Type / allowed values": "single_line_text_field",
        "Example": "Best Seller",
    },
    # ── Social proof ──────────────────────────────────────────────────
    {
        "I want to change": "Star rating shown on the product",
        "Use this tab": "Update Metafields / Bulk Update",
        "Put this in your CSV": "custom.product_rating",
        "Kind": "Metafield",
        "Type / allowed values": "number_decimal",
        "Example": "4.5",
    },
    {
        "I want to change": "Happy shoppers count",
        "Use this tab": "Update Metafields / Bulk Update",
        "Put this in your CSV": "custom.happy_shoppers",
        "Kind": "Metafield",
        "Type / allowed values": "number_integer (whole number)",
        "Example": "1250",
    },
    {
        "I want to change": "Loved by customers count",
        "Use this tab": "Update Metafields / Bulk Update",
        "Put this in your CSV": "custom.loved_by_customers",
        "Kind": "Metafield",
        "Type / allowed values": "number_integer (whole number)",
        "Example": "340",
    },
    # ── Catalogue / organisation ──────────────────────────────────────
    {
        "I want to change": "Brand / vendor",
        "Use this tab": "Update Native Fields",
        "Put this in your CSV": "Vendor",
        "Kind": "Native column",
        "Type / allowed values": "Text",
        "Example": "Arias",
    },
    {
        "I want to change": "Product type label",
        "Use this tab": "Update Native Fields",
        "Put this in your CSV": "Type",
        "Kind": "Native column",
        "Type / allowed values": "Text",
        "Example": "Earrings",
    },
    {
        "I want to change": "Tags",
        "Use this tab": "Update Native Fields",
        "Put this in your CSV": "Tags",
        "Kind": "Native column",
        "Type / allowed values": "Comma separated. Replaces all existing tags",
        "Example": "gold, diamond, earrings",
    },
    {
        "I want to change": "Active / draft / archived",
        "Use this tab": "Update Native Fields",
        "Put this in your CSV": "Status",
        "Kind": "Native column",
        "Type / allowed values": "ACTIVE, DRAFT or ARCHIVED",
        "Example": "ACTIVE",
    },
    # ── Inventory and shipping ────────────────────────────────────────
    {
        "I want to change": "Barcode",
        "Use this tab": "Update Native Fields",
        "Put this in your CSV": "Variant Barcode",
        "Kind": "Native column",
        "Type / allowed values": "Text, or CLEAR to empty it",
        "Example": "8901234567890",
    },
    {
        "I want to change": "Weight",
        "Use this tab": "Update Native Fields",
        "Put this in your CSV": "Variant Grams",
        "Kind": "Native column",
        "Type / allowed values": "Grams only. Variant Weight Unit is ignored",
        "Example": "4500",
    },
    {
        "I want to change": "Sell when out of stock",
        "Use this tab": "Update Native Fields",
        "Put this in your CSV": "Variant Inventory Policy",
        "Kind": "Native column",
        "Type / allowed values": "CONTINUE = allow, DENY = block",
        "Example": "CONTINUE",
    },
    {
        "I want to change": "Track inventory on / off",
        "Use this tab": "Update Native Fields",
        "Put this in your CSV": "Variant Inventory Tracker",
        "Kind": "Native column",
        "Type / allowed values": "shopify = track, false = do not track",
        "Example": "shopify",
    },
    {
        "I want to change": "Charge tax on this item",
        "Use this tab": "Update Native Fields",
        "Put this in your CSV": "Variant Taxable",
        "Kind": "Native column",
        "Type / allowed values": "TRUE or FALSE",
        "Example": "TRUE",
    },
    {
        "I want to change": "Tax code",
        "Use this tab": "Update Native Fields",
        "Put this in your CSV": "Variant Tax Code",
        "Kind": "Native column",
        "Type / allowed values": "Text. May need Shopify Plus",
        "Example": "PC040100",
    },
    {
        "I want to change": "This is a physical product needing shipping",
        "Use this tab": "Update Native Fields",
        "Put this in your CSV": "Variant Requires Shipping",
        "Kind": "Native column",
        "Type / allowed values": "TRUE or FALSE",
        "Example": "TRUE",
    },
    # ── SEO ───────────────────────────────────────────────────────────
    {
        "I want to change": "SEO page title",
        "Use this tab": "Update Native Fields",
        "Put this in your CSV": "SEO Title",
        "Kind": "Native column",
        "Type / allowed values": "Text",
        "Example": "Buy Gold Diamond Earrings",
    },
    {
        "I want to change": "SEO meta description",
        "Use this tab": "Update Native Fields",
        "Put this in your CSV": "SEO Description",
        "Kind": "Native column",
        "Type / allowed values": "Text",
        "Example": "Certified lab grown diamond earrings in 14K gold",
    },
    # ── Shopify standard taxonomy metafields ──────────────────────────
    {
        "I want to change": "Jewellery type (Shopify category field)",
        "Use this tab": "Update Metafields / Bulk Update",
        "Put this in your CSV": "shopify.jewelry-type",
        "Kind": "Metafield",
        "Type / allowed values": "single_line_text_field",
        "Example": "Earrings",
    },
    {
        "I want to change": "Jewellery material",
        "Use this tab": "Update Metafields / Bulk Update",
        "Put this in your CSV": "shopify.jewelry-material",
        "Kind": "Metafield",
        "Type / allowed values": "single_line_text_field",
        "Example": "14K Yellow Gold",
    },
    {
        "I want to change": "Earring design",
        "Use this tab": "Update Metafields / Bulk Update",
        "Put this in your CSV": "shopify.earring-design",
        "Kind": "Metafield",
        "Type / allowed values": "single_line_text_field",
        "Example": "Drop",
    },
    {
        "I want to change": "Colour",
        "Use this tab": "Update Metafields / Bulk Update",
        "Put this in your CSV": "shopify.color-pattern",
        "Kind": "Metafield",
        "Type / allowed values": "single_line_text_field",
        "Example": "Gold",
    },
    {
        "I want to change": "Target gender",
        "Use this tab": "Update Metafields / Bulk Update",
        "Put this in your CSV": "shopify.target-gender",
        "Kind": "Metafield",
        "Type / allowed values": "single_line_text_field",
        "Example": "Female",
    },
    {
        "I want to change": "Age group",
        "Use this tab": "Update Metafields / Bulk Update",
        "Put this in your CSV": "shopify.age-group",
        "Kind": "Metafield",
        "Type / allowed values": "single_line_text_field",
        "Example": "Adult",
    },
    {
        "I want to change": "Google Shopping custom product flag",
        "Use this tab": "Update Metafields / Bulk Update",
        "Put this in your CSV": "mm-google-shopping.custom_product",
        "Kind": "Metafield",
        "Type / allowed values": "boolean — TRUE or FALSE",
        "Example": "FALSE",
    },
]

GUIDE_COLUMNS = [
    "I want to change",
    "Use this tab",
    "Put this in your CSV",
    "Kind",
    "Type / allowed values",
    "Example",
]


def native_sample_rows():
    """Sample rows for a native-fields CSV, ready to edit and upload."""
    return [
        {
            "Variant SKU": "SPLDT19906-14KY-4.91CT",
            "Variant Price": "287093",
            "Variant Compare At Price": "300000",
            "Cost per item": "",
            "Variant Barcode": "",
            "Tags": "",
            "Status": "",
        },
        {
            "Variant SKU": "SQT19349-EG-925S-0.8CT",
            "Variant Price": "8999",
            "Variant Compare At Price": "CLEAR",
            "Cost per item": "4500",
            "Variant Barcode": "",
            "Tags": "silver, earrings",
            "Status": "ACTIVE",
        },
    ]
