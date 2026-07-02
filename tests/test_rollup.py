"""`rollup`: attention/accomplishments/stale synthesis and determinism."""

import json

from conftest import read


def _plan_files(names, out):
    return {n: p for n, p in zip(names, out)}


def test_rollup_synthesizes_status(pt, new_plan, specs):
    a = new_plan("roll-a", title="A", owner="engineer-api")
    b = new_plan("roll-b", title="B", owner="ux")
    new_plan("roll-c", title="C", owner="ux")  # no reports -> stale

    pt.main(["report", str(a), "--role", "engineer-api", "--status", "done",
             "--summary", "finished A"])
    pt.main(["report", str(b), "--role", "ux", "--status", "blocked",
             "--summary", "waiting on design"])
    pt.main(["index", "--specs", str(specs), "--root", str(specs)])

    assert pt.main(["rollup", "--specs", str(specs)]) == 0
    out = json.loads(read(specs / "_status.json"))

    attention_plans = {a["plan"]: a for a in out["attention"]}
    assert "roll-b.html" in attention_plans
    assert attention_plans["roll-b.html"]["kind"] == "blocked"

    acc_plans = {r["plan"] for r in out["accomplishments"]}
    assert "roll-a.html" in acc_plans

    stale_plans = {s["plan"] for s in out["stale"]}
    assert "roll-c.html" in stale_plans


def test_rollup_is_byte_identical_across_runs(pt, new_plan, specs):
    a = new_plan("roll-d", title="D", owner="engineer-api")
    pt.main(["report", str(a), "--role", "engineer-api", "--status", "done",
             "--summary", "done D"])
    pt.main(["index", "--specs", str(specs), "--root", str(specs)])

    pt.main(["rollup", "--specs", str(specs)])
    j1 = (specs / "_status.json").read_bytes()
    h1 = (specs / "_status.html").read_bytes()
    pt.main(["rollup", "--specs", str(specs)])
    assert (specs / "_status.json").read_bytes() == j1
    assert (specs / "_status.html").read_bytes() == h1


def test_rollup_emits_artifacts(pt, new_plan, specs):
    new_plan("roll-e", title="E")
    assert pt.main(["rollup", "--specs", str(specs)]) == 0
    assert (specs / "_status.json").exists()
    assert (specs / "_status.html").exists()
