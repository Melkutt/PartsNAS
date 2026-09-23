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


def test_tme_errors_say_which_of_the_four_actions_failed(client, monkeypatch):
    from app.core.db import SessionLocal
    from app.core.kv import set_kv
    from app.providers.base import ProviderBlocked, ProviderError
    import app.providers.tme as tme_mod

    def boom(*a, **kw):
        raise ProviderError("tme: HTTP 403 — 4: Access denied. You are not allowed to execute this action.")

    def blocked(*a, **kw):
        raise ProviderBlocked("tme: HTTP 403 (rate limit / block) — pausing this provider for ~8.0 h", 28800)

    with SessionLocal() as db:
        set_kv(db, "provider:tme:config", {"token": "t", "secret": "s"})
        monkeypatch.setattr(tme_mod, "guarded_request", boom)
        try:
            tme_mod.TMEProvider()._call(db, "Products/Search", {"SearchPlain": "1N4007"})
            assert False, "should have raised"
        except ProviderError as e:
            assert str(e).startswith("Products/Search: ")

        monkeypatch.setattr(tme_mod, "guarded_request", blocked)
        try:
            tme_mod.TMEProvider()._call(db, "Products/GetPrices", {"SymbolList": ["X"]})
            assert False, "should have raised"
        except ProviderBlocked as e:
            assert str(e).startswith("Products/GetPrices: ") and e.retry_after_s == 28800
        set_kv(db, "provider:tme:config", {})


def test_search_falls_back_to_the_mpn_as_symbol_when_search_itself_is_forbidden(client, monkeypatch):
    from app.core.db import SessionLocal
    from app.core.kv import set_kv
    from app.providers.base import ProviderError
    import app.providers.tme as tme_mod

    def fake_call(self, db, action, params):
        if action == "Products/Search":
            raise ProviderError("Products/Search: tme: HTTP 403 — 4: Access denied. You are not allowed to execute this action.")
        sym = params["SymbolList"][0]  # a real GetProducts/GetPrices/GetParameters echoes back whatever Symbol was asked for
        if action == "Products/GetProducts":
            return {"ProductList": [{"Symbol": sym, "Description": "Diode 1A 1000V", "Producer": "Diotec"}]}
        if action == "Products/GetPrices":
            return {"ProductList": [{"Symbol": sym, "PriceList": [{"Amount": 1, "PriceValue": 0.42}]}]}
        return {"ProductList": [{"Symbol": sym, "ParameterList": [{"ParameterName": "Voltage", "ParameterValue": "1000V"}]}]}

    with SessionLocal() as db:
        set_kv(db, "provider:tme:config", {"token": "t", "secret": "s"})
        monkeypatch.setattr(tme_mod.TMEProvider, "_call", fake_call)
        results = tme_mod.TMEProvider().search(db, "ZZ-TME-FALLBACK-OK")
        assert len(results) == 1
        r = results[0]
        assert r.manufacturer == "Diotec" and r.description == "Diode 1A 1000V"
        assert r.unit_price().ex_vat == 0.42
        assert r.attributes.get("Voltage") == "1000V"
        set_kv(db, "provider:tme:config", {})


def test_search_reports_the_real_error_when_the_fallback_finds_nothing_either(client, monkeypatch):
    from app.core.db import SessionLocal
    from app.core.kv import set_kv
    from app.providers.base import ProviderError
    import app.providers.tme as tme_mod

    def all_forbidden(self, db, action, params):
        raise ProviderError(f"{action}: tme: HTTP 403 — 4: Access denied. You are not allowed to execute this action.")

    with SessionLocal() as db:
        set_kv(db, "provider:tme:config", {"token": "t", "secret": "s"})
        monkeypatch.setattr(tme_mod.TMEProvider, "_call", all_forbidden)
        try:
            tme_mod.TMEProvider().search(db, "ZZ-TME-FALLBACK-ALLFAIL")
            assert False, "should have raised"
        except ProviderError as e:
            assert str(e).startswith("Products/Search: ")  # the original, most actionable error - not a silent empty match
        set_kv(db, "provider:tme:config", {})


# -- Farnell / element14 --------------------------------------------------------------------

