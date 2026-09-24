"""The KiCad HTTP library (KiCad's symbol chooser asking PartsNAS) and the standard names for passives."""
from app.kicadlib import is_named, suggest_names


def test_standard_passives_get_kicads_own_names():
    s = suggest_names("Passive > Capacitor > Ceramic", "0603")
    assert s == {"symbol": "Device:C", "footprint": "Capacitor_SMD:C_0603_1608Metric", "reference": "C"}
    assert suggest_names("Passive > Resistor > Thick film", "0805 (2012 Metric)")["footprint"] == "Resistor_SMD:R_0805_2012Metric"
    assert suggest_names("Passive > Inductor > Shielded", "1008")["footprint"] == "Inductor_SMD:L_1008_2520Metric"
    assert suggest_names("Semiconductor > Diode > LED", "0603")["symbol"] == "Device:LED"
    assert suggest_names("Passive > Resistor > Thick film", "1812")["footprint"] == "Resistor_SMD:R_1812_4532Metric"


def test_things_that_are_not_plain_smd_passives_are_left_alone():
    assert suggest_names("Passive > Capacitor > Electrolytic (Al)", "6.3mm") is None       # a can, not a size code
    assert suggest_names("Passive > Capacitor > Tantalum", "1210") is None                # polarised: not Device:C
    assert suggest_names("Passive > Resistor > Resistor network", "1206") is None         # an array, not one resistor
    assert suggest_names("Passive > Capacitor > Ceramic", "1008") is None                 # KiCad has no C_1008
    assert suggest_names("Passive > Capacitor > Ceramic", "10.16mm") is None              # "0.16mm"/"10.16" is no size code
    assert suggest_names("Passive > Capacitor > Ceramic", None) is None
    assert suggest_names("Connector > Crimp", "0603") is None


def test_a_part_is_ready_only_when_both_names_carry_their_library():
    assert is_named("Device:C", "Capacitor_SMD:C_0603_1608Metric")
    assert not is_named("Device:C", "C_0603_1608Metric")
    assert not is_named("C", "Capacitor_SMD:C_0603_1608Metric")
    assert not is_named(None, None)


def _cat(client, name):
    r = client.post("/api/categories", json={"name": name, "parent_id": None})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def test_kicad_sees_only_ready_parts_and_gets_the_fields_it_expects(client):
    cid = _cat(client, "ZZ_KICAD cat")
    a = client.post("/api/parts", json={"name": "ZZ_KICAD 100n", "mpn": "ZZ-K-1", "manufacturer": "KEMET", "category_id": cid,
                                        "kicad_symbol": "Device:C", "kicad_footprint": "Capacitor_SMD:C_0603_1608Metric",
                                        "attributes": {"value": "100nF"}}).json()["id"]
    b = client.post("/api/parts", json={"name": "ZZ_KICAD unnamed", "mpn": "ZZ-K-2", "category_id": cid}).json()["id"]
    try:
        assert client.get("/api/kicad/v1/").json() == {"categories": "", "parts": ""}
        cats = client.get("/api/kicad/v1/categories.json").json()
        mine = [c for c in cats if c["name"] == "ZZ_KICAD cat"]
        assert len(mine) == 1 and isinstance(mine[0]["id"], str)              # every value is a string
        listed = client.get(f"/api/kicad/v1/parts/category/{mine[0]['id']}.json").json()
        assert [p["id"] for p in listed] == [a]                                # b has no symbol/footprint: not shown
        part = client.get(f"/api/kicad/v1/parts/{a}.json").json()
        assert part["symbolIdStr"] == "Device:C" and part["id"] == a
        f = part["fields"]
        assert f["value"]["value"] == "100nF" and f["footprint"] == {"value": "Capacitor_SMD:C_0603_1608Metric", "visible": "False"}
        assert f["MPN"]["value"] == "ZZ-K-1" and f["Manufacturer"]["value"] == "KEMET" and f["reference"]["value"] == "C"
        assert f["datasheet"]["value"] == "~"                                  # KiCad's own "none"
        assert client.get(f"/api/kicad/v1/parts/{b}.json").status_code == 404
        assert client.get("/api/kicad/v1/parts/nope.json").status_code == 404
    finally:
        for p in (a, b):
            client.delete(f"/api/parts/{p}")
        client.delete(f"/api/categories/{cid}")


def test_suggested_names_fill_only_what_is_empty(client):
    cats = client.get("/api/categories").json()

    def find(nodes, name):
        for n in nodes:
            if n["name"] == name:
                return n
            got = find(n.get("children") or [], name)
            if got:
                return got
    ceramic = find(cats, "Ceramic")
    assert ceramic, "the seed has a Ceramic category"
    a = client.post("/api/parts", json={"name": "ZZ_SUGG 100n", "mpn": "ZZ-S-1", "category_id": ceramic["id"], "footprint_raw": "0603"}).json()["id"]
    b = client.post("/api/parts", json={"name": "ZZ_SUGG own", "mpn": "ZZ-S-2", "category_id": ceramic["id"], "footprint_raw": "0402",
                                        "kicad_footprint": "My_Lib:My_C_0402"}).json()["id"]
    try:
        sug = client.get("/api/kicad/suggest").json()
        by = {p["id"]: p for p in sug["proposals"]}
        assert by[a]["symbol"] == "Device:C" and by[a]["footprint"] == "Capacitor_SMD:C_0603_1608Metric"
        assert by[b]["symbol"] == "Device:C" and by[b]["footprint"] is None      # the footprint typed by hand is left alone
        assert client.post("/api/kicad/apply", json={"ids": [a, b]}).json()["updated"] == 2
        pa, pb = client.get(f"/api/parts/{a}").json(), client.get(f"/api/parts/{b}").json()
        assert (pa["kicad_symbol"], pa["kicad_footprint"]) == ("Device:C", "Capacitor_SMD:C_0603_1608Metric")
        assert (pb["kicad_symbol"], pb["kicad_footprint"]) == ("Device:C", "My_Lib:My_C_0402")
        assert client.get(f"/api/kicad/v1/parts/{a}.json").status_code == 200   # now ready
        assert client.get("/api/kicad/suggest").json()["ready"] >= 2
        assert client.post("/api/kicad/apply", json={"ids": [a]}).json()["updated"] == 0   # nothing left to fill
    finally:
        for p in (a, b):
            client.delete(f"/api/parts/{p}")
