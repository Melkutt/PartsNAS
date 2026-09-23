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
