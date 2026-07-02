"""`validate`: token severity by status, and schema-ceiling refusal of writes."""

from conftest import read


def test_tokens_are_warning_while_draft(pt, new_plan, capsys):
    plan = new_plan("val-draft")
    capsys.readouterr()
    code = pt.main(["validate", str(plan)])
    out = capsys.readouterr().out
    assert code == 0
    assert "warn:" in out and "OK" in out


def test_tokens_fail_once_not_draft(pt, new_plan, capsys):
    plan = new_plan("val-active")
    # move off draft while free-form {{}} tokens still remain
    assert pt.main(["meta", str(plan), "--field", "status", "--value", "active"]) == 0
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
