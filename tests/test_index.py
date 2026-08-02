"""`index`: deterministic output, dangling-ref flagging, doc-drift scan."""

import json

from conftest import read


def _index(pt, specs, root=None):
    argv = ["index", "--specs", str(specs), "--root", str(root or specs)]
    return pt.main(argv)


def test_index_emits_artifacts(pt, new_plan, specs):
    new_plan("idx-a", title="Alpha")
    assert _index(pt, specs) == 0
    assert (specs / "_index.json").exists()
    assert (specs / "_index.html").exists()


def test_index_is_byte_identical_across_runs(pt, new_plan, specs):
    new_plan("idx-b", title="Beta")
    new_plan("idx-c", title="Gamma")
    _index(pt, specs)
    j1 = (specs / "_index.json").read_bytes()
    h1 = (specs / "_index.html").read_bytes()
    _index(pt, specs)
    assert (specs / "_index.json").read_bytes() == j1
    assert (specs / "_index.html").read_bytes() == h1


def test_index_flags_dangling_backref(pt, new_plan, specs):
    plan = new_plan("idx-dangle", title="Dangler")
    # point a back-ref at a file that does not exist in specs/
    pt.main(["meta", str(plan), "--field", "back-refs", "--value", "ghost.html"])
    _index(pt, specs)
    data = json.loads(read(specs / "_index.json"))
    assert ["idx-dangle.html", "back-refs", "ghost.html"] in [list(d) for d in data["dangling"]]


def test_index_reads_past_the_modified_elision_marker(pt, new_plan, specs):
    # `modified` is compacted to a tail plus a `(+N earlier)` marker; the index
    # still has to report a real timestamp, not the marker.
    plan = new_plan("idx-mod", title="Compacted")
    for i in range(9):
        pt.main(["meta", str(plan), "--field", "modified",
                 "--value", f"2026-04-{i + 1:02d}T00:00:00-05:00"])
    _index(pt, specs)
    data = json.loads(read(specs / "_index.json"))
    entry = next(p for p in data["plans"] if p["file"] == "idx-mod.html")
    assert entry["modified"] == "2026-04-09T00:00:00-05:00"
    assert data["as_of"] == "2026-04-09T00:00:00-05:00"


def test_scan_drift_catches_planted_token(pt, tmp_path):
    root = tmp_path / "proj"
    (root / "docs").mkdir(parents=True)
    planted = root / "docs" / "notes.md"
    planted.write_text("intro\nkey is OPENAI_API_KEY here\n", encoding="utf-8")
    hits = pt.scan_drift(root)
    assert any(h[2] == "OPENAI_API_KEY" and h[0] == str(planted) for h in hits)


def test_scan_drift_skips_scripts_dir(pt, tmp_path):
    root = tmp_path / "proj2"
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "tool.md").write_text("uses gpt-image internally\n", encoding="utf-8")
    assert pt.scan_drift(root) == []
