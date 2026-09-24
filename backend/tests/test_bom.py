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
        assert found("not a value") == set()             # not a number: matched as text, never silently ignored
        assert found("zz_val 1uf") == {a}
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


# -- lines that are not part of the build, and editing a saved line ------------------------------

def test_skipped_lines_are_left_out_of_shortages_and_builds(client):
    loc = _location(client)[0]
    a = _part(client, "ZZ_SKIP screw", "ZZ-SKIP-A")
    h = _part(client, "ZZ_SKIP hole part", "ZZ-SKIP-H")
    try:
        for p in (a, h):
            client.post(f"/api/parts/{p}/stock", json={"location_id": loc, "delta": 10, "kind": "add"})
        pid = client.post("/api/bom/projects", json={"name": "ZZ_SKIP proj", "lines": [
            {"value": "M3", "footprint": "x", "qty": 2, "refdes": "C1", "part_id": a},
            {"value": "Hole", "footprint": "MountingHole", "qty": 4, "refdes": "H1 H2 H3 H4", "part_id": h, "ignored": True},
            {"value": "?", "footprint": "Logo", "qty": 1, "refdes": "G1", "ignored": True},
        ]}).json()["id"]
        summary = client.get("/api/bom/projects").json()[0]
        assert (summary["line_count"], summary["ignored_count"], summary["unresolved_count"]) == (1, 2, 0)
        d = client.get(f"/api/bom/projects/{pid}", params={"boards": 3}).json()
        by = {ln["refdes"]: ln for ln in d["lines"]}
        assert by["H1 H2 H3 H4"]["ignored"] is True and by["H1 H2 H3 H4"]["needed"] == 0 and by["H1 H2 H3 H4"]["short"] is None
        assert by["C1"]["needed"] == 6
        client.post(f"/api/bom/projects/{pid}/build", json={"boards": 3})
        assert client.get(f"/api/parts/{a}").json()["on_hand"] == 4      # 10 - 6
        assert client.get(f"/api/parts/{h}").json()["on_hand"] == 10     # untouched
        client.delete(f"/api/bom/projects/{pid}")
    finally:
        for p in (a, h):
            client.delete(f"/api/parts/{p}")


def test_a_saved_line_can_be_edited(client):
    x = _part(client, "ZZ_EDIT 1n X7R", "ZZ-EDIT-X")
    y = _part(client, "ZZ_EDIT 1n C0G", "ZZ-EDIT-Y")
    pid = client.post("/api/bom/projects", json={"name": "ZZ_EDIT proj", "lines": [
        {"value": "1n", "footprint": "C_0603_1608Metric", "qty": 1, "refdes": "C1", "part_id": x}]}).json()["id"]
    try:
        lid = client.get(f"/api/bom/projects/{pid}").json()["lines"][0]["id"]
        url = f"/api/bom/projects/{pid}/lines/{lid}"
        assert client.patch(url, json={"part_id": y, "remember": True}).status_code == 200
        assert client.get(f"/api/bom/projects/{pid}").json()["lines"][0]["part_id"] == y
        assert any(r["part_id"] == y for r in client.get("/api/bom/match-rules").json())      # remembered for the next BOM
        assert client.patch(url, json={"ignored": True, "qty_per_board": 3}).status_code == 200
        line = client.get(f"/api/bom/projects/{pid}").json()["lines"][0]
        assert line["ignored"] is True and line["qty_per_board"] == 3 and line["part_id"] == y
        assert client.patch(url, json={"part_id": None, "ignored": False}).status_code == 200
        assert client.get(f"/api/bom/projects/{pid}").json()["lines"][0]["part_id"] is None
        assert client.patch(url, json={"part_id": "nope"}).status_code == 400
        assert client.patch(f"/api/bom/projects/{pid}/lines/999999", json={"ignored": True}).status_code == 404
        assert client.patch(f"/api/bom/projects/999999/lines/{lid}", json={"ignored": True}).status_code == 404
        for r in client.get("/api/bom/match-rules").json():
            client.delete(f"/api/bom/match-rules/{r['id']}")
    finally:
        client.delete(f"/api/bom/projects/{pid}")
        for p in (x, y):
            client.delete(f"/api/parts/{p}")


# -- renaming, "Placed", boards drawn by an older parser ----------------------------------------

def test_a_project_can_be_renamed(client):
    a = client.post("/api/bom/projects", json={"name": "ZZ_REN a", "lines": []}).json()["id"]
    b = client.post("/api/bom/projects", json={"name": "ZZ_REN b", "lines": []}).json()["id"]
    try:
        assert client.patch(f"/api/bom/projects/{a}", json={"name": "  ZZ_REN renamed "}).status_code == 200
        assert client.get(f"/api/bom/projects/{a}").json()["name"] == "ZZ_REN renamed"
        assert client.patch(f"/api/bom/projects/{a}", json={"name": "ZZ_REN b"}).status_code == 409
        assert client.patch(f"/api/bom/projects/{a}", json={"name": "ZZ_REN renamed"}).status_code == 200   # same name, itself
        assert client.patch(f"/api/bom/projects/{a}", json={"name": " "}).status_code == 400
        assert client.patch("/api/bom/projects/999999", json={"name": "x"}).status_code == 404
    finally:
        for p in (a, b):
            client.delete(f"/api/bom/projects/{p}")


