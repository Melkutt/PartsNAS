from app.dupes import norm_mpn


def test_mpns_are_compared_without_punctuation_or_case():
    assert norm_mpn("MFR-12FTF52-3K3") == norm_mpn("mfr12ftf52 3k3") == norm_mpn(" MFR12FTF523K3 ")
    assert norm_mpn("") is None and norm_mpn(None) is None and norm_mpn("---") is None
    assert norm_mpn("ABC-1") != norm_mpn("ABC-2")


def _mk(client, name, mpn):
    r = client.post("/api/parts", json={"name": name, "mpn": mpn})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_duplicate_mpns_are_reported_but_nothing_is_touched(client):
    a = _mk(client, "ZZ_DUP a", "ZZ-DUP-100")
    b = _mk(client, "ZZ_DUP b", "zz dup 100")          # same part, typed differently
    c = _mk(client, "ZZ_DUP c", "ZZ-DUP-200")          # different part
    try:
        # the New part form asks before creating
        hits = client.get("/api/parts/check-mpn", params={"mpn": "ZZDUP100"}).json()["matches"]
        assert {h["id"] for h in hits} == {a, b}
        assert client.get("/api/parts/check-mpn", params={"mpn": "ZZDUP100", "exclude": a}).json()["matches"][0]["id"] == b
        assert client.get("/api/parts/check-mpn", params={"mpn": "ZZDUP300"}).json()["matches"] == []
        assert client.get("/api/parts/check-mpn", params={"mpn": ""}).json()["matches"] == []

        # the detail view names the other part
        assert [x["id"] for x in client.get(f"/api/parts/{a}").json()["same_mpn"]] == [b]
        assert client.get(f"/api/parts/{c}").json()["same_mpn"] == []

        # the list flags it, and the filter finds it
        items = {i["id"]: i for i in client.get("/api/parts", params={"q": "ZZ_DUP"}).json()["items"]}
        assert items[a]["dup"] == 1 and items[b]["dup"] == 1 and items[c]["dup"] == 0
        only = client.get("/api/parts", params={"q": "ZZ_DUP", "duplicates": "true"}).json()["items"]
        assert {i["id"] for i in only} == {a, b}

        groups = client.get("/api/parts/duplicates").json()["groups"]
        assert any({p["id"] for p in g["parts"]} == {a, b} for g in groups)

        # reporting never removes anything
        assert client.get(f"/api/parts/{a}").status_code == 200 and client.get(f"/api/parts/{b}").status_code == 200
    finally:
        for pid in (a, b, c):
            client.delete(f"/api/parts/{pid}")
