"""`brief`: compact plain-text extract of one plan, and the --all one-liner index."""


def test_brief_shows_metadata_and_task_state(pt, new_plan, capsys):
    plan = new_plan("br", owner="engineer-api")
    pt.main(["status", str(plan), "--id", "1.1", "--state", "wip"])
    capsys.readouterr()
    assert pt.main(["brief", str(plan)]) == 0
    out = capsys.readouterr().out
    assert "id" in out and "br" in out
    assert "engineer-api" in out
    assert "[wip]" in out and "1.1" in out
    assert "Recent events" in out
    # plain text only — no HTML tags (draft placeholder {{}} tokens may remain)
    assert "<" not in out


def test_brief_decodes_html_entities(pt, new_plan, capsys):
    # `new` escapes the title (& -> &amp;) into the HTML; brief is a plain-text
    # extract, so it must decode entities back rather than print raw &amp;.
    plan = new_plan("bent", title="Ingest & Render <fast>")
    capsys.readouterr()
    assert pt.main(["brief", str(plan)]) == 0
    out = capsys.readouterr().out
    assert "Ingest & Render <fast>" in out
    assert "&amp;" not in out and "&lt;" not in out


def test_brief_open_failure_shows_reason(pt, new_plan, capsys):
    plan = new_plan("br2")
    pt.main(["status", str(plan), "--id", "1.1", "--state", "f", "--reason", "upstream gone"])
    capsys.readouterr()
    pt.main(["brief", str(plan)])
    out = capsys.readouterr().out
    assert "Open items" in out
    assert "[f]" in out and "upstream gone" in out


def test_brief_shows_refs(pt, new_plan, capsys):
    consumer = new_plan("bc")
    other = new_plan("bs")
    pt.main(["ref", "--this", str(consumer), "--other", str(other), "--type", "forward"])
    capsys.readouterr()
    pt.main(["brief", str(consumer)])
    out = capsys.readouterr().out
    assert "forward" in out and "bs.html" in out


def test_brief_all_one_line_per_plan(pt, new_plan, specs, capsys):
    new_plan("ba1", title="Alpha")
    new_plan("ba2", title="Beta")
    pt.main(["index", "--specs", str(specs), "--root", str(specs)])
    capsys.readouterr()
    assert pt.main(["brief", "--all", "--specs", str(specs)]) == 0
    out = capsys.readouterr().out
    assert "ba1.html" in out and "ba2.html" in out
    assert out.count("\n") >= 2