def test_lines_can_be_ticked_off_as_placed(client):
    pid = client.post("/api/bom/projects", json={"name": "ZZ_PLACED proj", "lines": [
        {"value": "1k", "qty": 1, "refdes": "R1"}, {"value": "2k", "qty": 1, "refdes": "R2"}, {"value": "H", "qty": 1, "refdes": "H1", "ignored": True}]}).json()["id"]
    try:
        lines = client.get(f"/api/bom/projects/{pid}").json()["lines"]
        assert not any(ln["placed"] for ln in lines)
        assert client.patch(f"/api/bom/projects/{pid}/lines/{lines[0]['id']}", json={"placed": True}).status_code == 200
        got = client.get(f"/api/bom/projects/{pid}").json()
        assert [ln["placed"] for ln in got["lines"]] == [True, False, False] and got["placed_count"] == 1
        assert client.post(f"/api/bom/projects/{pid}/placed", json={"placed": True, "line_ids": [lines[1]["id"]]}).status_code == 200
        assert client.get(f"/api/bom/projects/{pid}").json()["placed_count"] == 2
        assert client.post(f"/api/bom/projects/{pid}/placed", json={"placed": False}).status_code == 200      # start over
        assert client.get(f"/api/bom/projects/{pid}").json()["placed_count"] == 0
        assert client.post("/api/bom/projects/999999/placed", json={"placed": True}).status_code == 404
    finally:
        client.delete(f"/api/bom/projects/{pid}")


def test_a_board_drawn_by_an_older_parser_is_drawn_again_from_the_kept_file(client):
    import json
    from pathlib import Path

    from app.api.bom import _board_path, _board_source
    board = (Path(__file__).parent / "fixtures" / "mini.kicad_pcb").read_bytes()
    pid = client.post("/api/bom/projects", json={"name": "ZZ_REDRAW proj", "lines": []}).json()["id"]
    try:
        client.post(f"/api/bom/projects/{pid}/board", files={"file": ("m.kicad_pcb", board, "application/octet-stream")})
        assert _board_source(pid).is_file()
        old = json.loads(_board_path(pid).read_text(encoding="utf-8"))
        old["format"] = 1
        old["gfx"]["F.SilkS"] = [p for p in old["gfx"]["F.SilkS"] if p[0] != "t"]          # what a v1 file looked like
        _board_path(pid).write_text(json.dumps(old), encoding="utf-8")
        got = client.get(f"/api/bom/projects/{pid}/board").json()
        assert got["format"] >= 2 and any(p[0] == "t" for p in got["gfx"]["F.SilkS"])
        client.delete(f"/api/bom/projects/{pid}/board")
        assert not _board_source(pid).exists()
    finally:
        client.delete(f"/api/bom/projects/{pid}")


def test_lines_carry_what_the_part_costs_for_the_price_summary(client):
    loc = _location(client)[0]
    a = _part(client, "ZZ_COST priced", "ZZ-COST-A")
    b = _part(client, "ZZ_COST unpriced", "ZZ-COST-B")
    pid = None
    try:
        r = client.post(f"/api/parts/{a}/stock", json={"location_id": loc, "delta": 10, "kind": "add",
                                                       "unit_price": 2.0, "vat_percent": 25, "currency": "SEK", "link_to_part": False})
        assert r.status_code in (200, 201), r.text
        client.post(f"/api/parts/{b}/stock", json={"location_id": loc, "delta": 1, "kind": "add"})
        pid = client.post("/api/bom/projects", json={"name": "ZZ_COST proj", "lines": [
            {"value": "1k", "qty": 3, "refdes": "R1 R2 R3", "part_id": a},
            {"value": "2k", "qty": 1, "refdes": "R4", "part_id": b},
            {"value": "H", "qty": 1, "refdes": "H1", "part_id": a, "ignored": True},
            {"value": "?", "qty": 1, "refdes": "R5"}]}).json()["id"]
        by = {ln["refdes"]: ln for ln in client.get(f"/api/bom/projects/{pid}?boards=2").json()["lines"]}
        assert (by["R1 R2 R3"]["unit_cost"], by["R1 R2 R3"]["currency"], by["R1 R2 R3"]["vat_percent"]) == (2.0, "SEK", 25)
        assert by["R1 R2 R3"]["needed"] == 6
        assert by["R4"]["unit_cost"] is None and by["R5"]["unit_cost"] is None and by["H1"]["unit_cost"] is None
    finally:
        if pid:
            client.delete(f"/api/bom/projects/{pid}")
        for p in (a, b):
            client.delete(f"/api/parts/{p}")


