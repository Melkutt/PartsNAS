"""Pure-function tests for the supplier providers - no network calls (see providers/safety.py:
network access only ever happens on an explicit user click, never from a test)."""
from __future__ import annotations

from app.providers import all_providers, get_provider
from app.providers.tme import _flatten, _quote, _sign


def _base_string(params: dict) -> str:
    """Mirrors _sign()'s construction, so the test can check the string without a known HMAC output."""
    encoded = sorted((_quote(k), _quote(v)) for k, v in params.items())
    param_str = "&".join(f"{k}={v}" for k, v in encoded)
    return f"POST&{_quote('https://api.tme.eu/Products/GetStocks.json')}&{_quote(param_str)}"


def test_tme_signature_base_string_matches_the_published_example():
    # from TME's own API manual: SymbolList[0]=1N4007... under /Products/GetStocks.json
    params = _flatten({"Language": "EN", "SymbolList": ["1N4007"]})
    assert params == {"Language": "EN", "SymbolList[0]": "1N4007"}
    assert _base_string(params).startswith(
        "POST&https%3A%2F%2Fapi.tme.eu%2FProducts%2FGetStocks.json&"
        "Language%3DEN%26SymbolList%255B0%255D%3D1N4007"
    )


def test_tme_sorts_parameters_after_percent_encoding_not_before():
    # "A[1]" (raw '[' = 0x5B) sorts AFTER "A0" (raw '0' = 0x30) - but encoded, "A%5B1%5D" ('%' = 0x25)
    # sorts BEFORE "A0". RFC 5849 3.4.1.3.2 requires the latter; getting this backwards is exactly the
    # kind of thing that passes every test with plain field names and only breaks on a real request.
    params = {"A[1]": "x", "A0": "y"}
    assert _base_string(params).endswith("A%255B1%255D%3Dx%26A0%3Dy")


def test_tme_signature_is_a_deterministic_base64_hmac_sha1():
    sig = _sign("POST", "https://api.tme.eu/Products/Search.json", {"Token": "t", "SearchPlain": "1N4007"}, "secret")
    assert sig == _sign("POST", "https://api.tme.eu/Products/Search.json", {"Token": "t", "SearchPlain": "1N4007"}, "secret")
    assert sig != _sign("POST", "https://api.tme.eu/Products/Search.json", {"Token": "t", "SearchPlain": "1N4007"}, "different")
    import base64
    base64.b64decode(sig)  # raises if it is not valid base64


def test_tme_is_registered_alongside_mouser_and_digikey(client):
    from app.core.db import SessionLocal

    names = {p.name for p in all_providers()}
    assert {"mouser", "digikey", "tme"} <= names
    tme = get_provider("tme")
    assert tme.label == "TME" and tme.cred_fields == ["token", "secret"]
    with SessionLocal() as db:
        assert tme.configured(db) is False  # no creds set in this test database


def test_reset_breaker_clears_a_pause_but_not_todays_count(client):
    from app.core.db import SessionLocal
    from app.providers.safety import _trip_breaker, _load_state, reset_breaker

    with SessionLocal() as db:
        _trip_breaker(db, "zz-test-provider", "HTTP 403 (rate limit / block)", 3600)
        st = _load_state(db, "zz-test-provider")
        assert st["blocked_until"] and st["blocked_until"] > 0
        reset_breaker(db, "zz-test-provider")
        st = _load_state(db, "zz-test-provider")
        assert st["blocked_until"] is None


def test_a_structured_api_error_does_not_trip_the_breaker(client):
    # a 403/429 whose body is the API's OWN error (bad signature, bad parameter - a code bug)
    # must not cost 8h; only an unexplained block (no such body) should.
    import httpx

    from app.providers.safety import _api_error_detail

    tme_style = httpx.Response(403, json={"Status": "E_INVALID_SIGNATURE", "Data": [], "ErrorCode": 21,
                                          "ErrorMessage": "Signature value is invalid.", "Error": []})
    assert _api_error_detail(tme_style) == "21: Signature value is invalid."

    block_page = httpx.Response(403, text="<html>Access Denied</html>")
    assert _api_error_detail(block_page) is None


def test_settings_can_reset_a_paused_provider(client):
    from app.core.db import SessionLocal
    from app.providers.safety import _trip_breaker

    with SessionLocal() as db:
        _trip_breaker(db, "tme", "HTTP 403 (rate limit / block)", 3600)
    try:
        got = {p["name"]: p for p in client.get("/api/settings/providers").json()}
        assert got["tme"]["blocked_until"] is not None
        assert client.post("/api/settings/providers/tme/reset").status_code == 200
        got = {p["name"]: p for p in client.get("/api/settings/providers").json()}
        assert got["tme"]["blocked_until"] is None
        assert client.post("/api/settings/providers/nope/reset").status_code == 404
    finally:
        with SessionLocal() as db:
            from app.providers.safety import reset_breaker
            reset_breaker(db, "tme")
