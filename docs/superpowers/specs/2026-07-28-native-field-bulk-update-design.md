# Native Field Bulk Update — Design

**Date:** 2026-07-28
**Status:** Approved for planning

## Problem

The app updates metafields only. Native Shopify fields — most importantly variant
`price` — cannot be changed on products that already exist in the store.

`price` is written in exactly one place, `create_product()` at `app.py:344`, and that
function only runs when a SKU is *not* found in the store. For an existing product the
import loop hits `app.py:708-711`, logs `"Already exists — updating metafields only"`,
and discards the `Variant Price` value from the CSV row without warning.

The other four tabs cannot help:

- Export tab reads `Variant Price` out to CSV (`app.py:454`) with no write path back
- View Products displays price read-only (`app.py:854`)
- Update Metafields and Bulk Update call metafield endpoints exclusively

Consequence: prices are changed by hand in Shopify admin, one product at a time.
A `Display Price` metafield *can* be bulk-updated today — because the Update/Bulk tabs
take namespace, key, and type generically from CSV columns (`app.py:1263-1265`) — so the
displayed price and the real price can drift apart with no tooling to correct it.

## Goal

Bulk-update native product and variant fields from a CSV, with the same reliability
characteristics the Bulk Update tab already has: O(1) SKU lookup, batched GraphQL,
rate-limit retry, and per-row result reporting.

## Non-goals (v1)

| Excluded | Reason |
|---|---|
| `Variant Inventory Qty` | Needs `inventorySetQuantities` plus location IDs; blank-vs-zero is destructive |
| Rewriting `Variant SKU` | SKU is the lookup key used to find the row's target |
| Images, option names/values | Separate mutations, no current demand |
| `Display Price` metafield sync | Explicitly deferred by user; existing tabs already cover it |
| Google Shopping columns | Already metafields, handled by existing tabs |

## Approach

**New tab 6 "Update Native Fields" backed by a new `native_update.py` module.**

Rejected alternatives:

- *Extend tab 5 to detect native columns in the same CSV.* One button would fire two
  unrelated mutation families; a stray price column would take effect during a metafield
  run. Rejected on blast radius.
- *REST `PUT /variants/{id}.json` per row.* Shopify has deprecated variant writes through
  the product REST endpoint, and it costs one HTTP call per row. Rejected.

`app.py` is already ~1400 lines. Mutation building, batching, and sending live in
`native_update.py`; tab 6 in `app.py` stays thin UI — upload, validate, render, download.
This mirrors how `bulk_update.py` already sits beside the app.

## Field mapping

Column names match the existing template (`app.py:223-254`) so that
**Export tab → edit in Excel → upload to tab 6** round-trips without renaming.

### Variant level — `productVariantsBulkUpdate`

| CSV column | GraphQL path |
|---|---|
| `Variant Price` | `price` |
| `Variant Compare At Price` | `compareAtPrice` |
| `Variant Barcode` | `barcode` |
| `Variant Taxable` | `taxable` |
| `Variant Tax Code` | `taxCode` |
| `Variant Inventory Policy` | `inventoryPolicy` (`DENY` / `CONTINUE`) |
| `Cost per item` | `inventoryItem.cost` |
| `Variant Grams` + `Variant Weight Unit` | `inventoryItem.measurement.weight.{value,unit}` |
| `Variant Requires Shipping` | `inventoryItem.requiresShipping` |
| `Variant Inventory Tracker` | `inventoryItem.tracked` (`shopify`/`true`/`1`/`yes` → true; `false`/`0`/`no`/`untracked` → false; anything else is a row error) |

### Product level — `productUpdate`

| CSV column | GraphQL path |
|---|---|
| `Title` | `title` |
| `Body (HTML)` | `descriptionHtml` |
| `Vendor` | `vendor` |
| `Type` | `productType` |
| `Tags` | `tags` (comma-split into a list) |
| `Status` | `status` (`ACTIVE` / `DRAFT` / `ARCHIVED`) |
| `SEO Title` | `seo.title` |
| `SEO Description` | `seo.description` |

