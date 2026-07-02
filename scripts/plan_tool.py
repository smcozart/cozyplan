#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""planf3 plan_tool — deterministic writes, validation, and indexing for specs/*.html plans.

Every structured mutation of a living plan artifact goes through this tool instead of
free-form edits, so status markers, append-only metadata, references, and amendments stay
well-formed. Locating regions relies on machine-readable data-* anchors baked into the
plan template (see .claude/skills/planf3/SKILL.md). Stdlib only — run via `uv run`.

Commands:
  status     flip a task/phase status marker
  meta       set or append a metadata field
  ref        add a bidirectional back/forward reference between two plans
  amend      append an amendment entry
  build-meta convenience: append commit/agent/session + stamp modified
  report     append a cross-role report-back event
  validate   lint a plan (leftover tokens, markers, metadata, images, refs)
  index      scan specs/ -> _index.json + _index.html, flag dangling refs + doc drift
  init-ids   assign data-* anchors to a plan that lacks them (additive, reviewable)
  roles      build: generate roles/_roles.json + .github/CODEOWNERS from roles/*.md
  rollup     scan event logs + _index.json -> specs/_status.{json,html} (architect view)

Every mutating command appends a one-line JSON event to specs/<plan>.log.ndjson (the
append-only, merge-friendly multi-writer surface) and updates the human-readable HTML.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# ── vocab / field classification ──────────────────────────────────────────────
STATUS_MARKERS = {"idle": "[]", "wip": "[wip]", "x": "[x]", "f": "[f]"}
VALID_MARKERS = set(STATUS_MARKERS.values())
STATUS_VOCAB = {"draft", "active", "built", "superseded", "archived"}
LIST_FIELDS = {"modified", "commits", "agent", "session", "back-refs", "forward-refs"}
SINGLE_FIELDS = {"id", "created", "status", "owner", "schema"}
ALL_FIELDS = LIST_FIELDS | SINGLE_FIELDS
WRITE_ONCE = {"id", "created", "schema"}

# Artifact structural-contract version. The tool declares the schema range it
# understands and refuses structured writes to a plan stamped newer than MAX, so an
# old tool never corrupts a newer artifact. init-ids stamps schema=1 on legacy plans.
MIN_SCHEMA = 1
MAX_SCHEMA = 1

# rollup: a plan whose latest report is older than this (or has none) is flagged stale.
STALE_DAYS = 14
EMPTY_MARKERS = {"", "—", "-", "–"}
DENYLIST = ["gpt-image", "OPENAI_API_KEY", "generate_gpt_image", "edit_gpt_image", "image-generation.md"]
LABEL_MAP = {
    "agent name": "agent",
    "session id": "session",
    "back refs": "back-refs",
    "forward refs": "forward-refs",
}


# ── small utilities ───────────────────────────────────────────────────────────
def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def read(path: Path) -> str:
    with open(path, "r", encoding="utf-8", newline="") as f:
        return f.read()


def write(path: Path, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def detect_nl(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def esc(v: str) -> str:
    return v.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def strip_tags(v: str) -> str:
    return re.sub(r"<[^>]+>", "", v).strip()


def is_placeholder(v: str) -> bool:
    return bool(re.fullmatch(r"\{\{.*?\}\}", v.strip(), re.S))


def is_empty_value(v: str) -> bool:
    return strip_tags(v) in EMPTY_MARKERS or is_placeholder(v)


def split_list(v: str) -> list[str]:
    v = strip_tags(v)
    if v in EMPTY_MARKERS or is_placeholder(v):
        return []
    return [x.strip() for x in v.split(",") if x.strip()]


def fail(msg: str) -> int:
    print(f"error: {msg}", file=sys.stderr)
    return 1


# ── metadata parsing / mutation ───────────────────────────────────────────────
def parse_meta(text: str) -> dict[str, str]:
    """Read metadata, preferring data-meta anchors and falling back to legacy dt/dd pairs."""
    meta: dict[str, str] = {}
    for m in re.finditer(r'<dd\b[^>]*\bdata-meta="([^"]+)"[^>]*>(.*?)</dd>', text, re.S):
        meta[m.group(1)] = strip_tags(m.group(2))
    if meta:
        return meta
    for m in re.finditer(r"<dt>([^<]+)</dt>\s*<dd\b[^>]*>(.*?)</dd>", text, re.S):
        label = m.group(1).strip().lower()
        meta[LABEL_MAP.get(label, label)] = strip_tags(m.group(2))
    return meta


def _meta_pattern(field: str) -> re.Pattern:
    return re.compile(
        r'(<dd\b[^>]*\bdata-meta="' + re.escape(field) + r'"[^>]*>)(.*?)(</dd>)', re.S
    )


def get_meta_raw(text: str, field: str):
    m = _meta_pattern(field).search(text)
    return m.group(2) if m else None


def set_meta(text: str, field: str, new_content: str) -> tuple[str, int]:
    return _meta_pattern(field).subn(lambda m: m.group(1) + new_content + m.group(3), text, count=1)


def append_meta(text: str, field: str, value: str) -> tuple[str, int]:
    cur = get_meta_raw(text, field)
    if cur is None:
        return text, 0
    if is_empty_value(cur):
        new_content = esc(value)
    else:
        if value in split_list(cur):
            return text, 1  # already present, no-op (still "found")
        new_content = cur.strip() + ", " + esc(value)
    return set_meta(text, field, new_content)


# ── event log sidecar ─────────────────────────────────────────────────────────
def sidecar_path(plan_path: Path) -> Path:
    return plan_path.with_suffix(".log.ndjson")


def log_event(plan_path: Path, event: str, args, details: dict) -> None:
    rec = {
        "ts": now_iso(),
        "event": event,
        "role": getattr(args, "role", None),
        "agent": getattr(args, "agent", None),
        "session": getattr(args, "session", None),
        "details": details,
    }
    with open(sidecar_path(plan_path), "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ── validation ────────────────────────────────────────────────────────────────
_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.-]*:")  # github:, http:, etc. (not Windows C:\)


def _looks_local_ref(ref: str) -> bool:
    ref = ref.split("(")[0].strip()
    if _SCHEME_RE.match(ref):
        return False
    return ref.endswith((".html", ".md")) or "/" in ref or "\\" in ref


def resolve_ref(plan_path: Path, ref: str) -> Path | None:
    ref = ref.split("(")[0].strip()
    if not _looks_local_ref(ref):
        return None
    return plan_path.parent / ref


def validate_text(path: Path, text: str) -> tuple[list[str], list[str], bool]:
    problems: list[str] = []
    warns: list[str] = []
    anchored = 'data-meta="' in text

    # Leftover {{}} tokens are expected in a fresh scaffold, so they are only a
    # warning while status=draft (a `new` scaffold validates clean, exit 0) and a
    # hard failure once the plan leaves draft — every slot must be filled by then.
    status = strip_tags(get_meta_raw(text, "status") or "")
    tokens = re.findall(r"\{\{.*?\}\}", text, re.S)
    if tokens:
        msg = f"{len(tokens)} leftover {{{{}}}} placeholder token(s)"
        if status == "draft":
            warns.append(msg + " (allowed while status=draft; fill before leaving draft)")
        else:
            problems.append(msg)

    for m in re.finditer(r'<code\b[^>]*\bclass="status"[^>]*>(.*?)</code>', text, re.S):
        val = m.group(1).strip()
        if val not in VALID_MARKERS:
            problems.append(f"invalid status marker {val!r} (expected [] / [wip] / [x] / [f])")

    if not anchored:
        return problems, warns, False  # legacy: reduced checks only

    meta = parse_meta(text)
    for field in ("id", "status", "created", "schema"):
        if not meta.get(field) or meta[field] in EMPTY_MARKERS or is_placeholder(meta.get(field, "")):
            problems.append(f"metadata field {field!r} is missing or empty")
    if meta.get("schema") and meta["schema"].isdigit() and int(meta["schema"]) > MAX_SCHEMA:
        problems.append(f"schema {meta['schema']} newer than supported {MAX_SCHEMA}; update planf3")
    if meta.get("status") and meta["status"] not in STATUS_VOCAB:
        problems.append(f"status {meta['status']!r} not in {sorted(STATUS_VOCAB)}")
    if meta.get("created") and "," in meta["created"]:
        problems.append("metadata 'created' must be a single value, not a list")
    if meta.get("status") == "superseded" and not split_list(meta.get("forward-refs", "")):
        problems.append("status 'superseded' requires a forward ref to its successor")
    if "data-amendments-list" not in text:
        problems.append("amendments list container (data-amendments-list) missing")

    for fld in ("back-refs", "forward-refs"):
        for ref in split_list(meta.get(fld, "")):
            rp = resolve_ref(path, ref)
            if rp is None:
                warns.append(f"{fld} {ref!r} is external / non-file (not verified)")
            elif not rp.exists():
                problems.append(f"{fld} {ref!r} does not resolve to a file")

    for m in re.finditer(r'<img\b[^>]*\bsrc="([^"]+)"', text):
        src = m.group(1)
        if src.startswith(("http://", "https://", "data:")):
            continue
        if not (path.parent / src).exists():
            problems.append(f"image {src!r} not found on disk")

    return problems, warns, True


def cmd_validate(args) -> int:
    path = Path(args.plan)
    if not path.exists():
        return fail(f"plan not found: {path}")
    text = read(path)
    problems, warns, anchored = validate_text(path, text)
    if not anchored:
        print(f"[legacy] {path.name}: no data-* anchors present - run: plan_tool init-ids {path}")
    for w in warns:
        print(f"  warn: {w}")
    if problems:
        print(f"FAIL {path.name}: {len(problems)} problem(s)")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"OK {path.name}: valid" + (" (legacy, reduced checks)" if not anchored else ""))
    return 0


def self_validate(path: Path, text: str) -> None:
    problems, warns, _ = validate_text(path, text)
    for w in warns:
        print(f"  warn: {w}")
    for p in problems:
        print(f"  post-write warn: {p}")


# ── mutating commands ─────────────────────────────────────────────────────────
def _require_anchored(path: Path, text: str) -> bool:
    if 'data-meta="' not in text:
        print(f"{path.name} has no data-* anchors - run: plan_tool init-ids {path}",
              file=sys.stderr)
        return False
    return True


def stamp_modified(text: str, iso: str) -> str:
    new, n = append_meta(text, "modified", iso)
    return new if n else text


def schema_ok(path: Path, text: str) -> bool:
    """Refuse structured writes to a plan whose schema stamp is newer than this tool.

    Absent/placeholder schema (pre-schema or legacy plans) is treated as compatible;
    init-ids/migrate stamp it. Only a stamp strictly greater than MAX_SCHEMA blocks.
    """
    raw = get_meta_raw(text, "schema")
    if raw is None or is_empty_value(raw):
        return True
    try:
        n = int(strip_tags(raw))
    except ValueError:
        return True  # tolerate a non-numeric stamp rather than block
    if n > MAX_SCHEMA:
        fail(f"{path.name} declares schema {n} but this plan_tool supports up to "
             f"{MAX_SCHEMA}; update planf3 before writing this plan")
        return False
    return True


def cmd_status(args) -> int:
    path = Path(args.plan)
    if not path.exists():
        return fail(f"plan not found: {path}")
    if args.state not in STATUS_MARKERS:
        return fail(f"state must be one of {sorted(STATUS_MARKERS)}")
    if args.state == "f" and not args.reason:
        return fail("state 'f' (failed) requires --reason (one-line explanation)")
    text = read(path)
    if not schema_ok(path, text):
        return 1
    marker = STATUS_MARKERS[args.state]
    pat = re.compile(r'(data-status-for="' + re.escape(args.id) + r'"[^>]*>)\[[^\]]*\]')
    new, n = pat.subn(lambda m: m.group(1) + marker, text, count=1)
    if n == 0:
        return fail(f"no status anchor data-status-for={args.id!r} found (run init-ids?)")
    nl = detect_nl(new)
    new = stamp_modified(new, now_iso())
    if args.state == "f":
        new = append_amendment(new, nl, now_iso(), f"task {args.id} marked failed", args.reason)
    write(path, new)
    log_event(path, "status", args, {"id": args.id, "state": args.state, "reason": args.reason})
    print(f"status {args.id} -> {marker} in {path.name}")
    self_validate(path, new)
    return 0


def cmd_meta(args) -> int:
    path = Path(args.plan)
    if not path.exists():
        return fail(f"plan not found: {path}")
    if args.field not in ALL_FIELDS:
        return fail(f"unknown field {args.field!r}; valid: {sorted(ALL_FIELDS)}")
    text = read(path)
    if not _require_anchored(path, text):
        return 1
    if not schema_ok(path, text):
        return 1
    if args.field == "status" and args.value not in STATUS_VOCAB:
        return fail(f"status must be one of {sorted(STATUS_VOCAB)}")

    if args.field in SINGLE_FIELDS:
        cur = get_meta_raw(text, args.field)
        if cur is None:
            return fail(f"no data-meta anchor for {args.field!r} (run init-ids?)")
        if args.field in WRITE_ONCE and not is_empty_value(cur) and not args.force:
            return fail(f"{args.field!r} is write-once (currently {strip_tags(cur)!r}); use --force to override")
        new, n = set_meta(text, args.field, esc(args.value))
    else:
        new, n = append_meta(text, args.field, args.value)
    if n == 0:
        return fail(f"could not locate metadata field {args.field!r}")
    if args.field != "modified":
        new = stamp_modified(new, now_iso())
    write(path, new)
    log_event(path, "meta", args, {"field": args.field, "value": args.value})
    print(f"meta {args.field} <- {args.value!r} in {path.name}")
    self_validate(path, new)
    return 0


def cmd_build_meta(args) -> int:
    path = Path(args.plan)
    if not path.exists():
        return fail(f"plan not found: {path}")
    text = read(path)
    if not _require_anchored(path, text):
        return 1
    if not schema_ok(path, text):
        return 1
    applied = []
    for field, value in (("commits", args.commit), ("agent", args.agent), ("session", args.session)):
        if value:
            text, n = append_meta(text, field, value)
            if n:
                applied.append(f"{field}={value}")
    text = stamp_modified(text, now_iso())
    write(path, text)
    log_event(path, "build-meta", args, {"applied": applied})
    print(f"build-meta applied [{', '.join(applied) or 'nothing'}] in {path.name}")
    self_validate(path, text)
    return 0


def append_amendment(text: str, nl: str, iso: str, summary: str, detail: str) -> str:
    m = re.search(r"(<div\b[^>]*\bdata-amendments-list\b[^>]*>)(.*?)(</div>)", text, re.S)
    if not m:
        return text  # caller/validate will flag the missing container
    entry = (
        f"{nl}      <details>"
        f"{nl}        <summary>{esc(iso)} — {esc(summary)}</summary>"
        f"{nl}        <p>{esc(detail)}</p>"
        f"{nl}      </details>"
    )
    insert_at = m.end(2)
    return text[:insert_at] + entry + text[insert_at:]


def cmd_amend(args) -> int:
    path = Path(args.plan)
    if not path.exists():
        return fail(f"plan not found: {path}")
    text = read(path)
    if not _require_anchored(path, text):
        return 1
    if not schema_ok(path, text):
        return 1
    if "data-amendments-list" not in text:
        return fail("no data-amendments-list container (run init-ids?)")
    nl = detect_nl(text)
    iso = args.iso or now_iso()
    text = append_amendment(text, nl, iso, args.summary, args.detail)
    text = stamp_modified(text, now_iso())
    write(path, text)
    log_event(path, "amend", args, {"summary": args.summary})
    print(f"amend appended to {path.name}")
    self_validate(path, text)
    return 0


def cmd_ref(args) -> int:
    this_path = Path(args.this)
    other_path = Path(args.other)
    for p in (this_path, other_path):
        if not p.exists():
            return fail(f"plan not found: {p}")
    this_text = read(this_path)
    other_text = read(other_path)
    if 'data-meta="' not in this_text:
        return fail(f"{this_path.name} lacks anchors — run: plan_tool init-ids {this_path}")
    if 'data-meta="' not in other_text:
        return fail(f"{other_path.name} lacks anchors — run: plan_tool init-ids {other_path}")
    if not schema_ok(this_path, this_text) or not schema_ok(other_path, other_text):
        return 1

    this_field = "back-refs" if args.dir == "back" else "forward-refs"
    other_field = "forward-refs" if args.dir == "back" else "back-refs"
    this_val = other_path.name
    other_val = this_path.name
    iso = now_iso()

    this_text, n1 = append_meta(this_text, this_field, this_val)
    other_text, n2 = append_meta(other_text, other_field, other_val)
    if not n1 or not n2:
        return fail("could not locate a reference field on one of the plans")

    nl1, nl2 = detect_nl(this_text), detect_nl(other_text)
    this_text = stamp_modified(this_text, iso)
    other_text = stamp_modified(other_text, iso)
    this_text = append_amendment(this_text, nl1, iso, f"{this_field} += {this_val}",
                                 f"Linked to {other_path.name} ({args.dir} reference).")
    other_text = append_amendment(other_text, nl2, iso, f"{other_field} += {other_val}",
                                  f"Reciprocal link from {this_path.name}.")
    write(this_path, this_text)
    write(other_path, other_text)
    log_event(this_path, "ref", args, {"field": this_field, "other": this_val, "dir": args.dir})
    log_event(other_path, "ref", args, {"field": other_field, "other": other_val, "dir": args.dir})
    print(f"ref: {this_path.name} [{this_field}] <-> {other_path.name} [{other_field}]")
    self_validate(this_path, this_text)
    self_validate(other_path, other_text)
    return 0


def cmd_report(args) -> int:
    path = Path(args.plan)
    if not path.exists():
        return fail(f"plan not found: {path}")
    text = read(path)
    if not schema_ok(path, text):
        return 1
    commits = [c.strip() for c in (args.commits or "").split(",") if c.strip()]
    details = {
        "plan": path.name,
        "report_status": args.status,
        "summary": args.summary,
        "commits": commits,
    }
    log_event(path, "report", args, details)
    # HTML snapshot: append-only amendment so the report is visible in the readable artifact.
    if "data-amendments-list" in text:
        nl = detect_nl(text)
        iso = now_iso()
        who = args.role or args.agent or "role"
        text = append_amendment(text, nl, iso, f"report-back ({who}): {args.status}", args.summary)
        write(path, text)
    else:
        print("  warn: no amendments container; report recorded in event log only")
    print(f"report ({args.role or 'role'}) status={args.status} on {path.name}")
    return 0


# ── init-ids (additive anchor assignment) ─────────────────────────────────────
def _upgrade_meta_details(text: str) -> str:
    m = re.search(r'<details\b[^>]*\bclass="meta"[^>]*>', text)
    if not m:
        return text
    tag = m.group(0)
    if "data-region=" not in tag:
        tag = tag[:-1] + ' data-region="metadata"' + ">"
    if "data-managed=" not in tag:
        tag = tag[:-1] + ' data-managed="cli"' + ">"
    return text[: m.start()] + tag + text[m.end():]


def _tag_dds(text: str) -> str:
    def repl(m):
        ddtag = m.group("ddtag")
        if "data-meta=" in ddtag:
            return m.group(0)
        label = m.group("label").strip().lower()
        field = LABEL_MAP.get(label, label)
        newdd = ddtag[:-1] + f' data-meta="{field}"' + ">"
        return m.group("dt") + m.group("ws") + newdd

    return re.sub(
        r"(?P<dt><dt>(?P<label>[^<]+)</dt>)(?P<ws>\s*)(?P<ddtag><dd\b[^>]*>)",
        repl, text,
    )


def _ensure_new_fields(text: str, nl: str) -> str:
    m = re.search(r"<dl>", text)
    if not m:
        return text
    additions = ""
    for field, default in (("id", ""), ("owner", ""), ("status", "draft"), ("schema", str(MIN_SCHEMA))):
        if f'data-meta="{field}"' not in text:
            additions += f'{nl}        <dt>{field}</dt> <dd data-meta="{field}">{default}</dd>'
    if not additions:
        return text
    ins = m.end()
    return text[:ins] + additions + text[ins:]


def _number_phases(text: str) -> str:
    phases = list(re.finditer(r'<div\b[^>]*\bclass="phase"[^>]*>', text))
    for i in range(len(phases) - 1, -1, -1):
        pnum = i + 1
        seg_start = phases[i].end()
        seg_end = phases[i + 1].start() if i + 1 < len(phases) else len(text)
        seg = text[seg_start:seg_end]
        counter = [0]

        def repl(m):
            tag = m.group(0)
            if "data-status-for=" in tag:
                counter[0] += 1
                return tag
            sid = f"phase-{pnum}" if counter[0] == 0 else f"{pnum}.{counter[0]}"
            counter[0] += 1
            return tag[:-1] + f' data-status-for="{sid}"' + ">"

        seg = re.sub(r'<code\b[^>]*\bclass="status"[^>]*>', repl, seg)
        text = text[:seg_start] + seg + text[seg_end:]
        ptag = phases[i].group(0)
        if "data-phase=" not in ptag:
            newp = ptag[:-1] + f' data-phase="{pnum}"' + ">"
            text = text[: phases[i].start()] + newp + text[phases[i].end():]
    return text


def _wrap_amendments(text: str, nl: str) -> str:
    m = re.search(r'(<section\b[^>]*\bid="amendments"[^>]*>)(.*?)(</section>)', text, re.S)
    if not m:
        return text
    sect_open, body, sect_close = m.group(1), m.group(2), m.group(3)
    if "data-region=" not in sect_open:
        sect_open = sect_open[:-1] + ' data-region="amendments" data-managed="cli"' + ">"
    if "data-amendments-list" not in body:
        hm = re.search(r"</h2>", body)
        if hm:
            head, rest = body[: hm.end()], body[hm.end():]
            body = f"{head}{nl}    <div data-amendments-list>{rest}{nl}    </div>{nl}  "
    return text[: m.start()] + sect_open + body + sect_close + text[m.end():]


def cmd_init_ids(args) -> int:
    path = Path(args.plan)
    if not path.exists():
        return fail(f"plan not found: {path}")
    text = read(path)
    nl = detect_nl(text)
    original = text
    text = _upgrade_meta_details(text)
    text = _ensure_new_fields(text, nl)
    text = _tag_dds(text)
    text = _number_phases(text)
    text = _wrap_amendments(text, nl)
    if text == original:
        print(f"init-ids: {path.name} already anchored, no changes")
        return 0
    write(path, text)
    log_event(path, "init-ids", args, {})
    print(f"init-ids: anchored {path.name}")
    self_validate(path, text)
    return 0


# ── index ─────────────────────────────────────────────────────────────────────
def extract_title(text: str) -> str:
    m = re.search(r"<title>\s*Plan:\s*(.*?)</title>", text, re.S) or re.search(
        r"<title>(.*?)</title>", text, re.S
    )
    return strip_tags(m.group(1)) if m else ""


def scan_drift(root: Path) -> list[tuple[str, int, str]]:
    hits: list[tuple[str, int, str]] = []
    exts = {".md", ".html", ".txt", ".sample", ".json", ".cfg", ".ini", ".toml", ".yml", ".yaml"}
    exclude_names = {"RAW.md", "legacy_v1_meta_plan.md", "_index.html", "_index.json"}
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        parts = set(p.parts)
        if ".git" in parts or "scripts" in parts or "node_modules" in parts:
            continue
        if p.name in exclude_names or p.name.upper().startswith("CHANGELOG"):
            continue
        if p.suffix.lower() not in exts:
            continue
        try:
            content = read(p)
        except (OSError, UnicodeDecodeError):
            continue
        for i, line in enumerate(content.splitlines(), 1):
            for tok in DENYLIST:
                if tok in line:
                    hits.append((str(p), i, tok))
    return hits


def render_index_html(plans: list[dict], dangling: list, as_of: str = "") -> str:
    order = ["active", "draft", "built", "superseded", "archived", ""]
    by_status: dict[str, list[dict]] = {}
    for p in plans:
        by_status.setdefault(p["status"] or "", []).append(p)
    owners = sorted({p["owner"] for p in plans if p["owner"]})
    rows = []
    for st in order:
        group = by_status.get(st)
        if not group:
            continue
        rows.append(f'<h2>{esc(st or "unspecified")} <span class="count">{len(group)}</span></h2>')
        rows.append("<ul>")
        for p in sorted(group, key=lambda x: x["file"]):
            refs = ""
            if p["forward_refs"]:
                refs += f' <span class="ref">→ {esc(", ".join(p["forward_refs"]))}</span>'
            if p["back_refs"]:
                refs += f' <span class="ref">← {esc(", ".join(p["back_refs"]))}</span>'
            owner = f' <span class="owner">{esc(p["owner"])}</span>' if p["owner"] else ""
            rows.append(
                f'  <li><a href="{esc(p["file"])}">{esc(p["title"] or p["file"])}</a>'
                f'{owner}{refs}</li>'
            )
        rows.append("</ul>")
    danger = ""
    if dangling:
        items = "".join(f"<li>{esc(f)} [{esc(fld)}] → {esc(r)}</li>" for f, fld, r in dangling)
        danger = f'<div class="danger"><strong>Dangling references:</strong><ul>{items}</ul></div>'
    owner_facet = ""
    if owners:
        owner_facet = '<p class="facet">Owners: ' + ", ".join(esc(o) for o in owners) + "</p>"
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>planf3 — Plan Index</title>
<style>
  :root {{ --bg:#0E1116; --surface:#161B22; --border:#2A3344; --text:#E6EAF2;
    --muted:#9AA7BD; --violet:#8B7FF7; --amber:#F5B547; --red:#F87171; }}
  body {{ margin:0; background:var(--bg); color:var(--text);
    font-family:-apple-system,"Segoe UI",Roboto,sans-serif; line-height:1.6; }}
  main {{ max-width:900px; margin:0 auto; padding:48px 24px 96px; }}
  h1 {{ letter-spacing:-.02em; }}
  h2 {{ margin-top:2em; border-bottom:1px solid var(--border); padding-bottom:.3em;
    text-transform:capitalize; }}
  .count {{ color:var(--muted); font-size:.7em; font-weight:normal; }}
  ul {{ list-style:none; padding-left:0; }}
  li {{ padding:6px 0; border-bottom:1px solid var(--border); }}
  a {{ color:var(--violet); text-decoration:none; font-weight:600; }}
  a:hover {{ text-decoration:underline; }}
  .owner {{ color:var(--amber); font-size:.85em; margin-left:8px; }}
  .ref {{ color:var(--muted); font-size:.8em; margin-left:8px; }}
  .facet {{ color:var(--muted); }}
  .danger {{ background:rgba(248,113,113,.1); border:1px solid var(--red);
    border-radius:10px; padding:12px 16px; margin:16px 0; color:var(--red); }}
  footer {{ color:var(--muted); font-size:.8em; margin-top:3em; }}
</style></head>
<body><main>
  <h1>Plan Index</h1>
  {owner_facet}
  {danger}
  {chr(10).join(rows) if rows else "<p>No plans found.</p>"}
  <footer>Generated by plan_tool index{f" (content as of {esc(as_of)})" if as_of else ""}. Derived artifact — do not hand-edit.</footer>
</main></body></html>
"""


def cmd_index(args) -> int:
    specs = Path(args.specs)
    if not specs.exists():
        return fail(f"specs dir not found: {specs}")
    plans = []
    for hp in sorted(specs.glob("*.html")):
        if hp.name.startswith("_"):
            continue
        text = read(hp)
        meta = parse_meta(text)
        plans.append({
            "file": hp.name,
            "id": meta.get("id", ""),
            "title": extract_title(text),
            "status": meta.get("status", ""),
            "owner": meta.get("owner", ""),
            "created": meta.get("created", ""),
            "modified": (split_list(meta.get("modified", "")) or [""])[-1],
            "image_dir": hp.stem + "/" if (specs / hp.stem).is_dir() else "",
            "back_refs": split_list(meta.get("back-refs", "")),
            "forward_refs": split_list(meta.get("forward-refs", "")),
        })

    dangling = []
    for p in plans:
        for fld_key, fld_name in (("back_refs", "back-refs"), ("forward_refs", "forward-refs")):
            for r in p[fld_key]:
                rr = r.split("(")[0].strip()
                if _SCHEME_RE.match(rr):
                    continue
                if rr.endswith((".html", ".md")) and not (specs / rr).exists():
                    dangling.append((p["file"], fld_name, rr))

    # Deterministic output: stamp with the newest content timestamp, not the run
    # time, so re-running index on unchanged inputs produces a byte-identical file.
    as_of = max((p["modified"] or p["created"] for p in plans), default="")
    (specs / "_index.json").write_text(
        json.dumps({"as_of": as_of, "plans": plans, "dangling": dangling},
                   indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (specs / "_index.html").write_text(render_index_html(plans, dangling, as_of), encoding="utf-8")

    drift = scan_drift(Path(args.root))

    print(f"index: {len(plans)} plan(s) -> {specs}/_index.json, {specs}/_index.html")
    if dangling:
        print(f"  dangling refs ({len(dangling)}):")
        for f, fld, r in dangling:
            print(f"    {f} [{fld}] -> {r}")
    if drift:
        print(f"  docs-drift hits ({len(drift)}) [retired-pipeline tokens]:")
        for f, ln, tok in drift[:50]:
            print(f"    {f}:{ln}: {tok}")
    if not dangling and not drift:
        print("  clean: no dangling refs, no doc drift")
    return 0


# ── roles build (manifest + CODEOWNERS from roles/*.md) ───────────────────────
def parse_role_frontmatter(md_text: str) -> dict | None:
    """Parse the flat-ish YAML frontmatter of a role file (no PyYAML).

    Extracts `role`, `reports_to`, and the nested `owns.{source_of_truth,code,supporting}`
    lists — the only fields `roles build` needs. Tolerates the richer nested blocks
    (definition_of_done, report_back) by ignoring them.
    """
    m = re.match(r"^﻿?---\s*\n(.*?)\n---\s*\n?", md_text, re.S)
    if not m:
        return None
    lines = m.group(1).split("\n")
    out = {"role": None, "reports_to": None,
           "owns": {"source_of_truth": [], "code": [], "supporting": []}}

    def _unquote(s: str) -> str:
        return s.strip().strip('"').strip("'").strip()

    for ln in lines:
        ms = re.match(r"^role:\s*(.+)$", ln)
        if ms:
            out["role"] = _unquote(ms.group(1))
        mr = re.match(r"^reports_to:\s*(.+)$", ln)
        if mr:
            out["reports_to"] = _unquote(mr.group(1))

    owns_idx = next((k for k, ln in enumerate(lines) if re.match(r"^owns:\s*$", ln)), None)
    if owns_idx is not None:
        cur_sub = None
        for ln in lines[owns_idx + 1:]:
            if ln.strip() == "":
                continue
            if re.match(r"^\S", ln):  # dedent to column 0 -> owns block ended
                break
            msub = re.match(r"^  (\w+):\s*(.*)$", ln)
            if msub and not msub.group(2).strip().startswith("-"):
                cur_sub = msub.group(1)
                out["owns"].setdefault(cur_sub, [])
                inline = msub.group(2).strip()
                if inline.startswith("[") and inline.endswith("]"):
                    out["owns"][cur_sub].extend(
                        _unquote(x) for x in inline[1:-1].split(",") if x.strip())
                    cur_sub = None
                continue
            mitem = re.match(r"^\s*-\s*(.+)$", ln)
            if mitem and cur_sub:
                out["owns"][cur_sub].append(_unquote(mitem.group(1)))
    return out


def _glob_prefix(g: str) -> str:
    g = g.replace("\\", "/")
    idx = len(g)
    for ch in "*?[":
        j = g.find(ch)
        if j != -1:
            idx = min(idx, j)
    return g[:idx]


def check_disjoint(role_globs: dict[str, list[str]]) -> list[tuple[str, str, str, str]]:
    """Return (role1, glob1, role2, glob2) pairs whose ownership prefixes overlap."""
    flat = [(role, g, _glob_prefix(g)) for role, globs in role_globs.items() for g in globs]
    conflicts = []
    for i in range(len(flat)):
        for j in range(i + 1, len(flat)):
            r1, g1, p1 = flat[i]
            r2, g2, p2 = flat[j]
            if r1 == r2 or not p1 or not p2:
                continue
            if p1.startswith(p2) or p2.startswith(p1):
                conflicts.append((r1, g1, r2, g2))
    return conflicts


def _glob_to_codeowners(g: str) -> str:
    g = g.replace("\\", "/")
    if g.endswith("/**"):
        return g[:-3] + "/"
    return g.replace("/**/", "/").replace("**", "*")


