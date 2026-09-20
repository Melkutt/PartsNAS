import json
import zipfile
from datetime import datetime, timedelta

from app import autosnapshot as auto


def _cfg(**kw):
    return {**auto.DEFAULTS, **kw}


def test_off_by_default(client):
    body = client.get("/api/settings/autosnapshot").json()
    assert body["config"]["enabled"] is False and body["config"]["folder"] == "backups/auto"


def test_when_a_snapshot_is_due():
    at = lambda h, m=0: datetime(2026, 9, 20, h, m)   # noqa: E731
    on = _cfg(enabled=True, hour=3)
    assert not auto.is_due(_cfg(enabled=False), {}, at(4))          # switched off
    assert not auto.is_due(on, {}, at(2, 59))                       # before the hour
    assert auto.is_due(on, {}, at(3))                               # first time ever
    assert not auto.is_due(on, {"last_ok_at": at(3).isoformat()}, at(15))   # already made one today
    assert auto.is_due(on, {"last_ok_at": (at(3) - timedelta(days=1)).isoformat()}, at(3, 1))
    # the NAS was off at 03:00: catch up when it is back
    assert auto.is_due(on, {"last_ok_at": (at(3) - timedelta(days=1)).isoformat()}, at(17))
    # a failed attempt is not retried every minute
    failed = {"last_attempt_at": at(3).isoformat(), "last_error": "disk full"}
    assert not auto.is_due(on, failed, at(3, 10)) and auto.is_due(on, failed, at(3, 31))


def test_snapshots_are_written_to_the_chosen_folder_and_only_the_newest_are_kept(client, tmp_path):
    folder = tmp_path / "nas-backups"
    r = client.put("/api/settings/autosnapshot", json={"enabled": True, "folder": str(folder), "keep": 2, "hour": 3})
    assert r.status_code == 200, r.text
    names = [client.post("/api/settings/autosnapshot/run").json()["file"] for _ in range(3)]
    files = sorted(p.name for p in folder.glob("partsnas-auto-*.zip"))
    assert len(files) == 2 and names[0] not in files and names[-1] in files      # oldest pruned
    with zipfile.ZipFile(folder / names[-1]) as z:                               # a real, complete snapshot
        assert json.loads(z.read("snapshot.json"))["format"] == "partsnas-snapshot"
    assert not list(folder.glob("*.partial"))
    state = client.get("/api/settings/autosnapshot").json()
    assert state["state"]["last_file"] == names[-1] and state["state"]["last_error"] is None
    assert [f["name"] for f in state["files"]][0] == names[-1]
    client.put("/api/settings/autosnapshot", json={"enabled": False, "folder": "backups/auto", "keep": 7, "hour": 3})


def test_a_bad_folder_is_refused_when_saving(client, tmp_path):
    from app.core.config import get_settings

    inside_data = get_settings().data_dir / "images" / "snaps"
    r = client.put("/api/settings/autosnapshot", json={"enabled": True, "folder": str(inside_data), "keep": 3, "hour": 3})
    assert r.status_code == 400 and "backups" in r.json()["detail"]
    blocker = tmp_path / "a-file"
    blocker.write_text("x")
    r = client.put("/api/settings/autosnapshot", json={"enabled": True, "folder": str(blocker / "sub"), "keep": 3, "hour": 3})
    assert r.status_code == 400
    assert client.put("/api/settings/autosnapshot", json={"enabled": True, "folder": "x", "keep": 0, "hour": 3}).status_code == 422
    assert client.put("/api/settings/autosnapshot", json={"enabled": True, "folder": "x", "keep": 3, "hour": 24}).status_code == 422