### Value coercion

Handled by a `coerce_native_value(column, raw)` function, mirroring the role
`format_value_bulk()` plays for metafields:

- Money (`price`, `compareAtPrice`, `cost`): strip `₹`, `,`, and whitespace; validate as
  decimal; send as a string
- Booleans (`taxable`, `requiresShipping`): `true/1/yes` → `true`, else `false`
- Weight: `Variant Grams` is **always grams**, per Shopify's export format, so it is sent
  as `{value: <grams>, unit: GRAMS}`. `Variant Weight Unit` is a display preference and is
  **not** used to reinterpret the number — treating `Grams=1000, Weight Unit=kg` as
  1000 kg would be a 1000x error. `Variant Weight Unit` is therefore ignored by this tab,
  and the UI states so.
- Enums (`status`, `inventoryPolicy`): uppercased, validated against the allowed set; an
  unrecognised value fails that row rather than guessing
- A value that fails coercion becomes a **failed row with a reason**, never a silent skip

## Safety rules

These are the core requirements, not polish. A wrong run against 40k rows is expensive.

1. **Blank / `nan` / `"nan"` cell → field untouched.** Never written as empty.
2. **Column absent from the CSV → field never touched at all.** A CSV with only
   `Variant SKU` and `Variant Price` sends only `price`.
3. **`CLEAR` sentinel.** Because blank means skip, deliberately blanking
   `Variant Compare At Price` requires the literal value `CLEAR`, which sends `null`.
   Supported on `compareAtPrice` and `Variant Barcode` only.
4. **Dry-run before apply.** Uploading produces a diff table — SKU, field, current store
   value, new value — plus a count of rows that would change, rows unchanged, and rows
   not found. Nothing is sent to Shopify until a separate **Apply** button is pressed.

   Current values come from the product cache already fetched for the lookup index, so
   the diff costs no extra API calls — but the REST `products.json` variant payload does
   **not** include `cost` or `tax_code`. Those two fields show `unknown` as the current
   value in the diff and are labelled "will be overwritten, current value not shown".
   Every other mapped field (price, compare-at, barcode, taxable, inventory policy,
   grams, requires shipping, tracker) is present in the payload and diffs exactly.
5. **Row limit for testing.** A "limit to first N rows" number input, so a change can be
   proven on 3-5 SKUs before running the full file.
6. **Rows that resolve to no fields are reported as skipped**, not sent as empty
   mutations.

## Resolution and batching

**Lookup index.** Reuse the pattern at `app.py:1236-1249`: one pass over the cached
products building `sku_map` (SKU → variant GID + product GID) and `handle_map`
(handle → product GID). Row targeting: `Variant SKU` first, `Handle` as fallback.

**Grouping.** `productVariantsBulkUpdate` takes one `productId` and a list of that
product's variants. Rows must therefore be grouped by parent product GID, then
`{productId, variants[]}` groups formed. This differs from `metafieldsSet`, which accepts
a flat list of 25 arbitrary owners.

**The single-variant problem.** This catalog is predominantly single-variant (noted in
`export_metafields.py:120`). Grouping alone yields one mutation per product — roughly
40,000 HTTP requests, hours of wall clock.

**Solution: GraphQL mutation aliasing.** Pack N product groups into one HTTP request:

```graphql
mutation NativeBulk($p0: ID!, $v0: [ProductVariantsBulkInput!]!, ...) {
  m0: productVariantsBulkUpdate(productId: $p0, variants: $v0) {
    productVariants { id }
    userErrors { field message }
  }
  m1: productVariantsBulkUpdate(productId: $p1, variants: $v1) { ... }
}
```

The query text is generated per batch since the alias count varies. `NATIVE_BATCH_SIZE`
starts at 10, defined as a module constant and tunable. Product-level `productUpdate`
calls are aliased the same way, in their own batch stream.