def render_codeowners(roles_out: dict) -> str:
    lines = [
        "# GENERATED by plan_tool roles build - do not hand-edit. Source: roles/*.md",
        "",
    ]
    for role, info in roles_out.items():
        lines.append(f"# {role}")
        for g in info["owns"]:
            lines.append(f"{_glob_to_codeowners(g)}  @{role}")
        lines.append("")
    return "\n".join(lines) + "\n"


def cmd_roles(args) -> int:
    if args.roles_cmd != "build":
        return fail("only 'roles build' is supported")
    roles_dir = Path(args.dir)
    if not roles_dir.exists():
        return fail(f"roles dir not found: {roles_dir}")
    parsed = {}
    for rf in sorted(roles_dir.glob("*.md")):
        if rf.name.startswith("_"):
            continue
        data = parse_role_frontmatter(read(rf))
        if not data or not data.get("role"):
            print(f"  warn: {rf.name} has no parseable 'role' frontmatter; skipped")
            continue
        parsed[data["role"]] = data
    if not parsed:
        return fail("no roles parsed from roles/*.md")

    sot_code = {r: (d["owns"].get("source_of_truth", []) + d["owns"].get("code", []))
                for r, d in parsed.items()}
    conflicts = check_disjoint(sot_code)
    if conflicts:
        print("FAIL roles build: overlapping source_of_truth/code globs across roles:")
        for r1, g1, r2, g2 in conflicts:
            print(f"  - {r1} {g1!r} overlaps {r2} {g2!r}")
        return 1

    roles_out = {}
    for r, d in parsed.items():
        owns = d["owns"]
        union = list(dict.fromkeys(
            owns.get("source_of_truth", []) + owns.get("code", []) + owns.get("supporting", [])))
        roles_out[r] = {"owns": union, "reports_to": d.get("reports_to")}

    manifest = {"roles": roles_out}
    (roles_dir / "_roles.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    gh = Path(args.codeowners) if args.codeowners else Path(".github") / "CODEOWNERS"
    gh.parent.mkdir(parents=True, exist_ok=True)
    gh.write_text(render_codeowners(roles_out), encoding="utf-8")

    print(f"roles build: {len(roles_out)} role(s) -> {roles_dir}/_roles.json, {gh}")
    for r, info in roles_out.items():
        print(f"  {r}: {len(info['owns'])} owned glob(s)")
    return 0


# ── rollup (architect status dashboard from event logs + _index.json) ─────────
def _parse_ts(ts: str):
    try:
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


def _ymd(ts: str) -> str:
    return ts[:10] if ts else ""


def render_status_html(out: dict) -> str:
    def esc_(s):
        return esc(str(s))

    att_rows = ""
    for a in out["attention"]:
        att_rows += (f'<li><code>{esc_(a["plan"])}</code> — <strong>{esc_(a["kind"])}</strong>'
                     f' {esc_(a["detail"])} <span class="dim">{esc_(_ymd(a.get("ts","")))}</span></li>')
    attention = (f'<div class="danger"><strong>Attention</strong><ul>{att_rows}</ul></div>'
                 if att_rows else "")

    comp_rows = ""
    for owner, plans in sorted(out["components"].items()):
        comp_rows += f'<h3>{esc_(owner)}</h3><table><tr><th>plan</th><th>lifecycle</th><th>latest report</th></tr>'
        for p in plans:
            lr = p.get("latest_report")
            rep = ""
            if lr:
                rep = f'{esc_(lr["status"])} ({esc_(_ymd(lr["ts"]))}) — {esc_(lr["summary"])}'
            comp_rows += (f'<tr><td><a href="{esc_(p["plan"])}">{esc_(p["title"] or p["plan"])}</a></td>'
                          f'<td>{esc_(p["status"])}</td><td>{rep}</td></tr>')
        comp_rows += "</table>"

    acc_rows = ""
    for r in out["accomplishments"]:
        commits = ", ".join(r.get("commits", []))
        commits = f' <span class="dim">[{esc_(commits)}]</span>' if commits else ""
        acc_rows += (f'<li><span class="dim">{esc_(_ymd(r["ts"]))}</span> '
                     f'<strong>{esc_(r["role"])}</strong> {esc_(r["plan"])} — {esc_(r["summary"])}{commits}</li>')
    accomplishments = f"<h2>Accomplishments</h2><ul>{acc_rows}</ul>" if acc_rows else ""

    stale_rows = "".join(
        f'<li><code>{esc_(s["plan"])}</code> — {esc_(s["reason"])}</li>' for s in out["stale"])
    stale = f'<div class="stale"><strong>Stale</strong><ul>{stale_rows}</ul></div>' if stale_rows else ""

    rf = f' (role: {esc_(out["role_filter"])})' if out.get("role_filter") else ""
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>planf3 — Project Status</title>
<style>
  :root {{ --bg:#0E1116; --surface:#161B22; --border:#2A3344; --text:#E6EAF2;
    --muted:#9AA7BD; --dim:#5C6B85; --violet:#8B7FF7; --amber:#F5B547;
    --green:#4ADE80; --red:#F87171; }}
  body {{ margin:0; background:var(--bg); color:var(--text);
    font-family:-apple-system,"Segoe UI",Roboto,sans-serif; line-height:1.6; }}
  main {{ max-width:960px; margin:0 auto; padding:48px 24px 96px; }}
  h1 {{ letter-spacing:-.02em; }}
  h2 {{ margin-top:2em; border-bottom:1px solid var(--border); padding-bottom:.3em; }}
  h3 {{ margin:1.4em 0 .4em; color:var(--amber); }}
  table {{ width:100%; border-collapse:collapse; font-size:.92em; }}
  th, td {{ text-align:left; padding:6px 8px; border-bottom:1px solid var(--border);
    vertical-align:top; }}
  th {{ color:var(--muted); font-weight:600; }}
  a {{ color:var(--violet); text-decoration:none; }}
  a:hover {{ text-decoration:underline; }}
  ul {{ list-style:none; padding-left:0; }}
  li {{ padding:5px 0; border-bottom:1px solid var(--border); }}
  code {{ color:var(--text); }}
  .dim {{ color:var(--dim); font-size:.85em; }}
  .danger {{ background:rgba(248,113,113,.1); border:1px solid var(--red);
    border-radius:10px; padding:12px 16px; margin:16px 0; }}
  .stale {{ background:rgba(245,181,71,.08); border:1px solid var(--amber);
    border-radius:10px; padding:12px 16px; margin:16px 0; }}
  footer {{ color:var(--muted); font-size:.8em; margin-top:3em; }}
</style></head>
<body><main>
  <h1>Project Status{rf}</h1>
  {attention}
  {stale}
  <h2>By component</h2>
  {comp_rows or "<p>No plans found.</p>"}
  {accomplishments}
  <footer>Generated by plan_tool rollup{f" (events as of {esc_(out.get('as_of', ''))})" if out.get("as_of") else ""}. Derived artifact — do not hand-edit.</footer>
</main></body></html>
"""


def cmd_rollup(args) -> int:
    specs = Path(args.specs)
    if not specs.exists():
        return fail(f"specs dir not found: {specs}")

    plan_meta = {}
    idx_path = specs / "_index.json"
    if idx_path.exists():
        try:
            for p in json.loads(read(idx_path)).get("plans", []):
                plan_meta[p["file"]] = p
        except (json.JSONDecodeError, OSError):
            pass

    reports = []
    as_of = ""  # newest event ts across all logs — deterministic output stamp
    for logf in sorted(specs.glob("*.log.ndjson")):
        plan_file = logf.name[: -len(".log.ndjson")] + ".html"
        for line in read(logf).splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            as_of = max(as_of, rec.get("ts", ""))
            if rec.get("event") != "report":
                continue
            det = rec.get("details", {}) or {}
            reports.append({
                "plan": plan_file,
                "ts": rec.get("ts", ""),
                "role": rec.get("role") or "",
                "agent": rec.get("agent") or "",
                "status": det.get("report_status", ""),
                "summary": det.get("summary", ""),
                "commits": det.get("commits", []),
            })
    reports.sort(key=lambda r: r["ts"])

    latest = {}
    for r in reports:
        latest[r["plan"]] = r  # ascending sort -> last write wins

    role_filter = getattr(args, "role", None)
    all_plans = set(plan_meta) | {r["plan"] for r in reports}

    def owner_of(pf):
        return (plan_meta.get(pf, {}) or {}).get("owner", "") or "(unassigned)"

    if role_filter:
        all_plans = {pf for pf in all_plans
                     if (plan_meta.get(pf, {}) or {}).get("owner", "") == role_filter}

    attention = []
    for pf in sorted(all_plans):
        lr = latest.get(pf)
        if lr and lr["status"].lower() in ("blocked", "block", "failed"):
            attention.append({"plan": pf, "kind": "blocked", "detail": lr["summary"], "ts": lr["ts"]})
        hp = specs / pf
        if hp.exists():
            ftasks = len(re.findall(r'<code\b[^>]*\bclass="status"[^>]*>\[f\]</code>', read(hp)))
            if ftasks:
                attention.append({"plan": pf, "kind": "failed-tasks",
                                  "detail": f"{ftasks} task(s) marked [f]", "ts": ""})

    components = {}
    for pf in sorted(all_plans):
        meta = plan_meta.get(pf, {}) or {}
        components.setdefault(owner_of(pf), []).append({
            "plan": pf, "title": meta.get("title", ""), "status": meta.get("status", ""),
            "latest_report": latest.get(pf),
        })

    done = [r for r in reversed(reports) if r["status"].lower() == "done"]
    if role_filter:
        done = [r for r in done if r["plan"] in all_plans]

    now = datetime.now().astimezone()
    stale = []
    for pf in sorted(all_plans):
        lr = latest.get(pf)
        if not lr:
            stale.append({"plan": pf, "reason": "no reports filed"})
            continue
        ts = _parse_ts(lr["ts"])
        if ts and (now - ts).days > STALE_DAYS:
            # Deterministic reason (no live day count): only changes when the latest
            # report changes or a plan first crosses the staleness threshold.
            stale.append({"plan": pf,
                          "reason": f"last report {ts.date().isoformat()} (>{STALE_DAYS}d ago)"})

    out = {"as_of": as_of, "role_filter": role_filter, "attention": attention,
           "components": components, "accomplishments": done, "stale": stale}
    (specs / "_status.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    (specs / "_status.html").write_text(render_status_html(out), encoding="utf-8")

    print(f"rollup: {len(all_plans)} plan(s)" + (f" (role={role_filter})" if role_filter else "")
          + f" -> {specs}/_status.json, {specs}/_status.html")
    if attention:
        print(f"  attention: {len(attention)} item(s)")
    if stale:
        print(f"  stale: {len(stale)} plan(s)")
    return 0


# ── new (deterministic plan scaffolding from templates/plan.html) ─────────────
def template_candidates() -> list[Path]:
    """Ordered locations to look for templates/plan.html.

    Mirrors how the hooks resolve plan_tool.py: prefer CLAUDE_PLUGIN_ROOT (the
    bundled plugin), then the project cwd, then this script's own location — each
    with the in-project `.claude/skills/...` layout and the moved-as-a-unit layout.
    """
    rels = [
        Path(".claude") / "skills" / "planf3" / "templates" / "plan.html",
        Path("skills") / "planf3" / "templates" / "plan.html",
        Path("templates") / "plan.html",
    ]
    roots: list[Path] = []
    pr = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if pr:
        roots.append(Path(pr))
    roots.append(Path.cwd())
    roots.append(Path(__file__).resolve().parent.parent)  # <repo>/scripts/ -> <repo>/
    seen: list[Path] = []
    for root in roots:
        for rel in rels:
            c = root / rel
            if c not in seen:
                seen.append(c)
    return seen


def resolve_template() -> Path | None:
    for c in template_candidates():
        if c.exists():
            return c
    return None


# Structural slots `new` fills; every other {{...}} token is a free-form content
# slot left for the authoring agent. Numeric slots stamp the one example
# phase/task/check block (phase 1, tasks 1.1/1.2, global check g.1).
def _new_substitutions(name: str, args, created: str) -> dict[str, str]:
    return {
        "PLAN_TITLE": esc(args.title),
        "PLAN_ID": esc(name),
        "OWNER_ROLE": esc(args.owner or ""),
        "CREATED_ISO": esc(created),
        "MODIFIED_ISO_LIST": esc(created),
        "COMMIT_SHA_LIST": "—",
        "AGENT_NAME_LIST": esc(args.agent) if args.agent else "—",
        "SESSION_ID_LIST": esc(args.session) if args.session else "—",
        "BACK_REFERENCES": "—",
        "FORWARD_REFERENCES": "—",
        "PHASE_NUMBER": "1",
        "TASK_NUMBER": "1",
        "LAST_TASK_NUMBER": "2",
        "CHECK_NUMBER": "1",
    }


def cmd_new(args) -> int:
    name = args.name
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
        return fail(f"plan name must be kebab-case (lowercase letters, digits, hyphens): {name!r}")
    specs = Path(args.specs)
    path = specs / f"{name}.html"
    if path.exists():
        return fail(f"plan already exists: {path} - refusing to overwrite. "
                    f"Pick a new name, or edit the existing plan in place / via plan_tool.")
    tmpl = resolve_template()
    if tmpl is None:
        looked = "\n  ".join(str(c) for c in template_candidates())
        return fail("plan template (templates/plan.html) not found. Looked in:\n  " + looked)

    text = read(tmpl)
    for tok, val in _new_substitutions(name, args, now_iso()).items():
        text = text.replace("{{" + tok + "}}", val)

    specs.mkdir(parents=True, exist_ok=True)
    write(path, text)
    log_event(path, "created", args,
              {"id": name, "title": args.title, "owner": args.owner or "", "file": path.name})
    print(f"new: created {path} (id={name}, status=draft) from {tmpl}")
    self_validate(path, text)
    return 0


# ── argparse wiring ───────────────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("--role", help="acting role (architect / engineer-<c> / ux) for the event log")
    parent.add_argument("--agent", help="acting agent name (also appended by build-meta)")
    parent.add_argument("--session", help="acting session id (also appended by build-meta)")

    p = argparse.ArgumentParser(prog="plan_tool", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("new", parents=[parent], help="scaffold a fresh plan from templates/plan.html")
    sp.add_argument("name", help="kebab-case plan name (also the immutable id and filename stem)")
    sp.add_argument("--title", required=True, help="human-readable plan title")
    sp.add_argument("--owner", help="owning role (metadata owner field); empty if omitted")
    sp.add_argument("--specs", default="specs", help="specs directory (default: specs)")
    sp.set_defaults(func=cmd_new)

    sp = sub.add_parser("status", parents=[parent], help="flip a task/phase status marker")
    sp.add_argument("plan")
    sp.add_argument("--id", required=True, help="status anchor id, e.g. 1.1 or phase-1")
    sp.add_argument("--state", required=True, choices=list(STATUS_MARKERS))
    sp.add_argument("--reason", help="required when --state f")
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("meta", parents=[parent], help="set or append a metadata field")
    sp.add_argument("plan")
    sp.add_argument("--field", required=True)
    sp.add_argument("--value", required=True)
    sp.add_argument("--force", action="store_true", help="override a write-once field (id/created)")
    sp.set_defaults(func=cmd_meta)

    sp = sub.add_parser("build-meta", parents=[parent], help="append commit/agent/session + stamp modified")
    sp.add_argument("plan")
    sp.add_argument("--commit")
    sp.set_defaults(func=cmd_build_meta)

    sp = sub.add_parser("amend", parents=[parent], help="append an amendment entry")
    sp.add_argument("plan")
    sp.add_argument("--summary", required=True)
    sp.add_argument("--detail", required=True)
    sp.add_argument("--iso", help="override the timestamp")
    sp.set_defaults(func=cmd_amend)

    sp = sub.add_parser("ref", parents=[parent], help="add a bidirectional reference between two plans")
    sp.add_argument("--this", required=True)
    sp.add_argument("--other", required=True)
    sp.add_argument("--dir", required=True, choices=["back", "forward"])
    sp.set_defaults(func=cmd_ref)

    sp = sub.add_parser("report", parents=[parent], help="append a cross-role report-back event")
    sp.add_argument("plan")
    sp.add_argument("--status", required=True, help="report status, e.g. done / blocked / progress")
    sp.add_argument("--summary", required=True)
    sp.add_argument("--commits", help="comma-separated commit SHAs")
    sp.set_defaults(func=cmd_report)

    sp = sub.add_parser("validate", parents=[parent], help="lint a plan")
    sp.add_argument("plan")
    sp.set_defaults(func=cmd_validate)

    sp = sub.add_parser("init-ids", parents=[parent], help="assign data-* anchors (additive)")
    sp.add_argument("plan")
    sp.set_defaults(func=cmd_init_ids)

    sp = sub.add_parser("index", parents=[parent], help="build specs/_index.{json,html}")
    sp.add_argument("--specs", default="specs", help="specs directory (default: specs)")
    sp.add_argument("--root", default=".", help="repo root for doc-drift scan (default: .)")
    sp.set_defaults(func=cmd_index)

    sp = sub.add_parser("roles", parents=[parent], help="build role manifest + CODEOWNERS")
    sp.add_argument("roles_cmd", choices=["build"], help="subcommand (only 'build')")
    sp.add_argument("--dir", default="roles", help="roles directory (default: roles)")
    sp.add_argument("--codeowners", default=None, help="CODEOWNERS output path (default: .github/CODEOWNERS)")
    sp.set_defaults(func=cmd_roles)

    # rollup reuses the shared --role flag from `parent` as its component filter.
    sp = sub.add_parser("rollup", parents=[parent], help="architect status rollup -> specs/_status.{json,html}")
    sp.add_argument("--specs", default="specs", help="specs directory (default: specs)")
    sp.set_defaults(func=cmd_rollup)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
