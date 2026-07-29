# Update Native Shopify Fields

Use **Update Native Fields** to change existing Shopify product and variant fields from a CSV. It is separate from metafield updates so a price column can never be applied by accident during a metafield run.

1. Export products, edit only the fields you intend to change, and upload the CSV.
2. Use `Variant SKU` as the preferred identifier; `Handle` is supported as a fallback.
3. Select **Create dry-run preview**. Review current and proposed values before selecting **Apply native field updates**.

Blank cells (including `nan` and `none`) leave the existing Shopify value untouched. To deliberately clear a compare-at price or barcode, enter `CLEAR`.

Supported variant fields are price, compare-at price, barcode, taxable, tax code, inventory policy, cost per item, grams, requires shipping, and inventory tracking. Supported product fields are title, description, vendor, type, tags, status, SEO title, and SEO description.

`Variant Grams` is always treated as grams; `Variant Weight Unit` is ignored to avoid changing a weight by a factor of 1,000. Price updates do not update a separate Display Price metafield.

For the first run, set **Limit to first N rows** to a small number such as 3–5. Results are available as downloadable CSV files for successful, failed, skipped, not-found, and invalid rows.
