"""Moving a category / location up or down among its siblings."""


def _make(client, base, names, parent=None):
    ids = []
    for n in names:
        r = client.post(base, json={"name": n, "parent_id": parent})
        assert r.status_code in (200, 201), r.text
        ids.append(r.json()["id"])
    return ids


def _order(client, base, parent_id, prefix):
    def walk(nodes, pid):
        for n in nodes:
            if n["id"] == pid:
                return n["children"]
            got = walk(n["children"], pid)
            if got is not None:
                return got
    kids = walk(client.get(base).json(), parent_id)
    return [k["name"] for k in kids if k["name"].startswith(prefix)]


def test_a_category_moves_up_and_down_among_its_siblings(client):
    (top,) = _make(client, "/api/categories", ["ZZ_ORD top"])
    m3, m4, other, m5 = _make(client, "/api/categories", ["ZZ_ORD M3", "ZZ_ORD M4", "ZZ_ORD Other", "ZZ_ORD M5"], top)
    try:
        # (sort_order, name) decides the order shown; renumbering makes a step always change something
        assert _order(client, "/api/categories", top, "ZZ_ORD") == ["ZZ_ORD M3", "ZZ_ORD M4", "ZZ_ORD Other", "ZZ_ORD M5"]
        assert client.post(f"/api/categories/{m5}/move", json={"direction": "up"}).json() == {"position": 2}
        assert _order(client, "/api/categories", top, "ZZ_ORD") == ["ZZ_ORD M3", "ZZ_ORD M4", "ZZ_ORD M5", "ZZ_ORD Other"]
        assert client.post(f"/api/categories/{m3}/move", json={"direction": "down"}).json() == {"position": 1}
        assert _order(client, "/api/categories", top, "ZZ_ORD") == ["ZZ_ORD M4", "ZZ_ORD M3", "ZZ_ORD M5", "ZZ_ORD Other"]
        # at an end: nothing to do, no error
        assert client.post(f"/api/categories/{m4}/move", json={"direction": "up"}).json() == {"position": 0}
        assert client.post(f"/api/categories/{other}/move", json={"direction": "down"}).json() == {"position": 3}
        assert client.post(f"/api/categories/{m4}/move", json={"direction": "sideways"}).status_code == 400
        assert client.post("/api/categories/999999/move", json={"direction": "up"}).status_code == 404
    finally:
        client.delete(f"/api/categories/{top}")


def test_top_level_trees_and_locations_move_too(client):
    a, b = _make(client, "/api/locations", ["ZZ_ORD box A", "ZZ_ORD box B"])
    try:
        def names():
            return [n["name"] for n in client.get("/api/locations").json() if n["name"].startswith("ZZ_ORD")]
        assert names() == ["ZZ_ORD box A", "ZZ_ORD box B"]
        client.post(f"/api/locations/{b}/move", json={"direction": "up"})
        assert names() == ["ZZ_ORD box B", "ZZ_ORD box A"]
    finally:
        for i in (a, b):
            client.delete(f"/api/locations/{i}")
