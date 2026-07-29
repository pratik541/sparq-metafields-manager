from metafield_definitions import (
    DEFINITION_COLUMNS,
    DEFINITIONS_QUERY,
    fetch_metafield_definitions,
)

HEADERS = {"X-Shopify-Access-Token": "tok"}
STORE = "example.myshopify.com"


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text="", raise_on_json=False):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self._raise_on_json = raise_on_json

    def json(self):
        if self._raise_on_json:
            raise ValueError("not json")
        return self._payload or {}


class FakePoster:
    def __init__(self, response=None, exc=None):
        self.response = response
        self.exc = exc
        self.calls = []

    def __call__(self, url, headers=None, json=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "json": json})
        if self.exc:
            raise self.exc
        return self.response


def node(name, namespace, key, type_name, description=None):
    return {"node": {
        "name": name, "namespace": namespace, "key": key,
        "description": description, "type": {"name": type_name},
    }}


def payload(product_nodes=(), variant_nodes=()):
    return {"data": {
        "product": {"edges": list(product_nodes)},
        "variant": {"edges": list(variant_nodes)},
    }}


class TestQueryShape:
    def test_asks_for_both_owner_types(self):
        assert "ownerType: PRODUCT" in DEFINITIONS_QUERY
        assert "ownerType: PRODUCTVARIANT" in DEFINITIONS_QUERY

    def test_asks_for_description_and_type(self):
        assert "description" in DEFINITIONS_QUERY
        assert "type { name }" in DEFINITIONS_QUERY


class TestSuccess:
    def test_uses_correct_api_version_and_url(self):
        poster = FakePoster(FakeResponse(payload=payload(
            product_nodes=[node("Rating", "custom", "product_rating", "number_decimal")]
        )))
        fetch_metafield_definitions(HEADERS, STORE, http_post=poster)
        assert poster.calls[0]["url"] == (
            "https://example.myshopify.com/admin/api/2025-01/graphql.json"
        )
        assert poster.calls[0]["headers"] == HEADERS

    def test_maps_product_definition_to_csv_shape(self):
        poster = FakePoster(FakeResponse(payload=payload(
            product_nodes=[node("Product Rating", "custom", "product_rating",
                                "number_decimal", "Star rating out of 5")]
        )))
        rows, error = fetch_metafield_definitions(HEADERS, STORE, http_post=poster)
        assert error is None
        assert rows == [{
            "Name": "Product Rating",
            "Owner": "product",
            "Metafield namespace": "custom",
            "Metafield Key": "product_rating",
            "Metafield type": "number_decimal",
            "Description": "Star rating out of 5",
        }]

    def test_variant_owner_label_is_variant(self):
        poster = FakePoster(FakeResponse(payload=payload(
            variant_nodes=[node("Display Price", "custom", "display_price", "money")]
        )))
        rows, error = fetch_metafield_definitions(HEADERS, STORE, http_post=poster)
        assert error is None
        assert rows[0]["Owner"] == "variant"
        assert rows[0]["Metafield type"] == "money"

    def test_product_rows_come_before_variant_rows(self):
        poster = FakePoster(FakeResponse(payload=payload(
            product_nodes=[node("A", "custom", "a", "single_line_text_field")],
            variant_nodes=[node("B", "custom", "b", "money")],
        )))
        rows, _ = fetch_metafield_definitions(HEADERS, STORE, http_post=poster)
        assert [r["Owner"] for r in rows] == ["product", "variant"]

    def test_null_description_becomes_empty_string(self):
        poster = FakePoster(FakeResponse(payload=payload(
            product_nodes=[node("A", "custom", "a", "money", description=None)]
        )))
        rows, _ = fetch_metafield_definitions(HEADERS, STORE, http_post=poster)
        assert rows[0]["Description"] == ""

    def test_every_row_has_all_expected_columns(self):
        poster = FakePoster(FakeResponse(payload=payload(
            product_nodes=[node("A", "custom", "a", "money")],
            variant_nodes=[node("B", "custom", "b", "money")],
        )))
        rows, _ = fetch_metafield_definitions(HEADERS, STORE, http_post=poster)
        for row in rows:
            assert list(row.keys()) == DEFINITION_COLUMNS


class TestFailures:
    def test_non_200_returns_error(self):
        poster = FakePoster(FakeResponse(status_code=401, text="unauthorized"))
        rows, error = fetch_metafield_definitions(HEADERS, STORE, http_post=poster)
        assert rows == []
        assert "HTTP 401" in error

    def test_graphql_error_returns_message(self):
        poster = FakePoster(FakeResponse(payload={
            "errors": [{"message": "Access denied for metafieldDefinitions"}]
        }))
        rows, error = fetch_metafield_definitions(HEADERS, STORE, http_post=poster)
        assert rows == []
        assert "Access denied" in error

    def test_network_exception_returns_error(self):
        poster = FakePoster(exc=OSError("connection reset"))
        rows, error = fetch_metafield_definitions(HEADERS, STORE, http_post=poster)
        assert rows == []
        assert "Could not reach Shopify" in error

    def test_non_json_response_returns_error(self):
        poster = FakePoster(FakeResponse(raise_on_json=True))
        rows, error = fetch_metafield_definitions(HEADERS, STORE, http_post=poster)
        assert rows == []
        assert "not JSON" in error

    def test_missing_data_key_returns_error(self):
        poster = FakePoster(FakeResponse(payload={}))
        rows, error = fetch_metafield_definitions(HEADERS, STORE, http_post=poster)
        assert rows == []
        assert "no definition data" in error

    def test_no_definitions_returns_error(self):
        poster = FakePoster(FakeResponse(payload=payload()))
        rows, error = fetch_metafield_definitions(HEADERS, STORE, http_post=poster)
        assert rows == []
        assert "No metafield definitions" in error

    def test_missing_alias_does_not_crash(self):
        poster = FakePoster(FakeResponse(payload={"data": {
            "product": {"edges": [node("A", "custom", "a", "money")]}
        }}))
        rows, error = fetch_metafield_definitions(HEADERS, STORE, http_post=poster)
        assert error is None
        assert len(rows) == 1

    def test_null_type_object_does_not_crash(self):
        poster = FakePoster(FakeResponse(payload={"data": {
            "product": {"edges": [{"node": {
                "name": "A", "namespace": "custom", "key": "a",
                "description": None, "type": None,
            }}]},
            "variant": {"edges": []},
        }}))
        rows, error = fetch_metafield_definitions(HEADERS, STORE, http_post=poster)
        assert error is None
        assert rows[0]["Metafield type"] == ""
