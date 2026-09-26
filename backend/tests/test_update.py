"""Version comparison, the update check, and the warning when a snapshot comes from a newer PartsNAS."""
import io
import json
import zipfile

from app import __version__
from app.versioning import compare, parse_version


def test_versions_are_compared_by_number_not_by_text():
    assert parse_version("v0.8.0") == (0, 8, 0) and parse_version("0.10") == (0, 10)
    assert parse_version("nonsense") is None and parse_version(None) is None
    assert compare("0.10.0", "0.9.0") == 1 and compare("0.8.0", "0.8.1") == -1 and compare("1.0", "1.0.0") == 0
    assert compare("x", "0.8.0") is None


def test_the_update_check_says_newer_same_other_build_ahead_or_error(client, monkeypatch):
    import app.api.update as upd

    cur = upd.evaluate({"version": __version__})["current"]

    def check(latest=None, error=None):
        def fake(url, token=""):
            if error:
                raise ValueError(error)
            return latest
        monkeypatch.setattr(upd, "_fetch", fake)
        return client.get("/api/update/check?refresh=1").json()

    assert check({"version": "99.0.0", "notes": "n"})["status"] == "newer"
    assert check({"version": __version__, "build": cur["build"]})["status"] == "same"
    assert check({"version": __version__, "build": "0000000"})["status"] == "other_build"
    assert check({"version": "0.0.1"})["status"] == "ahead"
    err = check(error="the repository is private")
    assert err["status"] == "error" and "private" in err["message"] and err["current"]["version"] == __version__


def test_the_address_of_the_published_file_can_be_changed(client):
    assert client.get("/api/update/settings").json()["url"] == ""
    assert client.put("/api/update/settings", json={"url": " http://example.invalid/version.json "}).json()["url"] == "http://example.invalid/version.json"
    try:
        assert client.get("/api/update/check?refresh=1").json()["url"] == "http://example.invalid/version.json"
    finally:
        client.put("/api/update/settings", json={"url": ""})


def test_a_snapshot_from_a_newer_partsnas_is_refused_until_you_say_so(client):
    raw = client.get("/api/export/snapshot.zip").content
    src = zipfile.ZipFile(io.BytesIO(raw))
    manifest = json.loads(src.read("snapshot.json"))
    manifest["app_version"] = "99.0.0"
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for name in src.namelist():
            z.writestr(name, json.dumps(manifest) if name == "snapshot.json" else src.read(name))
    r = client.post("/api/import/snapshot", files={"file": ("s.zip", out.getvalue(), "application/zip")}, data={"confirm": "REPLACE"})
    assert r.status_code == 409
    d = r.json()["detail"]
    assert d["code"] == "newer_snapshot" and d["snapshot_version"] == "99.0.0" and d["running_version"] == __version__
    assert client.get("/api/health").status_code == 200        # nothing was touched


def test_a_github_token_is_only_sent_to_github(client):
    from app.api.update import _headers
    assert _headers("https://raw.githubusercontent.com/o/r/master/version.json", "T")["Authorization"] == "Bearer T"
    assert "Authorization" not in _headers("http://192.168.1.5/version.json", "T")           # another address: never
    assert "Authorization" not in _headers("https://raw.githubusercontent.com/o/r/master/version.json", "")
    assert client.put("/api/update/settings", json={"url": "", "token": "abc"}).json()["has_token"] is True
    assert client.get("/api/update/settings").json()["has_token"] is True
    assert client.put("/api/update/settings", json={"url": ""}).json()["has_token"] is True       # left alone when not sent
    assert client.put("/api/update/settings", json={"url": "", "token": ""}).json()["has_token"] is False
