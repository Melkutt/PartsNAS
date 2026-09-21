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


# -- Import IBOM: lines read elsewhere, and the optional board view ----------------------------

def test_lines_read_from_an_ibom_get_the_same_preview_as_a_csv(client):
    r = client.post("/api/bom/match", json={"suggested_name": "BGA2802_15", "lines": [
        {"refdes": "C6 C8 C10", "value": "1u", "footprint": "C_0402_1005Metric_Pad0.74x0.62mm_HandSolder", "qty": 3},
        {"refdes": "U1", "value": "MIC5504-3.3YM5", "footprint": "SOT-23-5", "mpn": "", "qty": 1},
    ]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["suggested_name"] == "BGA2802_15"
    assert [ln["refdes"] for ln in body["lines"]] == ["C6 C8 C10", "U1"]
    assert all("match" in ln and "kind" in ln["match"] for ln in body["lines"])
    assert client.post("/api/bom/match", json={"lines": []}).status_code == 422


def test_the_board_view_is_optional_and_lives_with_the_project(client):
    pid = client.post("/api/bom/projects", json={"name": "ZZ_IBOM proj", "lines": [
        {"value": "1u", "footprint": "C_0402", "qty": 1, "refdes": "C1"}]}).json()["id"]
    try:
        assert client.get("/api/bom/projects").json()[0]["has_ibom"] is False
        assert client.get(f"/api/bom/projects/{pid}/ibom").status_code == 404

        page = b"<html><head><title>Interactive BOM</title></head><script>var pcbdata = {};</script></html>"
        assert client.post(f"/api/bom/projects/{pid}/ibom", files={"file": ("ibom.html", page, "text/html")}).status_code == 200
        got = client.get(f"/api/bom/projects/{pid}/ibom")
        assert got.status_code == 200 and got.content == page and got.headers["content-type"].startswith("text/html")
        assert client.get(f"/api/bom/projects/{pid}").json()["has_ibom"] is True

        # anything else is refused, and the good file is left alone
        bad = client.post(f"/api/bom/projects/{pid}/ibom", files={"file": ("x.html", b"<html>nothing</html>", "text/html")})
        assert bad.status_code == 400
        assert client.get(f"/api/bom/projects/{pid}/ibom").content == page
        assert client.post("/api/bom/projects/999999/ibom", files={"file": ("i.html", page, "text/html")}).status_code == 404

        client.delete(f"/api/bom/projects/{pid}/ibom")
        assert client.get(f"/api/bom/projects/{pid}/ibom").status_code == 404
        # deleting the project removes the file too
        client.post(f"/api/bom/projects/{pid}/ibom", files={"file": ("ibom.html", page, "text/html")})
    finally:
        client.delete(f"/api/bom/projects/{pid}")
    from app.api.bom import _ibom_path
    assert not _ibom_path(pid).exists()


# -- the board drawn by PartsNAS itself -------------------------------------------------------

def test_a_kicad_board_can_be_previewed_and_kept_with_the_project(client):
    from pathlib import Path

    board = (Path(__file__).parent / "fixtures" / "mini.kicad_pcb").read_bytes()
    up = lambda: {"file": ("mini.kicad_pcb", board, "application/octet-stream")}  # noqa: E731

    r = client.post("/api/bom/board/parse", files=up())
    assert r.status_code == 200, r.text
    assert {f["ref"] for f in r.json()["footprints"]} == {"R1", "R2", "C1", "C2", "C3", "J1"}
    assert client.post("/api/bom/board/parse", files={"file": ("x.kicad_pcb", b"not a board", "text/plain")}).status_code == 400

    pid = client.post("/api/bom/projects", json={"name": "ZZ_BOARD proj", "lines": [
        {"value": "10k", "footprint": "R_0603", "qty": 1, "refdes": "R1"}]}).json()["id"]
    try:
        assert client.get(f"/api/bom/projects/{pid}").json()["has_board"] is False
        assert client.get(f"/api/bom/projects/{pid}/board").status_code == 404
        up_r = client.post(f"/api/bom/projects/{pid}/board", files=up())
        assert up_r.status_code == 200 and up_r.json()["footprints"] == 6
        got = client.get(f"/api/bom/projects/{pid}/board")
        assert got.status_code == 200 and len(got.json()["footprints"]) == 6
        assert client.get(f"/api/bom/projects/{pid}").json()["has_board"] is True
        assert client.post("/api/bom/projects/999999/board", files=up()).status_code == 404
        client.delete(f"/api/bom/projects/{pid}/board")
        assert client.get(f"/api/bom/projects/{pid}/board").status_code == 404
        client.post(f"/api/bom/projects/{pid}/board", files=up())
    finally:
        client.delete(f"/api/bom/projects/{pid}")
    from app.api.bom import _board_path
    assert not _board_path(pid).exists()
