"""`next`: first non-terminal status id in document order, or the literal 'done'."""

from conftest import read


def test_next_is_the_first_marker_on_a_fresh_plan(pt, new_plan, capsys):
    plan = new_plan("nx-fresh")
    capsys.readouterr()
    assert pt.main(["next", str(plan)]) == 0
    assert capsys.readouterr().out.strip() == "phase-1"


def test_next_skips_completed_markers(pt, new_plan, capsys):
    plan = new_plan("nx-skip")
    for sid in ("phase-1", "1.1"):
        pt.main(["status", str(plan), "--id", sid, "--state", "x"])
    capsys.readouterr()
    pt.main(["next", str(plan)])
    assert capsys.readouterr().out.strip() == "1.2"


def test_next_treats_failed_as_terminal(pt, new_plan, capsys):
    plan = new_plan("nx-failed")
    pt.main(["status", str(plan), "--id", "phase-1", "--state", "x"])
    pt.main(["status", str(plan), "--id", "1.1", "--state", "f", "--reason", "upstream gone"])
    capsys.readouterr()
    pt.main(["next", str(plan)])
    assert capsys.readouterr().out.strip() == "1.2"


def test_next_treats_wip_as_still_open(pt, new_plan, capsys):
    plan = new_plan("nx-wip")
    pt.main(["status", str(plan), "--id", "phase-1", "--state", "wip"])
    capsys.readouterr()
    pt.main(["next", str(plan)])
    assert capsys.readouterr().out.strip() == "phase-1"


def test_next_reports_done_when_everything_is_terminal(pt, new_plan, capsys):
    plan = new_plan("nx-done")
    for sid, _ in pt.iter_status_markers(read(plan)):
        pt.main(["status", str(plan), "--id", sid, "--state", "x"])
    capsys.readouterr()
    assert pt.main(["next", str(plan)]) == 0
    assert capsys.readouterr().out.strip() == "done"


def test_next_covers_ids_added_by_addphase(pt, new_plan, capsys):
    plan = new_plan("nx-added")
    for sid, _ in pt.iter_status_markers(read(plan)):
        pt.main(["status", str(plan), "--id", sid, "--state", "x"])
    pt.main(["addphase", str(plan), "--tasks", "1"])
    capsys.readouterr()
    pt.main(["next", str(plan)])
    assert capsys.readouterr().out.strip() == "phase-2"


def test_next_missing_plan_fails(pt, specs, capsys):
    code = pt.main(["next", str(specs / "ghost.html")])
    assert code != 0
    assert "plan not found" in capsys.readouterr().err