def test_browse_filters_by_a_value_that_is_not_a_number_and_lists_prices(client):
    loc = _location(client)[0]
    a = client.post("/api/parts", json={"name": "ZZ_BROWSE TestPoint_2Pole", "mpn": "ZZ-TP-1"}).json()["id"]
    b = client.post("/api/parts", json={"name": "ZZ_BROWSE Resistor", "mpn": "ZZ-R-1"}).json()["id"]
    try:
        client.post(f"/api/parts/{a}/stock", json={"location_id": loc, "delta": 5, "kind": "add", "unit_price": 0.0123,
                                                   "vat_percent": 25, "currency": "SEK", "link_to_part": False})
        # "TestPoint_2Pole" is not a number: it used to be ignored, so the list was not filtered at all
        got = client.get("/api/parts", params={"value_eq": "TestPoint_2Pole", "limit": 1000}).json()["items"]
        assert [p["id"] for p in got] == [a]
        assert got[0]["unit_price"] == 0.0123 and got[0]["currency"] == "SEK"
        assert client.get("/api/parts", params={"value_eq": "nothing-like-this"}).json()["items"] == []
        rows = {p["id"]: p for p in client.get("/api/parts", params={"q": "ZZ_BROWSE", "limit": 1000}).json()["items"]}
        assert rows[b]["unit_price"] is None
    finally:
        for p in (a, b):
            client.delete(f"/api/parts/{p}")


def test_bulk_prices_follow_the_same_rule_as_a_quote(client, db_session=None):
    from app.api.quotes import snapshot_cost
    from app.core.db import SessionLocal
    from app.services import unit_cost_map
    loc = _location(client)[0]
    a = _part(client, "ZZ_PRICE a", "ZZ-PRICE-A")
    b = _part(client, "ZZ_PRICE b", "ZZ-PRICE-B")
    try:
        client.post(f"/api/parts/{a}/stock", json={"location_id": loc, "delta": 5, "kind": "add", "unit_price": 1.5,
                                                   "vat_percent": 25, "currency": "SEK", "link_to_part": False})
        client.post(f"/api/parts/{a}/stock", json={"location_id": loc, "delta": 5, "kind": "add", "unit_price": 2.5,
                                                   "vat_percent": 12, "currency": "SEK", "link_to_part": False})
        with SessionLocal() as db:
            bulk = unit_cost_map(db, [a, b])
            cost, cur, _src, vat = snapshot_cost(db, a)
            assert bulk[a] == (cost, cur, vat) == (2.5, "SEK", 12)          # the most recent priced purchase
            assert b not in bulk and snapshot_cost(db, b)[0] == 0.0          # no price: absent here, 0 there
    finally:
        for p in (a, b):
            client.delete(f"/api/parts/{p}")


def test_references_can_be_ticked_as_placed_one_by_one(client):
    pid = client.post("/api/bom/projects", json={"name": "ZZ_REFS proj", "lines": [
        {"value": "100n", "qty": 3, "refdes": "C1 C2, C3"}, {"value": "1k", "qty": 1, "refdes": "R1"}]}).json()["id"]
    try:
        get = lambda: {ln["refdes"]: ln for ln in client.get(f"/api/bom/projects/{pid}").json()["lines"]}  # noqa: E731
        caps, res = get()["C1 C2, C3"], get()["R1"]
        assert caps["placed_refs"] == [] and caps["placed"] is False
        url = f"/api/bom/projects/{pid}/lines/{caps['id']}"
        assert client.patch(url, json={"placed_refs": ["C2", "C9"]}).status_code == 200      # C9 is not on the line
        line = get()["C1 C2, C3"]
        assert line["placed_refs"] == ["C2"] and line["placed"] is False
        assert client.patch(url, json={"placed_refs": ["C1", "C2", "C3"]}).status_code == 200
        line = get()["C1 C2, C3"]
        assert line["placed"] is True and line["placed_refs"] == ["C1", "C2", "C3"]     # all ticked = the line is done
        assert client.patch(url, json={"placed": False}).status_code == 200
        assert get()["C1 C2, C3"]["placed_refs"] == [] and get()["C1 C2, C3"]["placed"] is False
        assert client.patch(url, json={"placed": True}).status_code == 200                # ticking the line ticks all
        assert get()["C1 C2, C3"]["placed_refs"] == ["C1", "C2", "C3"]
        # a line ticked before individual ticks existed (placed, no list) still reads as all placed
        from app.core.db import SessionLocal
        from app.models import BomLine
        with SessionLocal() as db:
            ln = db.get(BomLine, res["id"])
            ln.placed, ln.placed_refs = True, None
            db.commit()
        assert get()["R1"]["placed_refs"] == ["R1"]
        assert client.post(f"/api/bom/projects/{pid}/placed", json={"placed": False}).status_code == 200
        assert all(ln["placed_refs"] == [] for ln in get().values())
    finally:
        client.delete(f"/api/bom/projects/{pid}")