def test_farnell_is_registered_and_builds_a_get_url_with_the_key_as_a_plain_param(client, monkeypatch):
    from app.core.db import SessionLocal
    from app.core.kv import set_kv
    import app.providers.farnell as farnell_mod

    names = {p.name for p in all_providers()}
    assert "farnell" in names
    f = get_provider("farnell")
    assert f.label == "Farnell" and f.cred_fields == ["api_key"]

    seen = {}

    def fake_guarded_request(db, name, *, method, url, params, per_min, per_day):
        seen.update(method=method, url=url, params=params)
        return {"manufacturerPartNumberSearchReturn": {"products": [
            {"translatedManufacturerPartNumber": "LM339ADT", "brandName": "Texas Instruments",
             "displayName": "TI - LM339ADT - COMPARATOR, QUAD, SOIC-14, 0.1uF, 5%",
             "sku": "1234567", "productStatus": "Active",
             "prices": [{"from": 1, "to": 9, "cost": 3.21}, {"from": 10, "to": 99, "cost": 2.87}],
             "datasheets": [{"url": "https://example.com/lm339.pdf"}],
             "inv": {"quantity": 812}}]}}

    with SessionLocal() as db:
        set_kv(db, "provider:farnell:config", {"api_key": "k"})
        monkeypatch.setattr(farnell_mod, "guarded_request", fake_guarded_request)
        results = farnell_mod.FarnellProvider().search(db, "LM339ADT")
        set_kv(db, "provider:farnell:config", {})

    assert seen["method"] == "GET" and seen["url"] == farnell_mod.BASE
    assert seen["params"]["callInfo.apiKey"] == "k"
    assert seen["params"]["term"] == "manuPartNum:LM339ADT"
    # regression: shipped defaulting to uk.farnell.com/GBP, which silently priced a Swedish
    # user's parts in the wrong currency (0.71 GBP read as if it were 0.71 SEK - the real price
    # was ~9.19 SEK, a ~13x difference nobody would catch just by looking at the number)
    assert seen["params"]["storeInfo.id"] == "se.farnell.com"
    assert len(results) == 1
    r = results[0]
    assert r.mpn == "LM339ADT" and r.manufacturer == "Texas Instruments"
    assert r.in_stock == 812 and r.datasheet_url == "https://example.com/lm339.pdf"
    breaks = sorted(r.price_breaks, key=lambda b: b.qty)
    assert [(b.qty, b.ex_vat) for b in breaks] == [(1, 3.21), (10, 2.87)]
    assert r.unit_price().ex_vat == 3.21
    assert r.attributes.get("Capacitance") == "0.1uF"  # pulled from the description text


def test_farnell_never_invents_an_image_url_from_a_bare_filename():
    from app.providers.farnell import _parse_product

    r = _parse_product({"translatedManufacturerPartNumber": "X", "image": {"baseName": "x_lrg.jpg"}}, "GBP")
    assert r.image_url is None  # a bare filename isn't a loadable URL; a wrong guess would be worse than none
    r2 = _parse_product({"translatedManufacturerPartNumber": "X", "image": {"url": "https://x.example/x.jpg"}}, "GBP")
    assert r2.image_url == "https://x.example/x.jpg"


def test_a_malformed_response_is_a_capped_error_message_not_a_breaker_trip(client, monkeypatch):
    # live case: Mouser (or something in front of it) returned a raw HTML page with no valid
    # HTTP framing - httpx/h11 calls that "illegal header line" and raises before any status
    # code exists to check, so it must not cost the provider an 8h pause, and the message must
    # not echo an unbounded amount of whatever garbage came back
    from app.core.db import SessionLocal
    from app.providers.base import ProviderError
    import app.providers.safety as safety_mod

    import httpx

    monkeypatch.setattr(safety_mod.time, "sleep", lambda *_: None)  # don't actually wait out the retries

    def fake_request(self, *a, **kw):
        raise httpx.RemoteProtocolError(
            "illegal header line: bytearray(b'<!doctype html public \"-//w3c//dtd xhtml 1.0 "
            "transitional//en\" \"http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd\">')"
        )

    monkeypatch.setattr(httpx.Client, "request", fake_request)
    with SessionLocal() as db:
        try:
            safety_mod.guarded_request(db, "zz-test-neterr", method="GET", url="http://127.0.0.1:1",
                                        per_min=100, per_day=100)
            assert False, "should have raised"
        except ProviderError as e:
            assert str(e).startswith("zz-test-neterr: network error:") and len(str(e)) < 260
        st = safety_mod._load_state(db, "zz-test-neterr")
        assert st["blocked_until"] is None and st["used_today"] == 0
