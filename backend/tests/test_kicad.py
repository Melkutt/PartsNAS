"""The KiCad HTTP library (KiCad's symbol chooser asking PartsNAS) and the standard names for passives."""
from app.kicadlib import is_named, suggest_names


def test_standard_passives_get_kicads_own_names():
    s = suggest_names("Passive > Capacitor > Ceramic", "0603")
    assert s == {"symbol": "Device:C", "footprint": "Capacitor_SMD:C_0603_1608Metric", "reference": "C",
                 "alts": ["Capacitor_SMD:C_0603_1608Metric_Pad1.08x0.95mm_HandSolder"]}
    hand = suggest_names("Passive > Capacitor > Ceramic", "0603", "hand")
    assert hand["footprint"] == "Capacitor_SMD:C_0603_1608Metric_Pad1.08x0.95mm_HandSolder"
    assert hand["alts"] == ["Capacitor_SMD:C_0603_1608Metric"]
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


def test_footprint_lists_and_filters():
    from app.kicadlib import footprint_filters, split_footprints
    assert split_footprints("A:x\n B:y; A:x,,C:z ") == ["A:x", "B:y", "C:z"]
    assert split_footprints(None) == []
    # every pad variant of the package is offered by a wildcard, the named ones exactly
    assert footprint_filters("Capacitor_SMD:C_0603_1608Metric_Pad1.08x0.95mm_HandSolder", ["Capacitor_SMD:C_0603_1608Metric"]) == [
        "Capacitor_SMD:C_0603_1608Metric*", "Capacitor_SMD:C_0603_1608Metric"]
    assert footprint_filters("My_Lib:Odd", ["Other:Thing"]) == ["Other:Thing"]


def test_a_part_with_several_footprints_is_listed_once_per_footprint(client):
    cid = _cat(client, "ZZ_KICAD alts")
    a = client.post("/api/parts", json={
        "name": "ZZ_KICAD 100n alts", "mpn": "ZZ-K-3", "category_id": cid, "kicad_symbol": "Device:C",
        "kicad_footprint": "Capacitor_SMD:C_0603_1608Metric_Pad1.08x0.95mm_HandSolder",
        "kicad_footprint_alts": "Capacitor_SMD:C_0603_1608Metric\nnot-a-library-name"}).json()["id"]
    try:
        cat = [c for c in client.get("/api/kicad/v1/categories.json").json() if c["name"] == "ZZ_KICAD alts"][0]
        listed = client.get(f"/api/kicad/v1/parts/category/{cat['id']}.json").json()
        assert [p["id"] for p in listed] == [a, f"{a}~1"]                       # the name without a library is ignored
        assert listed[1]["name"] == "ZZ_KICAD 100n alts · C_0603_1608Metric"
        main = client.get(f"/api/kicad/v1/parts/{a}.json").json()
        alt = client.get(f"/api/kicad/v1/parts/{a}~1.json").json()
        assert main["fields"]["footprint"]["value"].endswith("HandSolder")
        assert alt["fields"]["footprint"]["value"] == "Capacitor_SMD:C_0603_1608Metric"
        assert alt["fields"]["MPN"]["value"] == "ZZ-K-3" and alt["symbolIdStr"] == "Device:C"     # same part, other footprint
        assert "Capacitor_SMD:C_0603_1608Metric*" in main["footprint_filters"]
        assert client.get(f"/api/kicad/v1/parts/{a}~2.json").status_code == 404
        assert client.get(f"/api/kicad/v1/parts/{a}~x.json").status_code == 404
    finally:
        client.delete(f"/api/parts/{a}")
        client.delete(f"/api/categories/{cid}")


def test_suggestions_offer_the_other_kind_of_pads_and_respect_the_default(client):
    cats = client.get("/api/categories").json()

    def find(nodes, name):
        for n in nodes:
            if n["name"] == name:
                return n
            got = find(n.get("children") or [], name)
            if got:
                return got
    ceramic = find(cats, "Ceramic")
    a = client.post("/api/parts", json={"name": "ZZ_SUGG2 100n", "mpn": "ZZ-S-3", "category_id": ceramic["id"], "footprint_raw": "0603"}).json()["id"]
    try:
        std = {p["id"]: p for p in client.get("/api/kicad/suggest?prefer=standard").json()["proposals"]}[a]
        hand = {p["id"]: p for p in client.get("/api/kicad/suggest?prefer=hand").json()["proposals"]}[a]
        assert std["footprint"] == "Capacitor_SMD:C_0603_1608Metric" and std["alts"][0].endswith("HandSolder")
        assert hand["footprint"].endswith("HandSolder") and hand["alts"] == ["Capacitor_SMD:C_0603_1608Metric"]
        assert client.post("/api/kicad/apply", json={"ids": [a], "prefer": "hand"}).json()["updated"] == 1
        part = client.get(f"/api/parts/{a}").json()
        assert part["kicad_footprint"].endswith("HandSolder") and part["kicad_footprint_alts"] == "Capacitor_SMD:C_0603_1608Metric"
        assert client.post("/api/kicad/apply", json={"ids": [a], "prefer": "standard"}).json()["updated"] == 0   # already filled: left alone
    finally:
        client.delete(f"/api/parts/{a}")
