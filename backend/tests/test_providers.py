"""Pure-function tests for the supplier providers - no network calls (see providers/safety.py:
network access only ever happens on an explicit user click, never from a test)."""
from __future__ import annotations

from app.providers import all_providers, get_provider
from app.providers.tme import _flatten, _quote, _sign


def test_tme_signature_base_string_matches_the_published_example():
    # from TME's own API manual: SymbolList[0]=1N4007... under /Products/GetStocks.json
    params = _flatten({"Language": "EN", "SymbolList": ["1N4007"]})
    assert params == {"Language": "EN", "SymbolList[0]": "1N4007"}
    param_str = "&".join(f"{_quote(k)}={_quote(v)}" for k, v in sorted(params.items()))
    base_str = f"POST&{_quote('https://api.tme.eu/Products/GetStocks.json')}&{_quote(param_str)}"
    assert base_str.startswith(
        "POST&https%3A%2F%2Fapi.tme.eu%2FProducts%2FGetStocks.json&"
        "Language%3DEN%26SymbolList%255B0%255D%3D1N4007"
    )


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
