"""Bulk-fetch product metafield values via GraphQL.

Companion to metafield_definitions.py (which reads definitions, not values)
and native_update.py (which writes native fields via aliased mutations). The
export tab used to make one REST call per product just to read its
metafields; this module fetches many products' metafields in a single
GraphQL request instead, using the same aliased-field trick native_update.py
uses for its mutations: one `product(id:)` field per product, each under its
own alias, in a single query.

That aliasing is not just a batching convenience here — it's a correctness
requirement. The obvious alternative, a single `nodes(ids: [...])` query with
an inline `... on Product { metafields }` fragment, reliably returns an empty
metafields connection for every product, even when the same product queried
directly via `product(id:)` returns real values. Confirmed against a live
store: identical product ID, moments apart, `nodes(ids:)` returned zero
metafields while `product(id:)` returned ten, real rich-text values included.
So batching goes through aliased `product(id:)` fields, never `nodes(ids:)`.

No Streamlit imports, so it can be tested without a UI.
"""

import time

import requests

from native_update import extract_cost

API_VER = "2025-01"

# Each product's metafields(first: N) connection costs roughly N points, so
# batch_size * PRODUCT_METAFIELDS_FIRST is kept well under the 1000-point
# GraphQL bucket, mirroring the headroom native_update.py budgets for mutations.
PRODUCT_METAFIELDS_FIRST = 50
METAFIELD_FETCH_BATCH_SIZE = 10

# Stay under the 1000-point bucket with headroom for a throttle retry.
GRAPHQL_COST_BUDGET = 900

MAX_ATTEMPTS = 3

