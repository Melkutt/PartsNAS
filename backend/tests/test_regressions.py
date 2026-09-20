"""Regression tests for bugs that were found in real use. Each one names what went wrong."""
from app.providers.mouser import _augment_from_description


# -- Mouser description parsing ------------------------------------------------------------

def _parsed(desc: str) -> dict:
    attrs: dict = {}
    _augment_from_description(attrs, desc)
    return attrs


def test_leading_dot_is_kept():
    # ".18ohm" was read as 18 ohm: \b starts the match after the dot
    assert _parsed("Current Sense Resistors - SMD 1watt .18ohm 1%")["Resistance"] == ".18ohm"
    assert _parsed("Thick Film Resistors 10 Ohm .25W")["Power Rating"] == ".25W"


def test_ordinary_values_still_parse():
    a = _parsed("Res 0.18 Ohm 1W")
    assert a["Resistance"] == "0.18 Ohm" and a["Power Rating"] == "1W"
    assert _parsed("RES 4.7K OHM 1/4W 1%")["Resistance"] == "4.7K OHM"
    assert _parsed("Cap 100nF 50V")["Capacitance"] == "100nF"


# -- supplier link filed under the provider that answered ----------------------------------

def _apply(client, pid, provider, sku):
    return client.post(f"/api/parts/{pid}/apply-lookup", json={
        "result": {"provider": provider, "sku": sku, "product_url": f"https://example.test/{provider}",
                   "unit_price": {"ex_vat": 1.5, "currency": "SEK"}},
        "apply": {"supplier": True},
    })


def test_digikey_lookup_is_filed_under_digikey(client, part):
    # provider.title() gave "Digikey", found no supplier and fell back to Mouser
    assert _apply(client, part, "digikey", "ZZ-123-ND").status_code == 200
    assert _apply(client, part, "mouser", "603-ZZ").status_code == 200
    links = {s["supplier"]: s["sku"] for s in client.get(f"/api/parts/{part}").json()["suppliers"]}
    assert links == {"Digi-Key": "ZZ-123-ND", "Mouser": "603-ZZ"}


def test_a_link_can_be_moved_to_another_supplier(client, part):
    _apply(client, part, "mouser", "603-ZZ")
    link = client.get(f"/api/parts/{part}").json()["suppliers"][0]
    assert client.patch(f"/api/parts/{part}/suppliers/{link['id']}", json={"supplier_id": 999999}).status_code == 400
    assert client.patch(f"/api/parts/{part}/suppliers/{link['id']}", json={"supplier_id": 1}).status_code == 200
    assert client.get(f"/api/parts/{part}").json()["suppliers"][0]["supplier"] == "Digi-Key"


# -- Order list remembers the typed quantity -----------------------------------------------

def _order_row(client, pid):
    return next(i for i in client.get("/api/order").json()["items"] if i["id"] == pid)


def test_order_qty_is_remembered_and_can_be_cleared(client, part):
    assert _order_row(client, part)["suggested_qty"] == 2          # min 2, none in stock
    assert client.patch(f"/api/parts/{part}", json={"order_qty": 50}).status_code == 200
    assert _order_row(client, part)["suggested_qty"] == 50
    assert client.patch(f"/api/parts/{part}", json={"order_qty": None}).status_code == 200
    assert _order_row(client, part)["suggested_qty"] == 2
    assert client.patch(f"/api/parts/{part}", json={"order_qty": 0}).status_code == 422


# -- every class has the shared parameters ---------------------------------------------------

def test_every_class_has_size_dimension(client):
    classes = client.get("/api/meta/part-classes").json()
    missing = [cid for cid, c in classes.items() if not any(f["key"] == "dimensions" for f in c["fields"])]
    assert missing == []
