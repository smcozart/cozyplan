"""`meta`: append-only list dedup, write-once fields, status vocabulary."""

from conftest import read


def test_meta_list_append_dedup(pt, new_plan):
    plan = new_plan("meta-list")
    assert pt.main(["meta", str(plan), "--field", "commits", "--value", "abc123"]) == 0
    assert pt.main(["meta", str(plan), "--field", "commits", "--value", "abc123"]) == 0
    meta = pt.parse_meta(read(plan))
    # same commit twice collapses to a single entry
    assert meta["commits"] == "abc123"


def test_meta_list_append_distinct(pt, new_plan):
    plan = new_plan("meta-list2")
    pt.main(["meta", str(plan), "--field", "commits", "--value", "aaa"])
    pt.main(["meta", str(plan), "--field", "commits", "--value", "bbb"])
    assert pt.split_list(pt.parse_meta(read(plan))["commits"]) == ["aaa", "bbb"]


def test_meta_write_once_refused_without_force(pt, new_plan, capsys):
    plan = new_plan("meta-wo")
    capsys.readouterr()
    for field in ("id", "created", "schema"):
        code = pt.main(["meta", str(plan), "--field", field, "--value", "tampered"])
        err = capsys.readouterr().err
        assert code != 0, f"{field} should be write-once"
        assert "write-once" in err


def test_meta_write_once_allowed_with_force(pt, new_plan):
    plan = new_plan("meta-force")
    assert pt.main(["meta", str(plan), "--field", "id", "--value", "renamed",
                    "--force"]) == 0
    assert pt.parse_meta(read(plan))["id"] == "renamed"


def test_meta_status_vocabulary_enforced(pt, new_plan, capsys):
    plan = new_plan("meta-status")
    capsys.readouterr()
    bad = pt.main(["meta", str(plan), "--field", "status", "--value", "bogus"])
    err = capsys.readouterr().err
    assert bad != 0
    assert "status must be one of" in err
    ok = pt.main(["meta", str(plan), "--field", "status", "--value", "active"])
    assert ok == 0
    assert pt.parse_meta(read(plan))["status"] == "active"


def test_meta_unknown_field_rejected(pt, new_plan, capsys):
    plan = new_plan("meta-unknown")
    capsys.readouterr()
    code = pt.main(["meta", str(plan), "--field", "nonsense", "--value", "x"])
    assert code != 0
    assert "unknown field" in capsys.readouterr().err
