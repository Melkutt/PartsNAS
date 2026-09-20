"""Order tab: ordered -> on order -> received into stock."""


def _row(client, pid, key):
    return next((i for i in client.get("/api/order").json()[key] if i["id"] == pid), None)


def _location_id(client):
    def first(nodes):
        for n in nodes:
            return n["id"]
    data = client.get("/api/locations").json()
    return first(data if isinstance(data, list) else data.get("items", data.get("locations", [])))


def _link(client, pid, provider="digikey", sku="ZZ-ORD-ND", price=5.0):
    r = client.post(f"/api/parts/{pid}/apply-lookup", json={
        "result": {"provider": provider, "sku": sku, "unit_price": {"ex_vat": price, "currency": "SEK"}},
        "apply": {"supplier": True}})
    assert r.status_code == 200, r.text


def test_ordered_parts_leave_the_to_order_list_and_wait_for_delivery(client, part):
    assert _row(client, part, "items") and not _row(client, part, "on_order")
    before = client.get("/api/order/count").json()

    r = client.post("/api/order/mark-ordered", json={"items": [{"part_id": part, "qty": 50}], "ref": "ZZ-1"})
    assert r.status_code == 200, r.text
    assert _row(client, part, "items") is None                       # not ordered twice
    o = _row(client, part, "on_order")
    assert o["qty"] == 50 and o["ref"] == "ZZ-1" and o["ordered_at"]
    assert client.get("/api/order/count").json()["count"] == before["count"] - 1
    assert client.get(f"/api/parts/{part}").json()["on_order"]["qty"] == 50

    client.post("/api/order/unmark-ordered", json={"part_ids": [part]})
    assert _row(client, part, "on_order") is None and _row(client, part, "items")


def test_receiving_adds_stock_and_can_be_partial(client, part):
    loc = _location_id(client)
    client.post("/api/order/mark-ordered", json={"items": [{"part_id": part, "qty": 50}]})

    r = client.post("/api/order/receive", json={"part_id": part, "qty": 20, "location_id": loc})
    assert r.status_code == 200, r.text
    assert r.json()["on_hand"] == 20 and r.json()["still_on_order"] == 30
    assert _row(client, part, "on_order")["qty"] == 30               # the rest is still on its way

    r = client.post("/api/order/receive", json={"part_id": part, "qty": 30, "location_id": loc})
    assert r.json()["on_hand"] == 50 and r.json()["still_on_order"] == 0
    assert _row(client, part, "on_order") is None
    assert client.get(f"/api/parts/{part}").json()["on_hand"] == 50
    assert client.get(f"/api/parts/{part}").json()["on_order"] is None


def test_the_price_you_paid_becomes_the_supplier_price(client, part):
    loc = _location_id(client)
    _link(client, part, price=5.0)
    client.post("/api/order/mark-ordered", json={"items": [{"part_id": part, "qty": 10}]})
    client.post("/api/order/receive", json={"part_id": part, "qty": 10, "location_id": loc, "unit_price": 3.5})
    prices = [s["price"]["ex_vat"] for s in client.get(f"/api/parts/{part}").json()["suppliers"]]
    assert prices == [3.5]

    # ...unless told not to
    client.post("/api/order/mark-ordered", json={"items": [{"part_id": part, "qty": 10}]})
    client.post("/api/order/receive", json={"part_id": part, "qty": 10, "location_id": loc,
                                            "unit_price": 9.0, "update_price": False})
    assert [s["price"]["ex_vat"] for s in client.get(f"/api/parts/{part}").json()["suppliers"]] == [3.5]


def test_bad_input_is_refused(client, part):
    assert client.post("/api/order/mark-ordered", json={"items": [{"part_id": part, "qty": 0}]}).status_code == 422
    assert client.post("/api/order/mark-ordered", json={"items": [{"part_id": "nope", "qty": 1}]}).status_code == 404
    assert client.post("/api/order/receive", json={"part_id": part, "qty": 1, "location_id": 999999}).status_code == 400
