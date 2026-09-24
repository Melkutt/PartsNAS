"""Footprint rules for ICs / transistors / diodes, the 8-SOIC -> SOIC-8 tidy-up, and KiCad's category scope."""
from app.kicadrules import default_rules, footprint_text_from_lookup, match_rule, normalize_package, package_texts, validate_rule

RULES = default_rules()


def hit(case="", device="", raw="", path=""):
    return match_rule(RULES, {"case": case, "device": device, "raw": raw}, path)


def test_the_width_in_the_package_case_picks_the_right_footprint():
    assert hit(case='8-SOIC (0.154", 3.90mm Width)')["footprint"] == "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"
    assert hit(case='8-SOIC (0.209", 5.30mm Width)')["footprint"] == "Package_SO:SOIC-8W_5.3x5.3mm_P1.27mm"
    assert hit(case='16-SOIC (0.154", 3.90mm Width)')["footprint"] == "Package_SO:SOIC-16_3.9x9.9mm_P1.27mm"
    # two families in one string: the width belongs to the MSOP
    assert hit(case='8-TSSOP, 8-MSOP (0.118", 3.00mm Width)')["footprint"] == "Package_SO:MSOP-8_3x3mm_P0.65mm"
    assert hit(case='10-TFSOP, 10-MSOP (0.118", 3.00mm Width)')["footprint"] == "Package_SO:MSOP-10_3x3mm_P0.5mm"


def test_package_aliases_and_things_that_must_not_match():
    assert hit(case="SC-74A, SOT-753")["footprint"] == "Package_TO_SOT_SMD:SOT-23-5"
    assert hit(case="SOT-23-6 Thin, TSOT-23-6")["footprint"] == "Package_TO_SOT_SMD:TSOT-23-6"
    assert hit(case="TO-261-4, TO-261AA")["footprint"] == "Package_TO_SOT_SMD:SOT-223-3_TabPin2"
    assert hit(case="TO-220-3 Full Pack, Isolated Tab")["footprint"].endswith("TO-220F-3_Vertical")
    assert hit(case="TO-220-3")["footprint"].endswith("TO-220-3_Vertical")
    assert hit(case="DO-214AC, SMA")["footprint"] == "Diode_SMD:D_SMA"
    assert hit(case='8-SOIC (0.154", 3.90mm Width) Exposed Pad') is None       # many EP variants: not guessed
    assert hit(case="20-WFQFN Exposed Pad") is None
    assert hit(case="38-SMD Module") is None
    assert hit(case="TO-226-3, TO-92-3 (TO-226AA) Formed Leads") is None


def test_a_rule_that_only_reads_your_own_footprint_text_is_a_guess():
    r = hit(raw="SOIC-8")
    assert r["assumed"] is True and r["footprint"].startswith("Package_SO:SOIC-8_3.9x4.9mm")
    assert hit(raw="SOT-23-5")["assumed"] is False                 # a name with no variants is not a guess
    # the supplier's width beats the guess
    assert hit(case='8-SOIC (0.209", 5.30mm Width)', raw="SOIC-8")["assumed"] is False


def test_user_rules_come_first_and_are_checked():
    mine = [{"id": "mine", "when": {"raw": "^SOIC-8$"}, "footprint": "My:SOIC-8_special"}]
    assert match_rule([*mine, *RULES], {"raw": "SOIC-8"})["footprint"] == "My:SOIC-8_special"
    assert match_rule([{"id": "x", "scope": "diode", "when": {"raw": "^X$"}, "footprint": "A:B"}], {"raw": "X"}, "Passive > Resistor") is None
    assert validate_rule({"when": {"raw": "^X$"}, "footprint": "A:B"})["footprint"] == "A:B"
    for bad in ({"when": {}, "footprint": "A:B"}, {"when": {"raw": "("}, "footprint": "A:B"}, {"when": {"raw": "x"}, "footprint": "NoLibrary"}):
        try:
            validate_rule(bad)
            assert False, bad
        except ValueError:
            pass


