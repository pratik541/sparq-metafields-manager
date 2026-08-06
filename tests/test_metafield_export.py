from metafield_export import (
    GRAPHQL_COST_BUDGET,
    METAFIELD_FETCH_BATCH_SIZE,
    PRODUCT_METAFIELDS_FIRST,
    batch_size_for,
    build_aliased_metafields_query,
    fetch_metafields_bulk,
    product_gid,
)

HEADERS = {"X-Shopify-Access-Token": "tok"}
STORE = "example.myshopify.com"


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class FakePoster:
    """Returns queued responses in order and records the calls made."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, headers=None, json=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "json": json})
        return self.responses.pop(0)


def make_sleep_spy():
    slept = []
    return slept, slept.append


def mf_node(namespace, key, value):
    return {"node": {"namespace": namespace, "key": key, "value": value}}


def product_field(*mf_nodes):
    return {"id": "irrelevant", "metafields": {"edges": list(mf_nodes)}}


def payload_for(*products_by_alias):
    """products_by_alias: list of product_field(...) results, aliased p0, p1, ..."""
    return {"data": {f"p{i}": p for i, p in enumerate(products_by_alias)}}


class TestQueryShape:
    """Regression coverage for two live-store bugs found while debugging why
    exported metafield values kept coming back empty.

    1. The same product queried via nodes(ids: [...]) { ... on Product {
       metafields } } returned zero metafields, while the identical product
       queried via product(id:) directly returned all of them, real values
       included. So batching must go through aliased product(id:) fields,
       never nodes(ids:).
    2. Explicitly sending `keys: null` is NOT equivalent to omitting the
       `keys` argument — Shopify's resolver returns zero metafields when
       `keys` is present in the query at all, even bound to null. So the
       unfiltered case must leave `keys` out of the query text entirely,
       not just set its variable to None.
    """

    def test_uses_aliased_product_id_fields_not_nodes(self):
        query, _ = build_aliased_metafields_query([111, 222], 50, None)
        assert "nodes(ids:" not in query
        assert "p0: product(id: $id0)" in query
        assert "p1: product(id: $id1)" in query

    def test_unfiltered_query_omits_keys_argument_entirely(self):
        query, variables = build_aliased_metafields_query([111], 50, None)
        assert "keys" not in query
        assert "keys" not in variables
        assert "metafields(first: $first)" in query

    def test_filtered_query_includes_keys_argument(self):
        query, variables = build_aliased_metafields_query([111], 2, ["custom.a", "custom.b"])
        assert "metafields(first: $first, keys: $keys)" in query
        assert variables["keys"] == ["custom.a", "custom.b"]

    def test_variables_map_each_alias_to_its_product_gid(self):
        _, variables = build_aliased_metafields_query([111, 222], 50, None)
        assert variables["id0"] == product_gid(111)
        assert variables["id1"] == product_gid(222)


class TestSuccess:
    def test_empty_product_ids_makes_no_request(self):
        poster = FakePoster([])
        result, error = fetch_metafields_bulk(HEADERS, STORE, [], http_post=poster)
        assert result == {}
        assert error is None
        assert poster.calls == []

    def test_uses_correct_url_and_variables(self):
        poster = FakePoster([FakeResponse(payload={"data": {}})])
        fetch_metafields_bulk(HEADERS, STORE, [111, 222], http_post=poster)
        call = poster.calls[0]
        assert call["url"] == "https://example.myshopify.com/admin/api/2025-01/graphql.json"
        assert call["headers"] == HEADERS
        assert call["json"]["variables"]["id0"] == product_gid(111)
        assert call["json"]["variables"]["id1"] == product_gid(222)
        assert call["json"]["variables"]["first"] == PRODUCT_METAFIELDS_FIRST
        assert "keys" not in call["json"]["variables"]

    def test_maps_metafields_back_to_the_right_product_id_by_position(self):
        poster = FakePoster([FakeResponse(payload=payload_for(
            product_field(mf_node("custom", "happy_shoppers", "42")),
        ))])
        result, error = fetch_metafields_bulk(HEADERS, STORE, [111], http_post=poster)
        assert error is None
        assert result == {111: [{"namespace": "custom", "key": "happy_shoppers", "value": "42"}]}

    def test_product_with_no_metafields_is_absent_from_result(self):
        poster = FakePoster([FakeResponse(payload=payload_for(
            product_field(),
            product_field(mf_node("custom", "ribbon_text", "New")),
        ))])
        result, error = fetch_metafields_bulk(HEADERS, STORE, [111, 222], http_post=poster)
        assert error is None
        assert 111 not in result
        assert result[222] == [{"namespace": "custom", "key": "ribbon_text", "value": "New"}]


class TestKeyNormalization:
    """Regression coverage for the third live-store bug: when a query filters
    with `keys: [...]`, Shopify echoes each result's key back in combined
    "namespace.key" form instead of the bare key an unfiltered query returns
    — confirmed against a live store (product_details came back as
    "custom.product_details", not "product_details"). Every caller keys its
    lookups on the bare key, so this silently broke every filtered fetch:
    the data was fetched correctly, just filed under a key nothing matched.
    """

    def test_strips_leaked_namespace_prefix_from_filtered_response(self):
        poster = FakePoster([FakeResponse(payload=payload_for(
            product_field(mf_node("custom", "custom.product_details", "value")),
        ))])
        result, error = fetch_metafields_bulk(
            HEADERS, STORE, [111], keys=["custom.product_details"], http_post=poster
        )
        assert error is None
        assert result == {111: [{"namespace": "custom", "key": "product_details", "value": "value"}]}

    def test_leaves_already_bare_key_unchanged(self):
        poster = FakePoster([FakeResponse(payload=payload_for(
            product_field(mf_node("custom", "product_details", "value")),
        ))])
        result, error = fetch_metafields_bulk(HEADERS, STORE, [111], http_post=poster)
        assert error is None
        assert result == {111: [{"namespace": "custom", "key": "product_details", "value": "value"}]}

    def test_does_not_strip_a_key_that_merely_contains_a_dot(self):
        # A key like "a.b" under namespace "custom" must not become "b" —
        # only an exact "<namespace>." prefix should be stripped.
        poster = FakePoster([FakeResponse(payload=payload_for(
            product_field(mf_node("custom", "a.b", "value")),
        ))])
        result, error = fetch_metafields_bulk(HEADERS, STORE, [111], http_post=poster)
        assert error is None
        assert result == {111: [{"namespace": "custom", "key": "a.b", "value": "value"}]}

    def test_missing_alias_in_response_does_not_crash(self):
        poster = FakePoster([FakeResponse(payload={"data": {}})])
        result, error = fetch_metafields_bulk(HEADERS, STORE, [111], http_post=poster)
        assert error is None
        assert result == {}

    def test_null_alias_value_does_not_crash(self):
        poster = FakePoster([FakeResponse(payload={"data": {"p0": None}})])
        result, error = fetch_metafields_bulk(HEADERS, STORE, [111], http_post=poster)
        assert error is None
        assert result == {}


class TestKeysFilter:
    def test_keys_are_passed_through_as_variable(self):
        poster = FakePoster([FakeResponse(payload={"data": {}})])
        keys = ["custom.happy_shoppers", "custom.ribbon_text"]
        fetch_metafields_bulk(HEADERS, STORE, [111], keys=keys, http_post=poster)
        variables = poster.calls[0]["json"]["variables"]
        assert variables["keys"] == keys

    def test_first_is_capped_to_number_of_keys_requested(self):
        poster = FakePoster([FakeResponse(payload={"data": {}})])
        fetch_metafields_bulk(HEADERS, STORE, [111], keys=["custom.a", "custom.b"], http_post=poster)
        assert poster.calls[0]["json"]["variables"]["first"] == 2

    def test_first_matches_key_count_even_beyond_the_default_ceiling(self):
        # Regression: first used to be capped at PRODUCT_METAFIELDS_FIRST even
        # when more keys were explicitly requested, which silently truncated
        # real metafields past the cap since metafields(first: N, keys: [...])
        # returns at most N results regardless of how many keys matched.
        poster = FakePoster([FakeResponse(payload={"data": {}})])
        many_keys = [f"custom.field{i}" for i in range(PRODUCT_METAFIELDS_FIRST + 20)]
        fetch_metafields_bulk(HEADERS, STORE, [111], keys=many_keys, http_post=poster)
        assert poster.calls[0]["json"]["variables"]["first"] == len(many_keys)


class TestBatchSizeFor:
    def test_falls_back_to_fixed_size_when_key_count_unknown(self):
        assert batch_size_for(0) == METAFIELD_FETCH_BATCH_SIZE
        assert batch_size_for(None) == METAFIELD_FETCH_BATCH_SIZE

    def test_fewer_selected_keys_allows_a_larger_batch(self):
        small_selection = batch_size_for(2)
        large_selection = batch_size_for(40)
        assert small_selection > large_selection

    def test_batch_size_times_first_stays_under_the_cost_budget(self):
        for num_keys in (1, 2, 5, 12, 30, 50, 200):
            size = batch_size_for(num_keys)
            assert size * (num_keys + 2) <= GRAPHQL_COST_BUDGET

    def test_never_returns_less_than_one(self):
        assert batch_size_for(10_000) >= 1


class TestRetries:
    def test_http_429_sleeps_three_seconds_then_retries(self):
        poster = FakePoster([
            FakeResponse(status_code=429, text="rate limited"),
            FakeResponse(payload={"data": {}}),
        ])
        slept, sleep = make_sleep_spy()
        result, error = fetch_metafields_bulk(HEADERS, STORE, [111], http_post=poster, sleep=sleep)
        assert error is None
        assert result == {}
        assert slept == [3]

    def test_throttled_graphql_error_retries_after_delay(self):
        poster = FakePoster([
            FakeResponse(payload={"errors": [
                {"extensions": {"code": "THROTTLED", "retryAfter": 1.5}}
            ]}),
            FakeResponse(payload={"data": {}}),
        ])
        slept, sleep = make_sleep_spy()
        result, error = fetch_metafields_bulk(HEADERS, STORE, [111], http_post=poster, sleep=sleep)
        assert error is None
        assert slept == [2.0]

    def test_gives_up_after_max_attempts(self):
        poster = FakePoster([FakeResponse(status_code=429, text="x") for _ in range(3)])
        slept, sleep = make_sleep_spy()
        result, error = fetch_metafields_bulk(HEADERS, STORE, [111], http_post=poster, sleep=sleep)
        assert result == {}
        assert "3 attempts" in error


class TestFailures:
    def test_non_200_returns_error(self):
        poster = FakePoster([FakeResponse(status_code=401, text="unauthorized")])
        result, error = fetch_metafields_bulk(HEADERS, STORE, [111], http_post=poster)
        assert result == {}
        assert "HTTP 401" in error

    def test_graphql_error_returns_message(self):
        poster = FakePoster([FakeResponse(payload={
            "errors": [{"message": "Access denied for metafields"}]
        })])
        result, error = fetch_metafields_bulk(HEADERS, STORE, [111], http_post=poster)
        assert result == {}
        assert "Access denied" in error


class TestCostReporting:
    def test_on_cost_called_when_extension_present(self):
        seen = []
        poster = FakePoster([FakeResponse(payload={
            "data": {},
            "extensions": {"cost": {"requestedQueryCost": 51, "actualQueryCost": 51,
                                    "throttleStatus": {"maximumAvailable": 1000,
                                                        "currentlyAvailable": 949,
                                                        "restoreRate": 50}}},
        })])
        result, error = fetch_metafields_bulk(HEADERS, STORE, [111], http_post=poster, on_cost=seen.append)
        assert error is None
        assert len(seen) == 1
        assert seen[0]["actual"] == 51

    def test_on_cost_not_called_when_extension_missing(self):
        seen = []
        poster = FakePoster([FakeResponse(payload={"data": {}})])
        fetch_metafields_bulk(HEADERS, STORE, [111], http_post=poster, on_cost=seen.append)
        assert seen == []

    def test_cost_reported_even_on_throttled_attempt(self):
        seen = []
        throttled = {
            "errors": [{"extensions": {"code": "THROTTLED", "retryAfter": 1.0}}],
            "extensions": {"cost": {"requestedQueryCost": 51,
                                    "throttleStatus": {"maximumAvailable": 1000,
                                                        "currentlyAvailable": 10,
                                                        "restoreRate": 50}}},
        }
        poster = FakePoster([FakeResponse(payload=throttled),
                             FakeResponse(payload={"data": {}})])
        slept, sleep = make_sleep_spy()
        fetch_metafields_bulk(HEADERS, STORE, [111], http_post=poster, sleep=sleep, on_cost=seen.append)
        assert len(seen) == 1, "cost from the throttled attempt should still be reported"


class TestBatchSizeConstant:
    def test_batch_times_first_stays_well_under_the_bucket(self):
        assert METAFIELD_FETCH_BATCH_SIZE * PRODUCT_METAFIELDS_FIRST < 1000
