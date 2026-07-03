"""Seam contracts: kind, typed provides/consumes refs, ack loop, and the rollup
sections that surface change-request lifecycle, pending acceptance, drift."""

import json

from conftest import read


def _index_rollup(pt, specs):
    pt.main(["index", "--specs", str(specs), "--root", str(specs)])
    pt.main(["rollup", "--specs", str(specs)])
    return json.loads(read(specs / "_status.json"))


def _attention(out):
    return {(a["plan"], a["kind"]) for a in out["attention"]}


def test_new_contract_kind(pt, specs):
    pt.main(["new", "seam", "--title", "Seam", "--kind", "contract", "--specs", str(specs)])
    meta = pt.parse_meta(read(specs / "seam.html"))
    assert meta["kind"] == "contract"


def test_default_kind_is_plan(pt, new_plan):
    assert pt.parse_meta(read(new_plan("plainplan")))["kind"] == "plan"


def test_provides_consumes_bidirectional(pt, new_plan):
    consumer = new_plan("web-dash", owner="engineer-web")
    seam = new_plan("api-contract", owner="engineer-api")
    assert pt.main(["ref", "--this", str(consumer), "--other", str(seam),
                    "--type", "consumes"]) == 0
    assert "api-contract.html" in pt.split_list(pt.parse_meta(read(consumer))["consumes"])
    assert "web-dash.html" in pt.split_list(pt.parse_meta(read(seam))["provides"])


def test_provides_direction_is_symmetric(pt, new_plan):
    # `--type provides` from the seam side yields the same wiring.
    seam = new_plan("seam-p")
    consumer = new_plan("consumer-p")
    pt.main(["ref", "--this", str(seam), "--other", str(consumer), "--type", "provides"])
    assert "consumer-p.html" in pt.split_list(pt.parse_meta(read(seam))["provides"])
    assert "seam-p.html" in pt.split_list(pt.parse_meta(read(consumer))["consumes"])


def test_unacknowledged_seam_flagged_then_cleared(pt, new_plan, specs):
    seam = new_plan("seam-x")
    consumer = new_plan("consumer-y", owner="ux")
    pt.main(["meta", str(seam), "--field", "kind", "--value", "contract"])
    pt.main(["ref", "--this", str(consumer), "--other", str(seam), "--type", "consumes"])

    out = _index_rollup(pt, specs)
    assert ("consumer-y.html", "unacked-seam") in _attention(out)

    # consumer acknowledges the current seam state -> flag clears
    assert pt.main(["ack", str(consumer), "--seam", str(seam)]) == 0
    out2 = _index_rollup(pt, specs)
    assert ("consumer-y.html", "unacked-seam") not in _attention(out2)

    # seam is modified after the ack (explicit later timestamp, to avoid a
    # same-second race in the test) -> the flag returns
    pt.main(["meta", str(seam), "--field", "modified", "--value", "2099-01-01T00:00:00-05:00"])
    out3 = _index_rollup(pt, specs)
    assert ("consumer-y.html", "unacked-seam") in _attention(out3)


def test_change_request_lifecycle(pt, new_plan, specs):
    plan = new_plan("cr-plan", owner="engineer-api")
    pt.main(["report", str(plan), "--role", "ux", "--status", "request",
             "--summary", "please expose field Z"])
    out = _index_rollup(pt, specs)
    assert ("cr-plan.html", "open-request") in _attention(out)

    pt.main(["report", str(plan), "--role", "engineer-api", "--status", "request-closed",
             "--summary", "exposed"])
    out2 = _index_rollup(pt, specs)
    assert ("cr-plan.html", "open-request") not in _attention(out2)


def test_pending_acceptance_listed(pt, new_plan, specs):
    plan = new_plan("pa")
    pt.main(["meta", str(plan), "--field", "status", "--value", "built"])
    out = _index_rollup(pt, specs)
    assert "pa.html" in out["pending"]


def test_pending_omitted_when_acceptance_auto(pt, new_plan, specs):
    plan = new_plan("pa2")
    pt.main(["meta", str(plan), "--field", "status", "--value", "built"])
    roles = specs.parent / "roles"
    roles.mkdir()
    (roles / "_roles.json").write_text(
        json.dumps({"mode": "track", "acceptance": "auto", "roles": {}}), encoding="utf-8")
    out = _index_rollup(pt, specs)
    assert out["pending"] is None


def test_ownership_drift_from_activity_log(pt, new_plan, specs):
    new_plan("drift-anchor")  # ensures specs has content
    roles = specs.parent / "roles"
    roles.mkdir()
    (roles / "_roles.json").write_text(json.dumps({
        "mode": "track", "acceptance": "manual",
        "roles": {"engineer-api": {"source_of_truth": ["specs/api-*.html"],
                                   "code": ["src/api/**"], "supporting": [],
                                   "owns": ["src/api/**"]}}}), encoding="utf-8")
    (roles / "activity.log.ndjson").write_text(
        json.dumps({"ts": "2026-07-01T10:00:00-05:00", "path": "src/api/x.py",
                    "tool": "Edit", "role": "ux", "session": "s1",
                    "owner": "engineer-api"}) + "\n", encoding="utf-8")
    out = _index_rollup(pt, specs)
    hits = out["drift"].get("engineer-api", [])
    assert any(h["path"] == "src/api/x.py" and h["actor"] == "ux" for h in hits)


def test_checkpoints_section_in_rollup(pt, new_plan, specs):
    # synthesize a checkpoint event directly on the sidecar and confirm rollup surfaces it
    plan = new_plan("ck")
    from conftest import read as _r
    sc = plan.with_suffix(".log.ndjson")
    with open(sc, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": "2026-07-02T09:00:00-05:00", "event": "checkpoint",
                            "role": "engineer-api", "agent": None, "session": None,
                            "details": {"plan": "ck.html", "sha": "abc123def456",
                                        "tag": "planf3/ck/1", "label": "done"}}) + "\n")
    out = _index_rollup(pt, specs)
    assert "ck.html" in out["checkpoints"]
    assert out["checkpoints"]["ck.html"]["tag"] == "planf3/ck/1"
