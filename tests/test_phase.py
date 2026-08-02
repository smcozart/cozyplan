"""`phase`: the scoped half of two-tier recall — one phase block, in full, as text."""

from conftest import read


def test_phase_prints_tasks_actions_and_testing_strategy(pt, new_plan, capsys):
    plan = new_plan("ph-one", title="Phase Reader")
    pt.main(["status", str(plan), "--id", "1.1", "--state", "wip"])
    capsys.readouterr()
    assert pt.main(["phase", str(plan), "--id", "phase-1"]) == 0
    out = capsys.readouterr().out
    assert "Phase Reader" in out
    assert "phase-1" in out
    assert "[wip]" in out and "1.1" in out
    assert "1.2" in out
    assert "Testing Strategy" in out
    # plain text only (draft {{}} slots may remain, but no markup)
    assert "<" not in out


def test_phase_accepts_a_bare_number(pt, new_plan, capsys):
    plan = new_plan("ph-bare")
    capsys.readouterr()
    assert pt.main(["phase", str(plan), "--id", "1"]) == 0
    assert "phase-1" in capsys.readouterr().out


def test_phase_is_scoped_to_one_phase(pt, new_plan, capsys):
    plan = new_plan("ph-scope")
    pt.main(["addphase", str(plan), "--tasks", "1", "--title", "Second Phase"])
    capsys.readouterr()
    pt.main(["phase", str(plan), "--id", "1"])
    first = capsys.readouterr().out
    assert "phase-2" not in first and "Second Phase" not in first

    pt.main(["phase", str(plan), "--id", "2"])
    second = capsys.readouterr().out
    assert "Second Phase" in second and "phase-1" not in second
    # the trailing phase stops at the phases section, not at end-of-document
    assert "g.1" not in second


def test_phase_unknown_phase_fails_with_the_known_ones(pt, new_plan, capsys):
    plan = new_plan("ph-miss")
    capsys.readouterr()
    code = pt.main(["phase", str(plan), "--id", "phase-7"])
    err = capsys.readouterr().err
    assert code != 0
    assert "no phase" in err
    assert "phases present: 1" in err


def test_phase_rejects_a_task_id(pt, new_plan, capsys):
    plan = new_plan("ph-bad")
    capsys.readouterr()
    code = pt.main(["phase", str(plan), "--id", "1.1"])
    assert code != 0
    assert "phase-<n>" in capsys.readouterr().err


def test_phase_reflects_marker_state(pt, new_plan, capsys):
    plan = new_plan("ph-state")
    pt.main(["status", str(plan), "--id", "phase-1", "--state", "x"])
    pt.main(["status", str(plan), "--id", "1.2", "--state", "f", "--reason", "blocked"])
    capsys.readouterr()
    pt.main(["phase", str(plan), "--id", "1"])
    out = capsys.readouterr().out
    assert "[x]" in out and "[f]" in out


def test_phase_does_not_mutate_the_plan(pt, new_plan):
    plan = new_plan("ph-ro")
    before = read(plan)
    pt.main(["phase", str(plan), "--id", "1"])
    assert read(plan) == before


def test_phase_missing_plan_fails(pt, specs, capsys):
    code = pt.main(["phase", str(specs / "ghost.html"), "--id", "1"])
    assert code != 0
    assert "plan not found" in capsys.readouterr().err
