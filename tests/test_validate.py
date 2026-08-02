"""`validate`: token severity by status, structural id checks, schema-ceiling refusal."""

import re

from conftest import read


def _write(path, text):
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def test_tokens_are_warning_while_draft(pt, new_plan, capsys):
    plan = new_plan("val-draft")
    capsys.readouterr()
    code = pt.main(["validate", str(plan)])
    out = capsys.readouterr().out
    assert code == 0
    assert "warn:" in out and "OK" in out


def test_tokens_fail_once_not_draft(pt, new_plan, capsys):
    plan = new_plan("val-active")
    # Force status=active while free-form {{}} tokens remain by editing the HTML
    # directly — the meta gate now refuses this transition (see test_meta), so we
    # bypass it to exercise validate's token-severity-by-status branch.
    text = read(plan).replace('<dd data-meta="status">draft</dd>',
                              '<dd data-meta="status">active</dd>')
    with open(plan, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    capsys.readouterr()
    code = pt.main(["validate", str(plan)])
    out = capsys.readouterr().out
    assert code != 0
    assert "FAIL" in out
    assert "placeholder token" in out


def test_schema_newer_than_supported_refuses_writes(pt, new_plan, capsys):
    plan = new_plan("val-schema")
    # Stamp the artifact one schema version beyond what this tool understands.
    text = read(plan).replace('<dd data-meta="schema">1</dd>',
                              '<dd data-meta="schema">2</dd>')
    with open(plan, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    capsys.readouterr()
    code = pt.main(["status", str(plan), "--id", "1.1", "--state", "wip"])
    err = capsys.readouterr().err
    assert code != 0
    assert "schema 2" in err
    # marker must be untouched by the refused write
    assert '[]</code>' in read(plan)


def test_validate_missing_plan_fails(pt, specs, capsys):
    code = pt.main(["validate", str(specs / "ghost.html")])
    assert code != 0
    assert "plan not found" in capsys.readouterr().err


# ── structural id checks (the failure modes of hand-duplicated phase blocks) ──

def test_validate_flags_duplicate_status_ids(pt, new_plan, capsys):
    plan = new_plan("val-dupe-id")
    text = read(plan)
    m = re.search(r'<li data-task="1\.1".*?</li>', text, re.S)
    _write(plan, text[:m.end()] + m.group(0) + text[m.end():])
    capsys.readouterr()
    code = pt.main(["validate", str(plan)])
    out = capsys.readouterr().out
    assert code != 0, "a duplicated id is an error: it makes `status --id` ambiguous"
    assert "duplicate data-status-for" in out and "1.1" in out


def test_validate_flags_task_and_status_id_mismatch(pt, new_plan, capsys):
    plan = new_plan("val-mismatch")
    _write(plan, read(plan).replace('<li data-task="1.2">', '<li data-task="1.9">', 1))
    capsys.readouterr()
    code = pt.main(["validate", str(plan)])
    out = capsys.readouterr().out
    assert code != 0
    assert 'data-task="1.9"' in out and 'data-status-for="1.2"' in out


def test_validate_flags_duplicate_phase_numbers(pt, new_plan, capsys):
    plan = new_plan("val-dupe-phase")
    pt.main(["addphase", str(plan), "--tasks", "1"])
    _write(plan, read(plan).replace('data-phase="2"', 'data-phase="1"'))
    capsys.readouterr()
    code = pt.main(["validate", str(plan)])
    out = capsys.readouterr().out
    assert code != 0
    assert "duplicate data-phase" in out


def test_validate_warns_but_passes_on_a_phase_numbering_gap(pt, new_plan, capsys):
    plan = new_plan("val-gap")
    _write(plan, read(plan).replace('data-phase="1"', 'data-phase="2"'))
    capsys.readouterr()
    code = pt.main(["validate", str(plan)])
    out = capsys.readouterr().out
    assert code == 0, "a gap breaks nothing addressable — warning, not error"
    assert "not a gapless" in out


def test_validate_clean_plan_has_no_structural_findings(pt, new_plan, capsys):
    plan = new_plan("val-clean")
    pt.main(["addphase", str(plan), "--tasks", "3"])
    capsys.readouterr()
    assert pt.main(["validate", str(plan)]) == 0
    out = capsys.readouterr().out
    assert "duplicate" not in out
    assert "not a gapless" not in out
    assert "must match" not in out


# ── open-marker notice (the early warning for the status=built gate) ──────────

def test_validate_warns_on_open_markers_once_out_of_draft(pt, filled_plan, capsys):
    plan = filled_plan("val-open")
    pt.main(["meta", str(plan), "--field", "status", "--value", "active"])
    capsys.readouterr()
    code = pt.main(["validate", str(plan)])
    out = capsys.readouterr().out
    assert code == 0, "incomplete markers are a warning in validate, not a failure"
    assert "status marker(s) still open" in out
    assert "status=built is refused" in out


def test_validate_open_marker_notice_is_silent_while_draft(pt, new_plan, capsys):
    plan = new_plan("val-open-draft")
    capsys.readouterr()
    assert pt.main(["validate", str(plan)]) == 0
    assert "still open" not in capsys.readouterr().out


def test_validate_open_marker_notice_clears_when_all_terminal(pt, filled_plan, capsys):
    plan = filled_plan("val-open-done")
    pt.main(["meta", str(plan), "--field", "status", "--value", "active"])
    for sid, _ in pt.iter_status_markers(read(plan)):
        pt.main(["status", str(plan), "--id", sid, "--state", "x"])
    capsys.readouterr()
    assert pt.main(["validate", str(plan)]) == 0
    assert "still open" not in capsys.readouterr().out
