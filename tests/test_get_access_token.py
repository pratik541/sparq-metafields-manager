from app import get_access_token, normalize_store_url


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class FakePoster:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def __call__(self, url, json=None, timeout=None):
        self.calls.append({"url": url, "json": json})
        return self.response


class TestNormalizeStoreUrl:
    def test_leaves_a_bare_host_unchanged(self):
        assert normalize_store_url("store.myshopify.com") == "store.myshopify.com"

    def test_strips_https_prefix(self):
        assert normalize_store_url("https://store.myshopify.com") == "store.myshopify.com"

    def test_strips_http_prefix(self):
        assert normalize_store_url("http://store.myshopify.com") == "store.myshopify.com"

    def test_strips_trailing_slash(self):
        assert normalize_store_url("store.myshopify.com/") == "store.myshopify.com"

    def test_strips_protocol_and_trailing_slash_together(self):
        # Regression: this exact combination — pasting the full browser URL —
        # built a doubled "https://https://store.myshopify.com//admin/..."
        # request that Shopify's edge rejected with a generic 400 OAuth
        # error page, which looked like a credentials problem but wasn't.
        assert normalize_store_url("https://store.myshopify.com/") == "store.myshopify.com"

    def test_strips_surrounding_whitespace(self):
        assert normalize_store_url("  store.myshopify.com  \n") == "store.myshopify.com"


class TestGetAccessTokenNormalizesInput:
    def test_request_url_uses_normalized_store(self):
        poster = FakePoster(FakeResponse(payload={"access_token": "tok"}))
        get_access_token("https://store.myshopify.com/", " id ", " secret ", http_post=poster)

    def test_credentials_are_stripped_before_sending(self):
        poster = FakePoster(FakeResponse(payload={"access_token": "tok"}))
        get_access_token("store.myshopify.com", " id\n", " secret\n", http_post=poster)
        body = poster.calls[0]["json"]
        assert body["client_id"] == "id"
        assert body["client_secret"] == "secret"

    def test_success_returns_token(self):
        poster = FakePoster(FakeResponse(payload={"access_token": "tok-123"}))
        token, error = get_access_token("store.myshopify.com", "id", "secret", http_post=poster)
        assert token == "tok-123"
        assert error is None

    def test_failure_returns_status_and_body(self):
        poster = FakePoster(FakeResponse(status_code=400, text="invalid_request"))
        token, error = get_access_token("store.myshopify.com", "id", "secret", http_post=poster)
        assert token is None
        assert "400" in error
        assert "invalid_request" in error
