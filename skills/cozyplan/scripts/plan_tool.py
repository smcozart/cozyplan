#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""cozyplan plan_tool — deterministic writes, validation, and indexing for specs/*.html plans.

Every structured mutation of a living plan artifact goes through this tool instead of
free-form edits, so status markers, append-only metadata, references, and amendments stay
well-formed. Locating regions relies on machine-readable data-* anchors baked into the
plan template (see .claude/skills/cozyplan/SKILL.md). Stdlib only — run via `uv run`.

Commands:
  new        scaffold a fresh plan from templates/plan.html
  status     flip a task/phase status marker
  meta       set or append a metadata field
  ref        add a bidirectional back/forward reference between two plans
  amend      append an amendment entry
  validate   lint a plan (leftover tokens, markers, metadata, images, refs)
  index      scan specs/ -> _index.json + _index.html, flag dangling refs + doc drift
  init-ids   assign data-* anchors to a plan that lacks them (additive, reviewable)
  roles      build: generate roles/_roles.json + .github/CODEOWNERS from roles/*.md
  brief      compact plain-text extract of a plan (or --all for a one-liner index)

Scope: cozyplan is the *plan/intent* layer. Enforcement, revert points, and
accountability are git's job (branches, PRs, CODEOWNERS, tags, CI) — this tool
does not reimplement them. Every mutating command appends a one-line JSON event
to specs/<plan>.log.ndjson (append-only, merge-friendly) and updates the HTML.
"""

from __future__ import annotations

import argparse
import contextlib
import html
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
LIST_FIELDS = {"modified", "commits", "agent", "session", "back-refs", "forward-refs",
               "provides", "consumes"}
SINGLE_FIELDS = {"id", "created", "status", "owner", "schema", "kind"}
ALL_FIELDS = LIST_FIELDS | SINGLE_FIELDS
WRITE_ONCE = {"id", "created", "schema"}
KIND_VOCAB = {"plan"}

# Artifact structural-contract version. The tool declares the schema range it
# understands and refuses structured writes to a plan stamped newer than MAX, so an
# old tool never corrupts a newer artifact. init-ids stamps schema=1 on legacy plans.
MIN_SCHEMA = 1
MAX_SCHEMA = 1
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


# ── glob engine (ONE matcher shared by roles-build disjointness AND the guard) ─
# Semantics, documented once and relied on by both consumers:
#   **   spans directory boundaries (zero or more path segments)
#   *    matches within a single segment (never crosses '/')
#   ?    matches one non-'/' character
#   [..] a character class (passed through to the regex)
# Separators are normalized ('\\' -> '/') before matching. The guard imports
# `glob_match`; `roles build` disjointness uses `glob_overlap`, which is defined
# purely in terms of `glob_match`, so build-time and enforce-time never disagree.
_GLOB_CACHE: dict[str, re.Pattern] = {}


def _compile_glob(glob: str) -> re.Pattern:
    cached = _GLOB_CACHE.get(glob)
    if cached is not None:
        return cached
    g = glob.replace("\\", "/")
    out: list[str] = []
    i, n = 0, len(g)
    while i < n:
        if g[i:i + 3] == "**/":
            out.append("(?:[^/]+/)*")  # zero or more whole directory segments
            i += 3
        elif g[i:i + 2] == "**":
            out.append(".*")            # trailing/!bare ** -> spans everything
            i += 2
        elif g[i] == "*":
            out.append("[^/]*")
            i += 1
        elif g[i] == "?":
            out.append("[^/]")
            i += 1
        elif g[i] == "[":
            j = g.find("]", i + 1)
            if j == -1:
                out.append(re.escape("["))
                i += 1
            else:
                out.append(g[i:j + 1])
                i = j + 1
        else:
            out.append(re.escape(g[i]))
            i += 1
    pat = re.compile("".join(out) + r"\Z")
    _GLOB_CACHE[glob] = pat
    return pat