def test_the_suppliers_package_is_written_the_way_people_write_it():
    assert normalize_package("8-SOIC") == "SOIC-8"
    assert normalize_package("16-SO") == "SOIC-16"
    assert normalize_package("8-PDIP") == "DIP-8"
    assert normalize_package("44-TQFP (10x10)") == "TQFP-44"
    assert normalize_package("10-MSOP") == "MSOP-10"
    assert normalize_package("SOT-23-5") == "SOT-23-5"
    assert normalize_package("8-SMD Module") == "8-SMD Module"        # not a package family to reorder
    assert normalize_package(None) is None and normalize_package("") is None
    assert footprint_text_from_lookup({"Supplier Device Package": "8-SOIC", "Package / Case": '8-SOIC (0.154", 3.90mm Width)'}) == "SOIC-8"
    assert footprint_text_from_lookup({"Package / Case": '16-SOIC (0.154", 3.90mm Width)'}) == "SOIC-16"
    assert package_texts({"packagecase": "A", "supplierdevicepackage": "B"}, "C") == {"case": "A", "device": "B", "raw": "C"}


def _cat(client, name, parent=None):
    r = client.post("/api/categories", json={"name": name, "parent_id": parent})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def test_a_new_part_gets_its_kicad_footprint_when_a_rule_is_certain(client):
    cid = _cat(client, "ZZ_RULES cat")
    a = client.post("/api/parts", json={"name": "ZZ_RULES opamp", "mpn": "ZZ-R-1", "category_id": cid,
                                        "attributes": {"packagecase": '8-SOIC (0.154", 3.90mm Width)'}}).json()["id"]
    b = client.post("/api/parts", json={"name": "ZZ_RULES guess", "mpn": "ZZ-R-2", "category_id": cid, "footprint_raw": "SOIC-8"}).json()["id"]
    c = client.post("/api/parts", json={"name": "ZZ_RULES own", "mpn": "ZZ-R-3", "category_id": cid, "kicad_footprint": "My:Own",
                                        "attributes": {"packagecase": '8-SOIC (0.154", 3.90mm Width)'}}).json()["id"]
    try:
        get = lambda i: client.get(f"/api/parts/{i}").json()["kicad_footprint"]  # noqa: E731
        assert get(a) == "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"
        assert get(b) is None                                       # only a guess: not filled in for you
        assert get(c) == "My:Own"                                   # never replaced
        sug = {p["id"]: p for p in client.get(f"/api/kicad/suggest?category_id={cid}").json()["proposals"]}
        assert set(sug) == {b}                                      # a and c are done; b is proposed, as a guess
        assert sug[b]["assumed"] is True and sug[b]["rule"] == "raw-soic-8"
    finally:
        for p in (a, b, c):
            client.delete(f"/api/parts/{p}")
        client.delete(f"/api/categories/{cid}")


def test_kicad_only_looks_at_the_chosen_category_and_the_rules_can_be_edited(client):
    top = _cat(client, "ZZ_SCOPE top")
    sub = _cat(client, "ZZ_SCOPE sub", top)
    other = _cat(client, "ZZ_SCOPE other")

    def mk(name, cat):
        return client.post("/api/parts", json={"name": name, "mpn": name, "category_id": cat, "footprint_raw": "SOT-23-5"}).json()["id"]

    a, b, c = mk("ZZ_SC a", top), mk("ZZ_SC b", sub), mk("ZZ_SC c", other)
    try:
        # created with a raw SOT-23-5 (certain), so already filled in: clear it to see the proposal
        for i in (a, b, c):
            client.patch(f"/api/parts/{i}", json={"kicad_footprint": None})

        def ids(cat):
            return {p["id"] for p in client.get(f"/api/kicad/suggest?category_id={cat}").json()["proposals"]}

        assert ids(top) == {a, b}                                   # the category and everything below it
        assert ids(other) == {c}
        assert client.post("/api/kicad/apply", json={"ids": [a, b, c], "category_id": top}).json()["updated"] == 2
        assert client.get(f"/api/parts/{c}").json()["kicad_footprint"] is None     # outside the chosen category: untouched
        # rules from Settings
        assert client.put("/api/kicad/rules", json={"rules": [{"id": "r", "when": {"raw": "^ZZ$"}, "footprint": "Lib:Fp"}]}).status_code == 200
        assert client.get("/api/kicad/rules").json()["user"][0]["footprint"] == "Lib:Fp"
        assert client.put("/api/kicad/rules", json={"rules": [{"when": {"raw": "("}, "footprint": "A:B"}]}).status_code == 400
    finally:
        client.put("/api/kicad/rules", json={"rules": []})
        for p in (a, b, c):
            client.delete(f"/api/parts/{p}")
        for cid in (sub, top, other):
            client.delete(f"/api/categories/{cid}")