**Rate limits.** GraphQL Admin API uses a calculated-cost bucket (1000 points for
standard plans, 2000 for Plus, restoring at 100/s and 200/s respectively). Mutations
cost roughly 10 points each, so ~10 aliased mutations per request with the existing
inter-batch sleep stays within budget. The retry loop from `app.py:1332-1344` is reused
verbatim in shape: HTTP 429 → sleep 3s; GraphQL `THROTTLED` extension → sleep
`retryAfter + 0.5`; up to 3 attempts, then the whole batch is recorded as failed.

**Error attribution.** Because one HTTP request carries many aliased mutations, each
alias maps back to its product group so `userErrors` are attributed to the right rows.
A batch-level HTTP failure marks every row in that batch failed with the HTTP reason.

## Reporting

Reuse the tab 5 result structure — four dataframes, each with a CSV download:

- **Success** — SKU, product title, field, old value, new value
- **Failed** — same plus the Shopify `userErrors` message
- **Skipped** — with reason (`empty value`, `no updatable fields in row`)
- **Not found** — with reason (`SKU/handle not in store`)

Progress is reported per batch, not per row, matching tab 5 — per-row Streamlit updates
were the cause of the 40k-row slowdown fixed in commit `4d30621`.

## Verification

Mutation success is not proof the value landed. After a run, re-fetch the affected
products and compare each written field against the CSV value, reporting a
verified / mismatched count. Mismatches are listed with both values.

The verification re-fetch is limited to the products actually touched, not the whole
catalog.

## Risks

| Risk | Mitigation |
|---|---|
| `taxCode` may be Plus-only or require a tax service | Confirm against the store during implementation; if rejected, drop the column from the mapping and document it |
| `productUpdate` input shape differs by API version (`input:` in 2025-01 vs `product:` later) | App is pinned to 2025-01; verify the argument name against the live endpoint before wiring the mutation |
| Aliased-mutation cost could exceed the bucket on large batches | `NATIVE_BATCH_SIZE` is a tunable constant; the throttle retry catches overruns without data loss |
| A user uploads a metafield CSV to tab 6 by mistake | Validate that at least one recognised native column is present; refuse the file otherwise with a clear message |
| Price changed natively while a `Display Price` metafield still shows the old value | Out of scope per user decision; noted in the tab UI as a caution |

## Module boundaries

**`native_update.py`** — no Streamlit imports, so it stays unit-testable:

- `NATIVE_VARIANT_FIELDS`, `NATIVE_PRODUCT_FIELDS` — column → GraphQL path maps
- `coerce_native_value(column, raw)` → `(value, error)`
- `build_variant_input(row)` / `build_product_input(row)` → dict of only present fields
- `group_by_product(resolved_rows)` → list of `{productId, variants[], meta[]}`
- `build_aliased_mutation(groups)` → `(query_string, variables)`
- `send_native_batch(headers, gql_url, query, variables, meta)` → `(successes, failures)`
- `diff_rows(resolved_rows, products_cache)` → dry-run diff records

**`app.py` tab 6** — uploader, column validation, dry-run table, Apply button, progress,
result tables, downloads. No mutation logic.

## Testing

1. Unit tests for `coerce_native_value` covering money with `₹`/commas, booleans, enums,
   the `CLEAR` sentinel, blanks, and malformed input
2. Unit tests for `build_variant_input` proving absent and blank columns produce no key
3. Unit test for `build_aliased_mutation` asserting alias count, variable names, and
   correct meta-to-alias mapping
4. Live test against a single known SKU (`SPLDT19906-14KY-4.91CT`), changing price and
   confirming in Shopify admin
5. Live test with the row limit set to 5, confirming exactly 5 products change
6. Live test of a CSV containing a blank `Variant Compare At Price`, confirming the
   existing compare-at value is unchanged
