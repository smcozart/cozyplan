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


def test_meta_status_gate_refuses_leaving_draft_with_placeholders(pt, new_plan, capsys):
    plan = new_plan("meta-gate")
    capsys.readouterr()
    # a fresh scaffold is full of {{}} slots -> cannot go active
    code = pt.main(["meta", str(plan), "--field", "status", "--value", "active"])
    err = capsys.readouterr().err
    assert code != 0
    assert "placeholder slot" in err
    assert pt.parse_meta(read(plan))["status"] == "draft"  # unchanged


def test_meta_status_gate_allows_transition_into_draft(pt, filled_plan):
    # transitions INTO draft never gate (they're the authoring direction)
    plan = filled_plan("meta-todraft")
    assert pt.main(["meta", str(plan), "--field", "status", "--value", "active"]) == 0
    assert pt.main(["meta", str(plan), "--field", "status", "--value", "draft"]) == 0
    assert pt.parse_meta(read(plan))["status"] == "draft"


def test_meta_status_allowed_when_filled(pt, filled_plan):
    plan = filled_plan("meta-status-ok")
    assert pt.main(["meta", str(plan), "--field", "status", "--value", "active"]) == 0
    assert pt.parse_meta(read(plan))["status"] == "active"


# ── status=built gates on the status markers, not just on prose ───────────────

def _finish_every_marker(pt, plan):
    for sid, _ in pt.iter_status_markers(read(plan)):
        assert pt.main(["status", str(plan), "--id", sid, "--state", "x"]) == 0


def test_meta_built_refused_while_markers_are_open(pt, filled_plan, capsys):
    plan = filled_plan("meta-built-open")
    capsys.readouterr()
    code = pt.main(["meta", str(plan), "--field", "status", "--value", "built"])
    err = capsys.readouterr().err
    assert code != 0
    assert "not [x] or [f]" in err
    assert "phase-1" in err and "1.1" in err  # the offending ids are named
    assert pt.parse_meta(read(plan))["status"] == "draft"  # unchanged


def test_meta_built_allowed_once_every_marker_is_terminal(pt, filled_plan):
    plan = filled_plan("meta-built-ok")
    _finish_every_marker(pt, plan)
    assert pt.main(["meta", str(plan), "--field", "status", "--value", "built"]) == 0
    assert pt.parse_meta(read(plan))["status"] == "built"


def test_meta_built_counts_failed_markers_as_terminal(pt, filled_plan):
    plan = filled_plan("meta-built-failed")
    for sid, _ in pt.iter_status_markers(read(plan)):
        if sid == "1.2":
            pt.main(["status", str(plan), "--id", sid, "--state", "f",
                     "--reason", "blocked upstream"])
        else:
            pt.main(["status", str(plan), "--id", sid, "--state", "x"])
    assert pt.main(["meta", str(plan), "--field", "status", "--value", "built"]) == 0


def test_meta_built_force_overrides_the_gate(pt, filled_plan):
    plan = filled_plan("meta-built-force")
    assert pt.main(["meta", str(plan), "--field", "status", "--value", "built",
                    "--force"]) == 0
    assert pt.parse_meta(read(plan))["status"] == "built"


def test_meta_marker_gate_applies_only_to_built(pt, filled_plan):
    # active/archived make no completion claim, so they stay ungated
    plan = filled_plan("meta-built-only")
    assert pt.main(["meta", str(plan), "--field", "status", "--value", "active"]) == 0
    assert pt.main(["meta", str(plan), "--field", "status", "--value", "archived"]) == 0


def test_meta_built_gate_covers_ids_added_by_addphase(pt, filled_plan, capsys):
    import re
    plan = filled_plan("meta-built-added")
    _finish_every_marker(pt, plan)
    pt.main(["addphase", str(plan), "--tasks", "1"])
    # addphase lays down fresh {{}} content slots; fill them so the *marker* gate,
    # not the placeholder gate, is what refuses the transition
    stripped = re.sub(r"\{\{.*?\}\}", "x", read(plan), flags=re.S)
    with open(plan, "w", encoding="utf-8", newline="") as f:
        f.write(stripped)
    capsys.readouterr()
    code = pt.main(["meta", str(plan), "--field", "status", "--value", "built"])
    err = capsys.readouterr().err
    assert code != 0
    assert "not [x] or [f]" in err
    assert "phase-2" in err


# ── `modified` stays bounded (last N stamps + an exact elision count) ─────────

def test_compact_modified_keeps_the_tail_and_an_exact_count(pt):
    assert pt.compact_modified(["a", "b"], keep=5) == ["a", "b"]
    assert pt.compact_modified(list("abcdefg"), keep=3) == ["e", "f", "g", "(+4 earlier)"]
    # a marker left by an earlier compaction is absorbed, never double-counted
    assert pt.compact_modified(["(+4 earlier)", "e", "f", "g", "h"], keep=3) == \
        ["f", "g", "h", "(+5 earlier)"]


def test_modified_compacts_to_five_stamps_plus_a_count(pt, new_plan):
    plan = new_plan("meta-mod")
    for i in range(12):
        assert pt.main(["meta", str(plan), "--field", "modified",
                        "--value", f"2026-01-{i + 1:02d}T00:00:00-05:00"]) == 0
    entries = pt.split_list(pt.parse_meta(read(plan))["modified"])
    assert len(entries) == pt.MODIFIED_KEEP + 1
    assert entries[:5] == [f"2026-01-{d:02d}T00:00:00-05:00" for d in range(8, 13)]
    # 1 scaffold stamp + 12 appends - 5 kept
    assert entries[-1] == "(+8 earlier)"


def test_modified_count_stays_exact_across_repeated_compaction(pt, new_plan):
    plan = new_plan("meta-mod-repeat")
    for i in range(20):
        pt.main(["meta", str(plan), "--field", "modified",
                 "--value", f"2026-02-{i + 1:02d}T00:00:00-05:00"])
    entries = pt.split_list(pt.parse_meta(read(plan))["modified"])
    assert len(entries) == pt.MODIFIED_KEEP + 1
    assert entries[-1] == "(+16 earlier)"  # 1 + 20 - 5


def test_modified_stamp_stays_idempotent_within_a_second(pt, new_plan):
    plan = new_plan("meta-mod-idem")
    text = read(plan)
    iso = "2026-03-01T00:00:00-05:00"
    once = pt.stamp_modified(text, iso)
    twice = pt.stamp_modified(once, iso)
    assert twice == once
    assert pt.split_list(pt.parse_meta(twice)["modified"]).count(iso) == 1


def test_modified_stays_bounded_under_automatic_stamping(pt, new_plan):
    plan = new_plan("meta-mod-auto")
    for i in range(30):
        pt.main(["meta", str(plan), "--field", "commits", "--value", f"sha{i}"])
    entries = pt.split_list(pt.parse_meta(read(plan))["modified"])
    assert len(entries) <= pt.MODIFIED_KEEP + 1


def test_meta_unknown_field_rejected(pt, new_plan, capsys):
    plan = new_plan("meta-unknown")
    capsys.readouterr()
    code = pt.main(["meta", str(plan), "--field", "nonsense", "--value", "x"])
    assert code != 0
    assert "unknown field" in capsys.readouterr().err