def glob_match(rel: str, glob: str) -> bool:
    """True if the relative POSIX path `rel` matches ownership glob `glob`."""
    return _compile_glob(glob).match(rel.replace("\\", "/")) is not None


def _glob_witness(glob: str) -> str:
    """A concrete path a glob matches — wildcards resolved to sentinel segments.

    Used only to probe overlap through `glob_match`; the sentinels are arbitrary
    tokens unlikely to collide with real literal segments in another glob.
    """
    g = glob.replace("\\", "/")
    parts = []
    for seg in g.split("/"):
        if seg == "**":
            parts.append("_w_")
        else:
            s = re.sub(r"\[.*?\]", "w", seg).replace("**", "w").replace("*", "w").replace("?", "y")
            parts.append(s if s else "w")
    return "/".join(p for p in parts if p != "")


def glob_overlap(g1: str, g2: str) -> bool:
    """True if some path could be owned by both globs — expressed via `glob_match`.

    Symmetric probe: a witness path generated from each glob is tested against the
    other. Correct for the prefix/segment ownership patterns roles use in practice.
    """
    return glob_match(_glob_witness(g1), g2) or glob_match(_glob_witness(g2), g1)


# ── plan write lock (exclusive, sibling <plan>.lock; Windows-safe) ────────────
LOCK_STALE_SECONDS = 60


class _PlanLock:
    """Exclusive advisory lock for a plan's read-modify-write cycle.

    Created via O_CREAT|O_EXCL (atomic on Windows too). Retries for ~2s; a lock
    older than LOCK_STALE_SECONDS is treated as abandoned, broken with a warning,
    and retried. Always released in __exit__.
    """

    def __init__(self, target: Path):
        self.path = Path(target).with_suffix(".lock")
        self.acquired = False

    def acquire(self) -> None:
        import time
        deadline = time.monotonic() + 2.0
        while True:
            try:
                fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, f"{os.getpid()} {now_iso()}".encode("utf-8"))
                os.close(fd)
                self.acquired = True
                return
            except FileExistsError:
                try:
                    age = time.time() - self.path.stat().st_mtime
                except OSError:
                    age = 0
                if age > LOCK_STALE_SECONDS:
                    print(f"  warn: breaking stale lock {self.path.name} "
                          f"(age {int(age)}s > {LOCK_STALE_SECONDS}s)", file=sys.stderr)
                    try:
                        self.path.unlink()
                    except OSError:
                        pass
                    continue
                if time.monotonic() >= deadline:
                    print(f"  warn: lock {self.path.name} busy; proceeding without it",
                          file=sys.stderr)
                    return  # fail-open: never hard-block a mutation on a busy lock
                time.sleep(0.05)

    def release(self) -> None:
        if self.acquired:
            try:
                self.path.unlink()
            except OSError:
                pass
            self.acquired = False

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        self.release()
        return False


