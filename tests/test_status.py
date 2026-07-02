"""`status`: flip markers, [f] reason requirement, unknown id, event logging."""

from conftest import read, sidecar_events


def _marker(text, sid):
    import re
    m = re.search(r'data-status-for="' + re.escape(sid) + r'"[^>]*>(\[[^\]]*\])', text)
    return m.group(1) if m else None


def test_status_flips_idle_wip_x(pt, new_plan):
    plan = new_plan("st-flip")
    assert pt.main(["status", str(plan), "--id", "1.1", "--state", "idle"]) == 0
    assert _marker(read(plan), "1.1") == "[]"
    assert pt.main(["status", str(plan), "--id", "1.1", "--state", "wip"]) == 0
    assert _marker(read(plan), "1.1") == "[wip]"
    assert pt.main(["status", str(plan), "--id", "1.1", "--state", "x"]) == 0
    assert _marker(read(plan), "1.1") == "[x]"


def test_status_f_requires_reason(pt, new_plan, capsys):
    plan = new_plan("st-fail")
    capsys.readouterr()
    code = pt.main(["status", str(plan), "--id", "1.1", "--state", "f"])
    err = capsys.readouterr().err
    assert code != 0
    assert "--reason" in err
    # marker untouched
    assert _marker(read(plan), "1.1") == "[]"


def test_status_f_with_reason_succeeds_and_amends(pt, new_plan):
    plan = new_plan("st-fail-ok")
    code = pt.main(["status", str(plan), "--id", "1.1", "--state", "f",
                    "--reason", "upstream API removed"])
    assert code == 0
    text = read(plan)
    assert _marker(text, "1.1") == "[f]"
    # [f] records an amendment carrying the reason
    assert "upstream API removed" in text


def test_status_unknown_id_fails(pt, new_plan, capsys):
    plan = new_plan("st-unknown")
    capsys.readouterr()
    code = pt.main(["status", str(plan), "--id", "9.9", "--state", "wip"])
    err = capsys.readouterr().err
    assert code != 0
    assert "no status anchor" in err


def test_status_appends_event_each_time(pt, new_plan):
    plan = new_plan("st-events")
    pt.main(["status", str(plan), "--id", "1.1", "--state", "wip"])
    pt.main(["status", str(plan), "--id", "1.2", "--state", "x"])
    events = [e for e in sidecar_events(plan) if e["event"] == "status"]
    assert len(events) == 2
    assert events[0]["details"] == {"id": "1.1", "state": "wip", "reason": None}
    assert events[1]["details"]["id"] == "1.2"
