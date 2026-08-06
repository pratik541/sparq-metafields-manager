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


def product_gid(product_id):
    return f"gid://shopify/Product/{product_id}"


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