# How many variants to ask for per product when fetching the native-field
# extras below. Generous for any realistic catalog; a product with more
# variants than this just gets extras for its first VARIANTS_FIRST, the same
# "best effort, don't fail the batch" tradeoff PRODUCT_METAFIELDS_FIRST makes.
VARIANTS_FIRST = 100
EXTRAS_FETCH_BATCH_SIZE = max(1, min(50, GRAPHQL_COST_BUDGET // (VARIANTS_FIRST + 10)))

# Variant-level metafields nest a metafields(first:) connection inside every
# variant of every product in the batch, so cost scales with
# VARIANT_METAFIELDS_FIRST * num_keys — much steeper than the flat per-product
# fetch above. Kept smaller than VARIANTS_FIRST for that reason; most products
# have far fewer variants than this, so it's a real-world non-issue, not a
# silent truncation in practice.
VARIANT_METAFIELDS_FIRST = 25


def variant_metafields_batch_size_for(num_selected_keys):
    """Products to request per GraphQL call for the variant-metafields pass.

    Unlike batch_size_for, there's no "fetch everything" mode here — the cost
    of an unfiltered metafields(first: N) nested inside every variant of every
    product in a batch would blow the budget immediately, so callers only run
    this pass at all when num_selected_keys > 0.
    """
    if not num_selected_keys:
        return 1
    return max(1, min(50, GRAPHQL_COST_BUDGET // (VARIANT_METAFIELDS_FIRST * (num_selected_keys + 2))))


def product_gid(product_id):
    return f"gid://shopify/Product/{product_id}"


def _variant_id_from_gid(gid):
    return int(gid.rsplit("/", 1)[-1])


def _normalize_key(node):
    """Strip a leaked namespace prefix off a metafield's key.

    Confirmed against a live store: when the query filters with `keys:
    [...]`, Shopify echoes each result's `key` back in combined
    "namespace.key" form (matching the docs: "will be returned in the same
    format") instead of the bare key an unfiltered query returns. Every
    caller (metafield_map, build_export_rows) keys its lookups on the bare
    key, so the mismatch silently missed every filtered lookup — the data
    was fetched correctly, just filed under the wrong key.
    """
    ns, key = node["namespace"], node["key"]
    prefix = f"{ns}."
    if key.startswith(prefix):
        key = key[len(prefix):]
    return {"namespace": ns, "key": key, "value": node["value"]}


def _first_for(keys):
    """The `first` value to request.

    When keys is given, it already bounds the maximum possible result count
    exactly — capping `first` below len(keys) would silently truncate real
    metafields past the cap, since metafields(first: N, keys: [...]) returns
    at most N results no matter how many keys matched. Only the unfiltered
    case (keys is None/empty) needs a guessed ceiling.
    """
    if not keys:
        return PRODUCT_METAFIELDS_FIRST
    return len(keys)


def batch_size_for(num_selected_keys):
    """Products to request per GraphQL call.

    Selecting fewer metafield columns means each product's metafields(first:)
    connection costs less, so more products fit in one request under the same
    cost budget. Falls back to the fixed, conservative batch size when the
    column count is unknown (0/None) — the old worst-case assumption of up to
    PRODUCT_METAFIELDS_FIRST metafields per product. Must mirror _first_for's
    uncapped `first` so batches stay correctly sized when many keys are
    selected (a smaller batch, not a truncated result, is the tradeoff).
    """
    if not num_selected_keys:
        return METAFIELD_FETCH_BATCH_SIZE
    return max(1, min(50, GRAPHQL_COST_BUDGET // (num_selected_keys + 2)))


def build_aliased_metafields_query(product_ids, first, keys):
    """Build one aliased `product(id:)` field per product in a single query.

    Returns (query, variables). Aliases are p0, p1, ... in the same order as
    product_ids, so the response can be matched back up positionally without
    needing to parse IDs back out of the result.
    Confirmed against a live store: explicitly sending `keys: null` is NOT
    equivalent to omitting the argument — Shopify's resolver returns zero
    metafields when `keys` is present in the query at all, even bound to
    null, instead of treating it as "no filter". So the `keys` argument (and
    its variable declaration) must be left out of the query text entirely
    when keys is falsy, not just set to None in the variables.
    """
    definitions, selections = ["$first: Int!"], []
    variables = {"first": first}
    metafields_args = "first: $first"
    if keys:
        definitions.append("$keys: [String!]!")
        variables["keys"] = keys
        metafields_args += ", keys: $keys"
    for index, pid in enumerate(product_ids):
        definitions.append(f"$id{index}: ID!")
        variables[f"id{index}"] = product_gid(pid)
        selections.append(
            f"  p{index}: product(id: $id{index}) {{\n"
            "    id\n"
            f"    metafields({metafields_args}) {{\n"
            "      edges { node { namespace key value } }\n"
            "    }\n"
            "  }"
        )
    query = "query ProductMetafieldsBulk(" + ", ".join(definitions) + ") {\n" + "\n".join(selections) + "\n}"
    return query, variables


def fetch_metafields_bulk(headers, store_url, product_ids, keys=None,
                          http_post=None, sleep=None, on_cost=None):
    """Fetch metafields for a batch of products in one GraphQL request.

    keys, if given, is a list of "namespace.key" strings — only those
    metafields are fetched (and counted against the query cost), letting
    callers who only need a few columns request smaller/cheaper batches via
    batch_size_for(). None fetches every metafield on the product, same as
    the old per-product REST call.

    Returns (metafields_by_id, error). metafields_by_id maps REST product id
    to a list of {"namespace", "key", "value"} dicts; products with no
    metafields are simply absent, matching the old per-product REST fetch's
    shape. error is None on success, else a message describing what went
    wrong — callers can fall back to per-product REST fetches for this batch.
    """
    if not product_ids:
        return {}, None

    post, pause = http_post or requests.post, sleep or time.sleep
    url = f"https://{store_url}/admin/api/{API_VER}/graphql.json"
    query, variables = build_aliased_metafields_query(product_ids, _first_for(keys), keys)

    for _attempt in range(MAX_ATTEMPTS):
        response = post(url, headers=headers,
                        json={"query": query, "variables": variables},
                        timeout=60)
        if response.status_code == 429:
            pause(3)
            continue
        if response.status_code != 200:
            return {}, f"HTTP {response.status_code}: {response.text[:160]}"

        data = response.json()
        if on_cost is not None:
            cost = extract_cost(data)
            if cost is not None:
                on_cost(cost)

        errors = data.get("errors") or []
        throttled = [e for e in errors if e.get("extensions", {}).get("code") == "THROTTLED"]
        if throttled:
            pause(float(throttled[0].get("extensions", {}).get("retryAfter", 2)) + 0.5)
            continue
        if errors:
            return {}, str(errors[0].get("message", "GraphQL error"))[:200]

        result = {}
        response_data = data.get("data") or {}
        for index, pid in enumerate(product_ids):
            node = response_data.get(f"p{index}")
            if not node:
                continue
            edges = ((node.get("metafields") or {}).get("edges")) or []
            metafields = [_normalize_key(edge["node"]) for edge in edges]
            if metafields:
                result[pid] = metafields
        return result, None

    return {}, f"Rate limited — gave up after {MAX_ATTEMPTS} attempts"


def build_aliased_extras_query(product_ids):
    """One aliased product(id:) field per product, asking for the native
    fields the REST products.json payload never carries at all: the real
    Standard Product Taxonomy category (REST only has the free-text product
    type), gift card status, template suffixes, and per-variant customs/cost
    data that otherwise requires a separate InventoryItem lookup.
    """
    definitions, selections = [], []
    variables = {}
    for index, pid in enumerate(product_ids):
        definitions.append(f"$id{index}: ID!")
        variables[f"id{index}"] = product_gid(pid)
        selections.append(
            f"  p{index}: product(id: $id{index}) {{\n"
            "    category { fullName }\n"
            "    isGiftCard\n"
            "    templateSuffix\n"
            "    giftCardTemplateSuffix\n"
            "    requiresSellingPlan\n"
            "    combinedListingRole\n"
            f"    variants(first: {VARIANTS_FIRST}) {{\n"
            "      edges { node {\n"
            "        id\n"
            "        availableForSale\n"
            "        sellableOnlineQuantity\n"
            "        requiresComponents\n"
            "        showUnitPrice\n"
            "        inventoryItem {\n"
            "          unitCost { amount }\n"
            "          countryCodeOfOrigin\n"
            "          harmonizedSystemCode\n"
            "          provinceCodeOfOrigin\n"
            "        }\n"
            "      } }\n"
            "    }\n"
            "  }"
        )
    query = ("query ProductNativeExtrasBulk(" + ", ".join(definitions) + ") {\n"
             + "\n".join(selections) + "\n}")
    return query, variables


def fetch_native_extras_bulk(headers, store_url, product_ids,
                             http_post=None, sleep=None, on_cost=None):
    """Fetch per-product/variant native fields not present in the REST export.

    Returns (extras_by_id, error). extras_by_id maps REST product id to a
    dict of product-level extras plus a "variants" dict keyed by REST variant
    id — see build_export_rows for exactly how each key is consumed. Products
    absent from the response are simply absent from the result. error is None
    on success, else a message describing what went wrong — callers can skip
    these extra columns for this batch and keep going, same fallback shape as
    fetch_metafields_bulk.
    """
    if not product_ids:
        return {}, None

    post, pause = http_post or requests.post, sleep or time.sleep
    url = f"https://{store_url}/admin/api/{API_VER}/graphql.json"
    query, variables = build_aliased_extras_query(product_ids)

    for _attempt in range(MAX_ATTEMPTS):
        response = post(url, headers=headers,
                        json={"query": query, "variables": variables},
                        timeout=60)
        if response.status_code == 429:
            pause(3)
            continue
        if response.status_code != 200:
            return {}, f"HTTP {response.status_code}: {response.text[:160]}"

        data = response.json()
        if on_cost is not None:
            cost = extract_cost(data)
            if cost is not None:
                on_cost(cost)

        errors = data.get("errors") or []
        throttled = [e for e in errors if e.get("extensions", {}).get("code") == "THROTTLED"]
        if throttled:
            pause(float(throttled[0].get("extensions", {}).get("retryAfter", 2)) + 0.5)
            continue
        if errors:
            return {}, str(errors[0].get("message", "GraphQL error"))[:200]

        result = {}
        response_data = data.get("data") or {}
        for index, pid in enumerate(product_ids):
            node = response_data.get(f"p{index}")
            if not node:
                continue

            variants_by_id = {}
            for edge in ((node.get("variants") or {}).get("edges")) or []:
                vnode = edge["node"]
                item = vnode.get("inventoryItem") or {}
                unit_cost = item.get("unitCost") or {}
                variants_by_id[_variant_id_from_gid(vnode["id"])] = {
                    "unit_cost": unit_cost.get("amount"),
                    "country_code_of_origin": item.get("countryCodeOfOrigin"),
                    "harmonized_system_code": item.get("harmonizedSystemCode"),
                    "province_code_of_origin": item.get("provinceCodeOfOrigin"),
                    "requires_components": vnode.get("requiresComponents"),
                    "show_unit_price": vnode.get("showUnitPrice"),
                    "available_for_sale": vnode.get("availableForSale"),
                    "sellable_online_quantity": vnode.get("sellableOnlineQuantity"),
                }

            category = node.get("category") or {}
            result[pid] = {
                "category_full_name": category.get("fullName"),
                "is_gift_card": node.get("isGiftCard"),
                "template_suffix": node.get("templateSuffix"),
                "gift_card_template_suffix": node.get("giftCardTemplateSuffix"),
                "requires_selling_plan": node.get("requiresSellingPlan"),
                "combined_listing_role": node.get("combinedListingRole"),
                "variants": variants_by_id,
            }
        return result, None

    return {}, f"Rate limited — gave up after {MAX_ATTEMPTS} attempts"


def build_aliased_variant_metafields_query(product_ids, keys):
    """One aliased product(id:) field per product, each asking for its own
    variants' metafields — Shopify has no cross-product "all variant
    metafields" query, so this nests one level deeper than
    build_aliased_metafields_query's flat per-product shape.

    keys is required: metafields(keys:) must be present to keep this query's
    cost bounded (see VARIANT_METAFIELDS_FIRST) — there's no unfiltered mode.
    """
    definitions, selections = ["$keys: [String!]!"], []
    variables = {"keys": keys}
    for index, pid in enumerate(product_ids):
        definitions.append(f"$id{index}: ID!")
        variables[f"id{index}"] = product_gid(pid)
        selections.append(
            f"  p{index}: product(id: $id{index}) {{\n"
            f"    variants(first: {VARIANT_METAFIELDS_FIRST}) {{\n"
            "      edges { node {\n"
            "        id\n"
            f"        metafields(first: {len(keys)}, keys: $keys) {{\n"
            "          edges { node { namespace key value } }\n"
            "        }\n"
            "      } }\n"
            "    }\n"
            "  }"
        )
    query = ("query VariantMetafieldsBulk(" + ", ".join(definitions) + ") {\n"
             + "\n".join(selections) + "\n}")
    return query, variables


def fetch_variant_metafields_bulk(headers, store_url, product_ids, keys,
                                  http_post=None, sleep=None, on_cost=None):
    """Fetch variant-level metafields for a batch of products in one request.

    keys must be non-empty — callers skip this fetch entirely when no
    variant-owned metafield columns are selected (see
    variant_metafields_batch_size_for's docstring for why there's no
    unfiltered mode).

    Returns (metafields_by_variant_id, error). metafields_by_variant_id maps
    REST variant id to a list of {"namespace", "key", "value"} dicts — the
    same shape fetch_metafields_bulk returns for products, so build_export_rows
    can treat product- and variant-level metafields identically once each is
    matched to the right row. Variants with no matching metafields are simply
    absent. error is None on success, else a message describing what went
    wrong — callers can skip these columns for this batch and keep going.
    """
    if not product_ids or not keys:
        return {}, None

    post, pause = http_post or requests.post, sleep or time.sleep
    url = f"https://{store_url}/admin/api/{API_VER}/graphql.json"
    query, variables = build_aliased_variant_metafields_query(product_ids, keys)

    for _attempt in range(MAX_ATTEMPTS):
        response = post(url, headers=headers,
                        json={"query": query, "variables": variables},
                        timeout=60)
        if response.status_code == 429:
            pause(3)
            continue
        if response.status_code != 200:
            return {}, f"HTTP {response.status_code}: {response.text[:160]}"

        data = response.json()
        if on_cost is not None:
            cost = extract_cost(data)
            if cost is not None:
                on_cost(cost)

        errors = data.get("errors") or []
        throttled = [e for e in errors if e.get("extensions", {}).get("code") == "THROTTLED"]
        if throttled:
            pause(float(throttled[0].get("extensions", {}).get("retryAfter", 2)) + 0.5)
            continue
        if errors:
            return {}, str(errors[0].get("message", "GraphQL error"))[:200]

        result = {}
        response_data = data.get("data") or {}
        for index, pid in enumerate(product_ids):
            node = response_data.get(f"p{index}")
            if not node:
                continue
            for edge in ((node.get("variants") or {}).get("edges")) or []:
                vnode = edge["node"]
                mf_edges = ((vnode.get("metafields") or {}).get("edges")) or []
                metafields = [_normalize_key(e["node"]) for e in mf_edges]
                if metafields:
                    result[_variant_id_from_gid(vnode["id"])] = metafields
        return result, None

    return {}, f"Rate limited — gave up after {MAX_ATTEMPTS} attempts"
