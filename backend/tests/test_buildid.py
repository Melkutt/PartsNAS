from pathlib import Path

from app.buildid import fingerprint


def _tree(root: Path, files: dict[str, bytes]):
    for name, data in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)


def test_build_id_follows_the_code(tmp_path):
    _tree(tmp_path / "a", {"x.py": b"print(1)\n"})
    _tree(tmp_path / "f", {"index.html": b"<html>"})
    _tree(tmp_path / "s", {"c.json": b"{}"})
    first = fingerprint(tmp_path / "a", tmp_path / "f", tmp_path / "s")
    assert first == fingerprint(tmp_path / "a", tmp_path / "f", tmp_path / "s")  # stable
    (tmp_path / "f" / "index.html").write_bytes(b"<html>changed")
    assert fingerprint(tmp_path / "a", tmp_path / "f", tmp_path / "s") != first


def test_line_endings_and_caches_do_not_change_it(tmp_path):
    _tree(tmp_path / "a", {"x.py": b"a\nb\n"})
    _tree(tmp_path / "f", {"i.js": b"1\n"})
    _tree(tmp_path / "s", {})
    base = fingerprint(tmp_path / "a", tmp_path / "f", tmp_path / "s")
    (tmp_path / "a" / "x.py").write_bytes(b"a\r\nb\r\n")       # same code, Windows checkout
    _tree(tmp_path / "a", {"__pycache__/x.cpython-313.pyc": b"junk"})
    assert fingerprint(tmp_path / "a", tmp_path / "f", tmp_path / "s") == base


def test_health_reports_the_build(client):
    h = client.get("/api/health").json()
    assert h["status"] == "ok" and len(h["build"]) == 7
