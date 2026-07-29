"""Read the store's real metafield definitions.

The app hardcodes a metafield list, and that list is known to be incomplete
(it has no custom.display_price) and possibly wrong (it types the shopify.*
category metafields as single_line_text_field, but those are metaobject
references). This module asks the store instead.

The point of the output is copy-paste: the Owner column holds exactly the
value the update CSV expects ("product" or "variant"), and the type is
whatever Shopify actually stores, not a guess.

No Streamlit imports, so it can be tested without a UI.
"""

import requests

API_VER = "2025-01"

# One request, two aliased queries — same aliasing trick used for the native
# field mutations. metafieldDefinitions is paginated; 250 is the per-page max
# and is far above the number of definitions any of these stores has.
DEFINITIONS_QUERY = """
{
  product: metafieldDefinitions(first: 250, ownerType: PRODUCT) {
    edges { node { name namespace key description type { name } } }
  }
  variant: metafieldDefinitions(first: 250, ownerType: PRODUCTVARIANT) {
    edges { node { name namespace key description type { name } } }
  }
}
"""

# GraphQL alias -> the value the CSV "Owner" column expects.
OWNER_LABELS = {"product": "product", "variant": "variant"}

DEFINITION_COLUMNS = [
    "Name",
    "Owner",
    "Metafield namespace",
    "Metafield Key",
    "Metafield type",
    "Description",
]


def _rows_from_alias(payload, alias):
    """Flatten one aliased metafieldDefinitions connection into CSV-shaped rows."""
    connection = payload.get(alias) or {}
    rows = []
    for edge in connection.get("edges") or []:
        node = edge.get("node") or {}
        rows.append({
            "Name": node.get("name", ""),
            "Owner": OWNER_LABELS[alias],
            "Metafield namespace": node.get("namespace", ""),
            "Metafield Key": node.get("key", ""),
            "Metafield type": (node.get("type") or {}).get("name", ""),
            "Description": node.get("description") or "",
        })
    return rows


def fetch_metafield_definitions(headers, store_url, http_post=None):
    """Return (rows, error).

    rows is a list of dicts keyed by DEFINITION_COLUMNS, product definitions
    first then variant. error is None on success, or a message to show the user.
    """
    post = http_post or requests.post
    url = f"https://{store_url}/admin/api/{API_VER}/graphql.json"

    try:
        resp = post(url, headers=headers,
                    json={"query": DEFINITIONS_QUERY}, timeout=60)
    except Exception as exc:  # network error, DNS, timeout
        return [], f"Could not reach Shopify: {exc}"

    if resp.status_code != 200:
        return [], f"Shopify returned HTTP {resp.status_code}: {resp.text[:160]}"

    try:
        body = resp.json()
    except ValueError:
        return [], "Shopify returned a response that was not JSON"

    errors = body.get("errors") or []
    if errors:
        return [], str(errors[0].get("message", "GraphQL error"))[:200]

    payload = body.get("data") or {}
    if not payload:
        return [], "Shopify returned no definition data"

    rows = _rows_from_alias(payload, "product") + _rows_from_alias(payload, "variant")
    if not rows:
        return [], "No metafield definitions are set up on this store"

    return rows, None
