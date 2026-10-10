from native_field_schema import SCHEMA_COLUMNS, SCHEMA_QUERY, fetch_native_field_schema

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


def field(name, type_name, kind="SCALAR"):
    return {"name": name, "type": {"kind": kind, "name": type_name, "ofType": None}}


def nullable(name, type_name, kind="SCALAR"):
    """A NON_NULL-wrapped field, the shape Shopify's schema actually returns."""
    return {"name": name, "type": {
        "kind": "NON_NULL", "name": None,
        "ofType": {"kind": kind, "name": type_name, "ofType": None},
    }}


def payload(t0=(), t1=(), t2=(), t3=(), t4=()):
    return {"data": {
        "t0": {"inputFields": list(t0)},
        "t1": {"inputFields": list(t1)},
        "t2": {"inputFields": list(t2)},
        "t3": {"inputFields": list(t3)},
        "t4": {"inputFields": list(t4)},
    }}


class TestQueryShape:
    def test_asks_for_product_and_variant_input_types(self):
        assert '__type(name: "ProductInput")' in SCHEMA_QUERY
        assert '__type(name: "ProductVariantsBulkInput")' in SCHEMA_QUERY

    def test_asks_for_nested_types_used_for_flattening(self):
        assert '__type(name: "SEOInput")' in SCHEMA_QUERY
        assert '__type(name: "InventoryItemInput")' in SCHEMA_QUERY


class TestSuccess:
    def test_uses_correct_api_version_and_url(self):
        poster = FakePoster(FakeResponse(payload=payload(t0=[field("title", "String")])))
        fetch_native_field_schema(HEADERS, STORE, http_post=poster)
        assert poster.calls[0]["url"] == (
            "https://example.myshopify.com/admin/api/2025-01/graphql.json"
        )
        assert poster.calls[0]["headers"] == HEADERS

    def test_simple_field_marked_supported_when_mapped_in_native_update(self):
        poster = FakePoster(FakeResponse(payload=payload(t0=[field("title", "String")])))
        rows, error = fetch_native_field_schema(HEADERS, STORE, http_post=poster)
        assert error is None
        assert rows == [{
            "Owner": "Product", "GraphQL Path": "title", "Type": "String",
            "Supported in this app": "Yes", "Notes": "",
        }]

    def test_unmapped_field_marked_not_supported(self):
        poster = FakePoster(FakeResponse(payload=payload(t0=[field("templateSuffix", "String")])))
        rows, _ = fetch_native_field_schema(HEADERS, STORE, http_post=poster)
        assert rows[0]["Supported in this app"] == "No"

    def test_id_field_flagged_complex(self):
        poster = FakePoster(FakeResponse(payload=payload(t0=[nullable("category", "ID")])))
        rows, _ = fetch_native_field_schema(HEADERS, STORE, http_post=poster)
        assert rows[0]["Type"] == "ID"
        assert "Complex" in rows[0]["Notes"]

    def test_metafields_field_points_to_the_other_tab(self):
        poster = FakePoster(FakeResponse(payload=payload(t0=[field("metafields", "MetafieldInput")])))
        rows, _ = fetch_native_field_schema(HEADERS, STORE, http_post=poster)
        assert "Update Metafields tab" in rows[0]["Notes"]

    def test_id_field_is_skipped(self):
        poster = FakePoster(FakeResponse(payload=payload(t0=[field("id", "ID"), field("title", "String")])))
        rows, _ = fetch_native_field_schema(HEADERS, STORE, http_post=poster)
        assert [r["GraphQL Path"] for r in rows] == ["title"]

    def test_seo_input_flattened_into_dotted_path(self):
        poster = FakePoster(FakeResponse(payload=payload(
            t0=[field("seo", "SEOInput")],
            t2=[field("title", "String"), field("description", "String")],
        )))
        rows, error = fetch_native_field_schema(HEADERS, STORE, http_post=poster)
        assert error is None
        assert [r["GraphQL Path"] for r in rows] == ["seo.title", "seo.description"]
        assert all(r["Owner"] == "Product" for r in rows)

    def test_weight_input_left_as_composite_not_flattened_further(self):
        poster = FakePoster(FakeResponse(payload=payload(
            t1=[field("inventoryItem", "InventoryItemInput")],
            t3=[field("measurement", "InventoryItemMeasurementInput")],
            t4=[field("weight", "WeightInput")],
        )))
        rows, _ = fetch_native_field_schema(HEADERS, STORE, http_post=poster)
        assert [r["GraphQL Path"] for r in rows] == ["inventoryItem.measurement.weight"]
        assert "Composite value" in rows[0]["Notes"]

    def test_product_rows_come_before_variant_rows(self):
        poster = FakePoster(FakeResponse(payload=payload(
            t0=[field("title", "String")], t1=[field("barcode", "String")],
        )))
        rows, _ = fetch_native_field_schema(HEADERS, STORE, http_post=poster)
        assert [r["Owner"] for r in rows] == ["Product", "Variant"]

    def test_every_row_has_all_expected_columns(self):
        poster = FakePoster(FakeResponse(payload=payload(
            t0=[field("title", "String")], t1=[field("barcode", "String")],
        )))
        rows, _ = fetch_native_field_schema(HEADERS, STORE, http_post=poster)
        for row in rows:
            assert list(row.keys()) == SCHEMA_COLUMNS


class TestFailures:
    def test_non_200_returns_error(self):
        poster = FakePoster(FakeResponse(status_code=401, text="unauthorized"))
        rows, error = fetch_native_field_schema(HEADERS, STORE, http_post=poster)
        assert rows == []
        assert "HTTP 401" in error

    def test_graphql_error_returns_message(self):
        poster = FakePoster(FakeResponse(payload={
            "errors": [{"message": "Access denied for introspection"}]
        }))
        rows, error = fetch_native_field_schema(HEADERS, STORE, http_post=poster)
        assert rows == []
        assert "Access denied" in error

    def test_network_exception_returns_error(self):
        poster = FakePoster(exc=OSError("connection reset"))
        rows, error = fetch_native_field_schema(HEADERS, STORE, http_post=poster)
        assert rows == []
        assert "Could not reach Shopify" in error

    def test_non_json_response_returns_error(self):
        poster = FakePoster(FakeResponse(raise_on_json=True))
        rows, error = fetch_native_field_schema(HEADERS, STORE, http_post=poster)
        assert rows == []
        assert "not JSON" in error

    def test_missing_data_key_returns_error(self):
        poster = FakePoster(FakeResponse(payload={}))
        rows, error = fetch_native_field_schema(HEADERS, STORE, http_post=poster)
        assert rows == []
        assert "no schema data" in error

    def test_no_fields_returns_error(self):
        poster = FakePoster(FakeResponse(payload=payload()))
        rows, error = fetch_native_field_schema(HEADERS, STORE, http_post=poster)
        assert rows == []
        assert "no fields" in error