def test_a_footprint_typed_without_its_library_gets_the_library_added(client):
    cid = _cat(client, "ZZ_LIB cat")
    a = client.post("/api/parts", json={"name": "ZZ_LIB soic", "mpn": "ZZ-L-1", "category_id": cid, "footprint_raw": "SOIC-8",
                                        "kicad_footprint": "SOIC-8_3.9x4.9mm_P1.27mm",
                                        "attributes": {"packagecase": '8-SOIC (0.154", 3.90mm Width)'}}).json()["id"]
    b = client.post("/api/parts", json={"name": "ZZ_LIB other", "mpn": "ZZ-L-2", "category_id": cid, "footprint_raw": "SOIC-8",
                                        "kicad_footprint": "Something_else",
                                        "attributes": {"packagecase": '8-SOIC (0.154", 3.90mm Width)'}}).json()["id"]
    try:
        sug = {p["id"]: p for p in client.get(f"/api/kicad/suggest?category_id={cid}").json()["proposals"]}
        assert set(sug) == {a}                                     # b's footprint is something else: left alone
        assert sug[a]["footprint"] == "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm" and "adds the library" in sug[a]["rule"]
        assert client.post("/api/kicad/apply", json={"ids": [a, b], "category_id": cid}).json()["updated"] == 1
        assert client.get(f"/api/parts/{a}").json()["kicad_footprint"] == "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"
        assert client.get(f"/api/parts/{b}").json()["kicad_footprint"] == "Something_else"
    finally:
        for p in (a, b):
            client.delete(f"/api/parts/{p}")
        client.delete(f"/api/categories/{cid}")


def test_a_lookup_fills_the_footprint_the_way_people_write_it_and_the_kicad_footprint(client):
    cid = _cat(client, "ZZ_LOOK cat")
    a = client.post("/api/parts", json={"name": "ZZ_LOOK opamp", "mpn": "ZZ-LK-1", "category_id": cid}).json()["id"]
    b = client.post("/api/parts", json={"name": "ZZ_LOOK typed", "mpn": "ZZ-LK-2", "category_id": cid, "footprint_raw": "My own text"}).json()["id"]
    result = {"provider": "digikey", "mpn": "X", "attributes": {"Supplier Device Package": "8-SOIC", "Package / Case": '8-SOIC (0.154", 3.90mm Width)'}}
    try:
        for pid in (a, b):
            r = client.post(f"/api/parts/{pid}/apply-lookup", json={"result": result, "apply": {}})
            assert r.status_code == 200, r.text
        pa, pb = client.get(f"/api/parts/{a}").json(), client.get(f"/api/parts/{b}").json()
        assert pa["footprint_raw"] == "SOIC-8"                                           # not the supplier's "8-SOIC"
        assert pa["kicad_footprint"] == "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"          # the width said which SOIC-8
        assert pb["footprint_raw"] == "My own text"                                      # what you typed stays
        assert pb["kicad_footprint"] == "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"
    finally:
        for p in (a, b):
            client.delete(f"/api/parts/{p}")
        client.delete(f"/api/categories/{cid}")