def _sorted_locks(paths: list[Path]) -> list[_PlanLock]:
    # Deterministic acquire order across two-plan ops avoids lock-order deadlock.
    return [_PlanLock(p) for p in sorted(dict.fromkeys(Path(p) for p in paths), key=str)]


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
        problems.append(f"schema {meta['schema']} newer than supported {MAX_SCHEMA}; update cozyplan")
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
             f"{MAX_SCHEMA}; update cozyplan before writing this plan")
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
    with _PlanLock(path):
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
    if args.field == "status" and args.value not in STATUS_VOCAB:
        return fail(f"status must be one of {sorted(STATUS_VOCAB)}")
    if args.field == "kind" and args.value not in KIND_VOCAB:
        return fail(f"kind must be one of {sorted(KIND_VOCAB)}")
    with _PlanLock(path):
        text = read(path)
        if not _require_anchored(path, text):
            return 1
        if not schema_ok(path, text):
            return 1
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
        # Leaving draft is the gate: unfilled {{}} placeholder slots are a warning
        # while draft but must be gone before the plan goes active/built/etc.
        # (validate already flips them warn->fail at this boundary; enforce it at the
        # transition so a plan can't quietly leave draft half-authored). Narrow to
        # placeholders on purpose — an old plan with an unrelated nit can still be
        # archived. Transitions INTO draft never gate.
        if args.field == "status" and args.value != "draft":
            leftover = re.findall(r"\{\{.*?\}\}", new, re.S)
            if leftover:
                return fail(
                    f"cannot move {path.name} to status={args.value!r}: "
                    f"{len(leftover)} unfilled {{{{}}}} placeholder slot(s) remain. "
                    f"Fill every slot (or strip the braces from any intentionally "
                    f"empty diagram comment) before leaving draft.")
        if args.field != "modified":
            new = stamp_modified(new, now_iso())
        write(path, new)
        log_event(path, "meta", args, {"field": args.field, "value": args.value})
    print(f"meta {args.field} <- {args.value!r} in {path.name}")
    self_validate(path, new)
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
    with _PlanLock(path):
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
    # `--type` supersedes the legacy `--dir` (back/forward kept for compatibility).
    rtype = getattr(args, "type", None) or getattr(args, "dir", None)
    if rtype is None:
        return fail("ref requires --type back|forward (or legacy --dir)")
    for p in (this_path, other_path):
        if not p.exists():
            return fail(f"plan not found: {p}")

    with contextlib.ExitStack() as stack:
        for lk in _sorted_locks([this_path, other_path]):
            stack.enter_context(lk)
        this_text = read(this_path)
        other_text = read(other_path)
        if 'data-meta="' not in this_text:
            return fail(f"{this_path.name} lacks anchors — run: plan_tool init-ids {this_path}")
        if 'data-meta="' not in other_text:
            return fail(f"{other_path.name} lacks anchors — run: plan_tool init-ids {other_path}")
        if not schema_ok(this_path, this_text) or not schema_ok(other_path, other_text):
            return 1
        iso = now_iso()

        this_field = "back-refs" if rtype == "back" else "forward-refs"
        other_field = "forward-refs" if rtype == "back" else "back-refs"
        this_val = other_path.name
        other_val = this_path.name

        this_text, n1 = append_meta(this_text, this_field, this_val)
        other_text, n2 = append_meta(other_text, other_field, other_val)
        if not n1 or not n2:
            return fail("could not locate a reference field on one of the plans")

        nl1, nl2 = detect_nl(this_text), detect_nl(other_text)
        this_text = stamp_modified(this_text, iso)
        other_text = stamp_modified(other_text, iso)
        this_text = append_amendment(this_text, nl1, iso, f"{this_field} += {this_val}",
                                     f"Linked to {other_path.name} ({rtype} reference).")
        other_text = append_amendment(other_text, nl2, iso, f"{other_field} += {other_val}",
                                      f"Reciprocal link from {this_path.name}.")
        write(this_path, this_text)
        write(other_path, other_text)
        log_event(this_path, "ref", args, {"field": this_field, "other": this_val, "type": rtype})
        log_event(other_path, "ref", args, {"field": other_field, "other": other_val, "type": rtype})
        print(f"ref: {this_path.name} [{this_field}] <-> {other_path.name} [{other_field}]")
        self_validate(this_path, this_text)
        self_validate(other_path, other_text)
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
    for field, default in (("id", ""), ("owner", ""), ("kind", "plan"),
                           ("status", "draft"), ("schema", str(MIN_SCHEMA)),
                           ("provides", "—"), ("consumes", "—")):
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
<title>cozyplan — Plan Index</title>
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
            "kind": meta.get("kind", "") or "plan",
            "title": extract_title(text),
            "status": meta.get("status", ""),
            "owner": meta.get("owner", ""),
            "created": meta.get("created", ""),
            "modified": (split_list(meta.get("modified", "")) or [""])[-1],
            "image_dir": hp.stem + "/" if (specs / hp.stem).is_dir() else "",
            "back_refs": split_list(meta.get("back-refs", "")),
            "forward_refs": split_list(meta.get("forward-refs", "")),
            "provides": split_list(meta.get("provides", "")),
            "consumes": split_list(meta.get("consumes", "")),
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

    Extracts `role`, `reports_to`, `github`, the architect-only `mode`/`acceptance`,
    and the nested `owns.{source_of_truth,code,supporting}` lists — the fields
    `roles build` needs. Tolerates the richer nested blocks (definition_of_done,
    report_back) by ignoring them.
    """
    m = re.match(r"^﻿?---\s*\n(.*?)\n---\s*\n?", md_text, re.S)
    if not m:
        return None
    lines = m.group(1).split("\n")
    out = {"role": None, "reports_to": None, "github": None,
           "mode": None, "acceptance": None,
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
        for key in ("github", "mode", "acceptance"):
            mk = re.match(rf"^{key}:\s*(.+)$", ln)
            if mk:
                out[key] = _unquote(mk.group(1))

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


def check_disjoint(role_globs: dict[str, list[str]]) -> list[tuple[str, str, str, str]]:
    """Return (role1, glob1, role2, glob2) pairs that could own a common path.

    Uses `glob_overlap` — the exact same matcher the guard enforces with — so a
    role set that builds clean here cannot surprise the guard at enforce time.
    """
    flat = [(role, g) for role, globs in role_globs.items() for g in globs]
    conflicts = []
    for i in range(len(flat)):
        for j in range(i + 1, len(flat)):
            r1, g1 = flat[i]
            r2, g2 = flat[j]
            if r1 == r2:
                continue
            if glob_overlap(g1, g2):
                conflicts.append((r1, g1, r2, g2))
    return conflicts


def _glob_to_codeowners(g: str) -> str:
    g = g.replace("\\", "/")
    if g.endswith("/**"):
        return g[:-3] + "/"
    return g.replace("/**/", "/").replace("**", "*")


def render_codeowners(roles_out: dict) -> tuple[str, list[str]]:
    """Render CODEOWNERS from the role manifest, plus a list of unmapped roles.

    A role with a `github` identity gets live ownership lines. A role WITHOUT one
    is emitted commented-out (never a bare `@<role-slug>`, which GitHub cannot
    resolve) with a trailing note, and its slug is returned so the caller warns.
    """
    lines = [
        "# GENERATED by plan_tool roles build - do not hand-edit. Source: roles/*.md",
        "",
    ]
    unmapped = []
    for role, info in roles_out.items():
        gh = info.get("github")
        lines.append(f"# {role}")
        if gh:
            for g in info["owns"]:
                lines.append(f"{_glob_to_codeowners(g)}  {gh}")
        else:
            unmapped.append(role)
            for g in info["owns"]:
                lines.append(f"# {_glob_to_codeowners(g)}  # no github identity mapped for role {role}")
        lines.append("")
    return "\n".join(lines) + "\n", unmapped


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

    # Disjointness on source_of_truth + code (unchanged scope), using the SAME
    # glob semantics the guard enforces (glob_overlap). `supporting` may overlap
    # freely — it drives logging/attribution only, never a guard deny.
    sot_code = {r: (d["owns"].get("source_of_truth", []) + d["owns"].get("code", []))
                for r, d in parsed.items()}
    conflicts = check_disjoint(sot_code)
    if conflicts:
        print("FAIL roles build: overlapping source_of_truth/code globs across roles:")
        for r1, g1, r2, g2 in conflicts:
            print(f"  - {r1} {g1!r} overlaps {r2} {g2!r}")
        return 1

    # roles is a pure ownership-map generator: it compiles roles/*.md into an
    # ownership manifest + CODEOWNERS for PR-review routing. It does NOT enforce
    # anything at edit time — git/PR review + CODEOWNERS carry that. (Enforcement
    # modes / acceptance queues were removed in the coherence-over-compliance rework.)
    roles_out = {}
    for r, d in parsed.items():
        owns = d["owns"]
        sot = list(dict.fromkeys(owns.get("source_of_truth", [])))
        code = list(dict.fromkeys(owns.get("code", [])))
        supporting = list(dict.fromkeys(owns.get("supporting", [])))
        roles_out[r] = {
            "source_of_truth": sot,
            "code": code,
            "supporting": supporting,
            "owns": list(dict.fromkeys(sot + code + supporting)),  # CODEOWNERS union
            "reports_to": d.get("reports_to"),
            "github": d.get("github"),
        }

    manifest = {"roles": roles_out}
    (roles_dir / "_roles.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    gh = Path(args.codeowners) if args.codeowners else Path(".github") / "CODEOWNERS"
    gh.parent.mkdir(parents=True, exist_ok=True)
    co_text, unmapped = render_codeowners(roles_out)
    gh.write_text(co_text, encoding="utf-8")

    print(f"roles build: {len(roles_out)} role(s) "
          f"-> {roles_dir}/_roles.json, {gh}")
    for r, info in roles_out.items():
        print(f"  {r}: {len(info['owns'])} owned glob(s)")
    for r in unmapped:
        print(f"  warn: no github identity mapped for role {r!r}; its CODEOWNERS lines "
              f"are commented out (add `github: \"@org/team\"` to roles/{r}.md)")
    return 0


# ── new (deterministic plan scaffolding from templates/plan.html) ─────────────
def template_candidates() -> list[Path]:
    """Ordered locations to look for templates/plan.html.

    Mirrors how the hooks resolve plan_tool.py: prefer CLAUDE_PLUGIN_ROOT (the
    bundled plugin), then the project cwd, then this script's own location — each
    with the in-project `.claude/skills/...` layout and the moved-as-a-unit layout.
    """
    rels = [
        Path(".claude") / "skills" / "cozyplan" / "templates" / "plan.html",
        Path("skills") / "cozyplan" / "templates" / "plan.html",
        Path("templates") / "plan.html",
    ]
    roots: list[Path] = []
    pr = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if pr:
        roots.append(Path(pr))
    roots.append(Path.cwd())
    roots.append(Path(__file__).resolve().parent.parent)  # <skill>/scripts/ -> <skill>/ (templates/ sits beside scripts/)
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
        "PLAN_KIND": esc(getattr(args, "kind", None) or "plan"),
        "OWNER_ROLE": esc(args.owner or ""),
        "CREATED_ISO": esc(created),
        "MODIFIED_ISO_LIST": esc(created),
        "COMMIT_SHA_LIST": "—",
        "AGENT_NAME_LIST": esc(args.agent) if args.agent else "—",
        "SESSION_ID_LIST": esc(args.session) if args.session else "—",
        "BACK_REFERENCES": "—",
        "FORWARD_REFERENCES": "—",
        "PROVIDES_LIST": "—",
        "CONSUMES_LIST": "—",
        "PHASE_NUMBER": "1",
        "TASK_NUMBER": "1",
        "LAST_TASK_NUMBER": "2",
        "CHECK_NUMBER": "1",
    }


def cmd_new(args) -> int:
    name = args.name
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
        return fail(f"plan name must be kebab-case (lowercase letters, digits, hyphens): {name!r}")
    if getattr(args, "kind", "plan") not in KIND_VOCAB:
        return fail(f"kind must be one of {sorted(KIND_VOCAB)}")
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
              {"id": name, "title": args.title, "owner": args.owner or "",
               "kind": getattr(args, "kind", None) or "plan", "file": path.name})
    print(f"new: created {path} (id={name}, kind={getattr(args, 'kind', None) or 'plan'}, "
          f"status=draft) from {tmpl}")
    self_validate(path, text)
    return 0


# ── brief (compact plain-text extract; cuts build/bootstrap read cost) ────────
def _read_events(plan_path: Path) -> list[dict]:
    sc = sidecar_path(plan_path)
    if not sc.exists():
        return []
    out = []
    for line in read(sc).splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _brief_one_line(p: dict) -> str:
    kind = p.get("kind", "plan") or "plan"
    owner = p.get("owner", "") or "-"
    status = p.get("status", "") or "-"
    return f"{p['file']:<32} [{kind}] {status:<10} {owner:<16} {html.unescape(p.get('title', ''))}"


def cmd_brief(args) -> int:
    if getattr(args, "all", False):
        specs = Path(args.specs)
        idx = specs / "_index.json"
        if not idx.exists():
            return fail(f"no _index.json in {specs}; run: plan_tool index --specs {specs}")
        plans = json.loads(read(idx)).get("plans", [])
        for p in sorted(plans, key=lambda x: x["file"]):
            print(_brief_one_line(p))
        return 0

    if not args.plan:
        return fail("brief requires a plan path (or --all --specs <dir>)")
    path = Path(args.plan)
    if not path.exists():
        return fail(f"plan not found: {path}")
    text = read(path)
    meta = parse_meta(text)
    events = _read_events(path)

    # latest failure/wip reason per status id, from status events
    reasons = {}
    for e in events:
        if e.get("event") == "status":
            d = e.get("details", {}) or {}
            if d.get("reason"):
                reasons[d.get("id")] = d["reason"]

    lines = [f"# {html.unescape(extract_title(text)) or path.stem}  ({path.name})"]
    lines.append("")
    for f in ("id", "kind", "owner", "status", "schema"):
        lines.append(f"{f:<10}: {meta.get(f, '') or '-'}")
    for f, label in (("back-refs", "back"), ("forward-refs", "forward"),
                     ("provides", "provides"), ("consumes", "consumes")):
        vals = split_list(meta.get(f, ""))
        if vals:
            lines.append(f"{label:<10}: {', '.join(vals)}")

    lines.append("")
    lines.append("Phases / tasks:")
    open_items = []
    for m in re.finditer(
            r'data-status-for="([^"]+)"[^>]*>(\[[^\]]*\])</code>(.*?)(?:</li>|</h3>|</h4>)',
            text, re.S):
        sid, mark, tail = m.group(1), m.group(2), html.unescape(strip_tags(m.group(3)).strip())
        lines.append(f"  {mark:<6} {sid:<10} {tail}")
        if mark in ("[wip]", "[f]"):
            r = reasons.get(sid)
            open_items.append(f"  {mark} {sid} {tail}" + (f"  — {r}" if r else ""))

    if open_items:
        lines.append("")
        lines.append("Open items:")
        lines.extend(open_items)

    lines.append("")
    lines.append("Recent events:")
    for e in events[-5:]:
        d = e.get("details", {}) or {}
        summary = d.get("summary") or d.get("field") or d.get("id") or d.get("label") or ""
        lines.append(f"  {e.get('ts', '')[:19]}  {e.get('event', ''):<11} "
                     f"{e.get('role') or '-':<14} {summary}")

    print("\n".join(lines))
    return 0


# ── hooks (register/unregister the coherence hooks in settings.json) ──────────
# Bare-skill installs (npx skills add) carry the hook scripts but nothing
# registers them — this command closes that gap. Keyed by script filename so
# re-running re-points a stale path instead of duplicating the entry.
HOOK_MATCHERS = {
    "guard_plan_edit.py": ("PreToolUse", "Edit|MultiEdit|Write"),
    "lint_plan.py": ("PostToolUse", "Edit|MultiEdit|Write|Bash"),
}


def cmd_hooks(args) -> int:
    hook_dir = Path(__file__).resolve().parent / "hooks"
    if args.settings:
        settings_path = Path(args.settings)
    elif args.global_:
        settings_path = Path.home() / ".claude" / "settings.json"
    else:
        settings_path = Path(".claude") / "settings.json"

    if args.hooks_cmd == "install":
        missing = [n for n in HOOK_MATCHERS if not (hook_dir / n).exists()]
        if missing:
            return fail(f"hook script(s) not found beside plan_tool: {', '.join(missing)}")

    data = {}
    if settings_path.exists():
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            return fail(f"cannot parse {settings_path}: {e}")
        if not isinstance(data, dict):
            return fail(f"{settings_path} is not a JSON object")

    hooks = data.setdefault("hooks", {})
    changed = []
    for script, (event, matcher) in HOOK_MATCHERS.items():
        entries = hooks.setdefault(event, [])
        before = len(entries)
        entries[:] = [
            blk for blk in entries
            if not any(script in (h.get("command") or "")
                       for h in (blk.get("hooks") or []) if isinstance(h, dict))
        ]
        removed = before - len(entries)
        if args.hooks_cmd == "install":
            cmd_str = f'uv run "{(hook_dir / script).as_posix()}"'
            entries.append({"matcher": matcher,
                            "hooks": [{"type": "command", "command": cmd_str}]})
            changed.append(f"{event}: {script} registered" + (" (re-pointed)" if removed else ""))
        elif removed:
            changed.append(f"{event}: {script} removed")
        if not entries:
            hooks.pop(event, None)
    if not data.get("hooks"):
        data.pop("hooks", None)

    if not changed:
        print(f"hooks: nothing to do in {settings_path}")
        return 0
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    for c in changed:
        print(f"hooks: {c}")
    print(f"hooks: wrote {settings_path} — restart Claude Code (or reload settings) to take effect")
    return 0


# ── argparse wiring ───────────────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("--role", help="acting role label for the event log (free-form)")
    parent.add_argument("--agent", help="acting agent name for the event log")
    parent.add_argument("--session", help="acting session id for the event log")

    p = argparse.ArgumentParser(prog="plan_tool", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("new", parents=[parent], help="scaffold a fresh plan from templates/plan.html")
    sp.add_argument("name", help="kebab-case plan name (also the immutable id and filename stem)")
    sp.add_argument("--title", required=True, help="human-readable plan title")
    sp.add_argument("--owner", help="owning role (metadata owner field); empty if omitted")
    sp.add_argument("--kind", choices=sorted(KIND_VOCAB), default="plan",
                    help="artifact kind (currently only 'plan')")
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

    sp = sub.add_parser("amend", parents=[parent], help="append an amendment entry")
    sp.add_argument("plan")
    sp.add_argument("--summary", required=True)
    sp.add_argument("--detail", required=True)
    sp.add_argument("--iso", help="override the timestamp")
    sp.set_defaults(func=cmd_amend)

    sp = sub.add_parser("ref", parents=[parent], help="add a bidirectional reference between two plans")
    sp.add_argument("--this", required=True)
    sp.add_argument("--other", required=True)
    sp.add_argument("--dir", choices=["back", "forward"],
                    help="legacy: back|forward reference direction (kept for compatibility)")
    sp.add_argument("--type", choices=["back", "forward"],
                    help="reference type: back|forward (a link between two plans)")
    sp.set_defaults(func=cmd_ref)

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

    sp = sub.add_parser("hooks", parents=[parent],
                        help="register/unregister the coherence hooks in .claude/settings.json (for bare-skill installs)")
    sp.add_argument("hooks_cmd", choices=["install", "remove"], help="install or remove the two hook entries")
    sp.add_argument("--settings", default=None,
                    help="explicit settings.json path (default: ./.claude/settings.json)")
    sp.add_argument("--global", dest="global_", action="store_true",
                    help="target ~/.claude/settings.json instead of the project settings")
    sp.set_defaults(func=cmd_hooks)

    sp = sub.add_parser("brief", parents=[parent],
                        help="compact plain-text extract of a plan (or --all for a one-liner index)")
    sp.add_argument("plan", nargs="?", help="plan path (omit with --all)")
    sp.add_argument("--all", action="store_true", help="one line per plan from _index.json")
    sp.add_argument("--specs", default="specs", help="specs directory (for --all; default: specs)")
    sp.set_defaults(func=cmd_brief)

    return p




def _make_stdio_utf8_safe() -> None:
    """Plan text carries em-dashes / arrows / entities; a cp1252 console (Windows
    default) raises UnicodeEncodeError on print. Re-encode stdout/stderr as UTF-8,
    replacing anything unmappable rather than crashing. No-op where unsupported."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            with contextlib.suppress(Exception):
                reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    _make_stdio_utf8_safe()
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
