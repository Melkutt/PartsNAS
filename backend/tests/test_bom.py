"""BOM: where the parts are (for a pick list) and changing a remembered match."""


def _location(client):
    data = client.get("/api/locations").json()
    nodes = data if isinstance(data, list) else data.get("items", data.get("locations", []))
    return nodes[0]["id"], nodes[0]["name"]


def _part(client, name, mpn):
    r = client.post("/api/parts", json={"name": name, "mpn": mpn})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_project_lines_say_where_the_parts_are(client):
    loc_id, loc_name = _location(client)
    a = _part(client, "ZZ_BOM cap", "ZZ-BOM-1")
    b = _part(client, "ZZ_BOM none in stock", "ZZ-BOM-2")
    try:
        client.post(f"/api/parts/{a}/stock", json={"location_id": loc_id, "delta": 40, "kind": "add"})
        r = client.post("/api/bom/projects", json={"name": "ZZ_BOM proj", "lines": [
            {"mpn": None, "value": "1n", "footprint": "C_0603_1608Metric", "qty": 2, "refdes": "C1 C2", "part_id": a},
            {"mpn": None, "value": "10k", "footprint": "R_0603_1608Metric", "qty": 1, "refdes": "R1", "part_id": b},
        ]})
        assert r.status_code == 201, r.text
        pid = r.json()["id"]
        lines = client.get(f"/api/bom/projects/{pid}", params={"boards": 3}).json()["lines"]
        by_ref = {ln["refdes"]: ln for ln in lines}
        assert by_ref["C1 C2"]["locations"] == [{"location": loc_name, "qty": 40}]
        assert by_ref["R1"]["locations"] == []
        client.delete(f"/api/bom/projects/{pid}")
    finally:
        for p in (a, b):
            client.delete(f"/api/parts/{p}")


def test_a_remembered_match_can_point_at_another_part(client):
    x = _part(client, "ZZ_BOM 1n X7R", "ZZ-BOM-X7R")
    y = _part(client, "ZZ_BOM 1n C0G", "ZZ-BOM-C0G")
    try:
        r = client.post("/api/bom/projects", json={"name": "ZZ_BOM remember", "lines": [
            {"mpn": None, "value": "1n", "footprint": "C_0603_1608Metric", "qty": 1, "refdes": "C1",
             "part_id": x, "remember": True}]})
        pid = r.json()["id"]
        rule = next(r for r in client.get("/api/bom/match-rules").json() if r["part_id"] == x)
        assert client.patch(f"/api/bom/match-rules/{rule['id']}", json={"part_id": "nope"}).status_code == 400
        assert client.patch("/api/bom/match-rules/999999", json={"part_id": y}).status_code == 404
        assert client.patch(f"/api/bom/match-rules/{rule['id']}", json={"part_id": y}).status_code == 200
        assert next(r for r in client.get("/api/bom/match-rules").json() if r["id"] == rule["id"])["part_id"] == y
        client.delete(f"/api/bom/match-rules/{rule['id']}")
        client.delete(f"/api/bom/projects/{pid}")
    finally:
        for p in (x, y):
            client.delete(f"/api/parts/{p}")


# -- values are compared as numbers -----------------------------------------------------------

def test_a_part_value_is_read_from_the_value_attribute_or_the_first_word_of_the_name():
    from app.bommatch import part_value_number, same_value

    assert part_value_number("x", {"value": "1µF", "voltage": "50"}) == 1e-6
    assert same_value(part_value_number("1n 100V X7R", {}), 1e-9)
    assert part_value_number("Single 2-Input AND Gate", {"voltage": "5"}) is None   # a voltage is not a value
    assert part_value_number("2-Input NAND", {}) is None
    assert same_value(1e-7, 0.1e-6) and not same_value(1e-6, 1e-7)


def test_browse_by_value_finds_1u_and_not_100n(client):
    """'1u' as text also matches '0.1uF' in a description - a factor of ten wrong."""
    r = client.post("/api/parts", json={"name": "ZZ_VAL 1uF 50V", "attributes": {"value": "1µF"},
                                         "description": "MLCC 1uF 50V X5R"})
    a = r.json()["id"]
    r = client.post("/api/parts", json={"name": "ZZ_VAL 100nF 50V", "attributes": {"value": "100nF"},
                                         "description": "MLCC 100nF (0.1uF) 50V X7R"})
    b = r.json()["id"]
    try:
        def found(v):
            return {i["id"] for i in client.get("/api/parts", params={"q": "ZZ_VAL", "value_eq": v}).json()["items"]}
        assert found("1u") == {a} and found("1µ") == {a} and found("1000n") == {a}
        assert found("100n") == {b} and found("0.1u") == {b}
        assert found("") == {a, b}                       # no value = no filter
        assert found("not a value") == {a, b}
    finally:
        for p in (a, b):
            client.delete(f"/api/parts/{p}")


def test_a_part_with_only_a_kicad_footprint_is_still_a_candidate(client):
    from app.bommatch import Matcher
    from app.core.db import SessionLocal

    r = client.post("/api/parts", json={"name": "ZZ_KICAD 1uF", "attributes": {"value": "1µF"},
                                         "kicad_footprint": "Capacitor_SMD:C_0603_1608Metric"})
    pid = r.json()["id"]
    try:
        with SessionLocal() as db:
            m = Matcher(db).match(mpn=None, value="1u", footprint="Capacitor_SMD:C_0603_1608Metric_Pad1.08x0.95mm_HandSolder")
        assert m["kind"] == "candidate" and m["part_id"] == pid
        assert "same value" in m["why"] and any(w.startswith("package") for w in m["why"])
        assert m["score"] <= 95
    finally:
        client.delete(f"/api/parts/{pid}")
