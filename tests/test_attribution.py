"""Attribution consistency: a --role that disagrees with PLANF3_ROLE is refused."""


def test_role_matching_env_is_allowed(pt, new_plan, monkeypatch):
    plan = new_plan("attr")
    monkeypatch.setenv("PLANF3_ROLE", "engineer-api")
    assert pt.main(["report", str(plan), "--role", "engineer-api",
                    "--status", "done", "--summary", "x"]) == 0


def test_role_mismatch_is_refused(pt, new_plan, monkeypatch, capsys):
    plan = new_plan("attr2")
    monkeypatch.setenv("PLANF3_ROLE", "engineer-api")
    capsys.readouterr()
    code = pt.main(["report", str(plan), "--role", "ux",
                    "--status", "done", "--summary", "x"])
    err = capsys.readouterr().err
    assert code != 0
    assert "disagrees" in err and "engineer-api" in err and "ux" in err


def test_force_role_overrides_mismatch(pt, new_plan, monkeypatch):
    plan = new_plan("attr3")
    monkeypatch.setenv("PLANF3_ROLE", "engineer-api")
    assert pt.main(["report", str(plan), "--role", "ux", "--status", "done",
                    "--summary", "x", "--force-role"]) == 0


def test_no_env_role_means_no_conflict(pt, new_plan, monkeypatch):
    plan = new_plan("attr4")
    monkeypatch.delenv("PLANF3_ROLE", raising=False)
    assert pt.main(["status", str(plan), "--id", "1.1", "--state", "wip",
                    "--role", "anything"]) == 0


def test_rollup_role_is_a_filter_not_attribution(pt, new_plan, specs, monkeypatch):
    # rollup --role is a component filter; it must not trip the attribution guard.
    new_plan("rf", owner="engineer-api")
    pt.main(["index", "--specs", str(specs), "--root", str(specs)])
    monkeypatch.setenv("PLANF3_ROLE", "architect")
    assert pt.main(["rollup", "--specs", str(specs), "--role", "engineer-api"]) == 0
