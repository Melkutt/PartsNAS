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
