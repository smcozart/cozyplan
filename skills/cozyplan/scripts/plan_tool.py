#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""cozyplan plan_tool — deterministic writes, validation, and indexing for specs/*.html plans.

Every structured mutation of a living plan artifact goes through this tool instead of
free-form edits, so status markers, append-only metadata, references, and amendments stay
well-formed. Locating regions relies on machine-readable data-* anchors baked into the
plan template (see .claude/skills/cozyplan/SKILL.md). Stdlib only, and 3.9 is the
floor the tests run on: `uv run` and a plain `python3` both work, and neither is
required by the other (ADR-0004).

Commands (`--help` is authoritative; this list is the map, not the contract):
  new        scaffold a fresh plan from templates/plan.html
  status     flip a task/phase status marker
  meta       set or append a metadata field
  ref        add a bidirectional back/forward reference between two plans
  amend      append an amendment entry
  validate   lint a plan (leftover tokens, markers, metadata, images, refs)
  index      scan specs/ -> _index.json + _index.html, flag dangling refs + doc drift
  init-ids   assign data-* anchors to a plan that lacks them (additive, reviewable)
  brief      compact plain-text extract of a plan (or --all for a one-liner index)
  phase      print one phase in full — its tasks, actions, and Testing Strategy
  next       print the first status id that is not [x]/[f] (or 'done')
  addphase   append a correctly-numbered phase block (structure, not content)
  init       wire a repo for cozyplan (idempotent; implements doctor's check list)
  doctor     report what is actually wired in this clone (ADR-0004)
  state      add/render/show/check/migrate the state layer (ADR-0005)
  issue      file a work item, queueing it when gh is away (ADR-0001)
  trailers   add the commit trailers this commit can demonstrate (ADR-0007)
  hooks      install/remove the Claude Code hooks and the tracked .githooks;
             `hooks selftest` proves they actually run here (ADR-0010)

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
import shlex
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

# ── vocab / field classification ──────────────────────────────────────────────
STATUS_MARKERS = {"idle": "[]", "wip": "[wip]", "x": "[x]", "f": "[f]"}
VALID_MARKERS = set(STATUS_MARKERS.values())
# Terminal = resolved for good: done, or deliberately abandoned with a recorded reason.
# `next` skips these and `meta --field status --value built` refuses while any remain.
TERMINAL_MARKERS = {"[x]", "[f]"}
STATUS_VOCAB = {"draft", "active", "built", "superseded", "archived"}
LIST_FIELDS = {"modified", "commits", "agent", "session", "back-refs", "forward-refs",
               "provides", "consumes", "issues"}
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


def under(root: Path, value) -> Path:
    """A path flag is relative to --root, never to the working directory.

    `--root` is how another repository reaches this tool from somewhere else: a
    site records a claim into a workspace ledger that way. When a sibling flag
    kept its own cwd-relative default, `--root` was accepted and not honoured,
    and neither half failed. The read half reported an empty ledger -- 0 claims
    against a log holding 65 -- and the write half wrote into the wrong one.

    An absolute value is left alone, so every caller that already passes a full
    path is unaffected. `cmd_hooks_git` and `cmd_init` computed `root / rel`
    inline and were always correct; this is the same rule, named once.
    """
    p = Path(value)
    return p if p.is_absolute() else root / p


# ── plan write lock (exclusive, sibling <plan>.lock; Windows-safe) ────────────
LOCK_STALE_SECONDS = 60
LOCK_ACQUIRE_SECONDS = 15.0


class PlanLockBusy(RuntimeError):
    """A plan's write lock stayed held past the acquire deadline; nothing was written."""


class _PlanLock:
    """Exclusive advisory lock for a plan's read-modify-write cycle.

    Created via O_CREAT|O_EXCL (atomic on Windows too). Retries for
    LOCK_ACQUIRE_SECONDS, then fails *closed* by raising PlanLockBusy — proceeding
    anyway would permit exactly the lost update the lock exists to prevent. A lock
    older than LOCK_STALE_SECONDS is a crashed writer rather than a live one: it is
    broken, recorded as an event in the plan's sidecar, and retried. Always released
    in __exit__.
    """

    def __init__(self, target: Path):
        self.target = Path(target)
        self.path = self.target.with_suffix(".lock")
        self.acquired = False

    def acquire(self) -> None:
        import time
        deadline = time.monotonic() + LOCK_ACQUIRE_SECONDS
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
                    # Recorded so a broken lock stays visible after the fact, not just
                    # in a stderr line nobody kept.
                    with contextlib.suppress(OSError):
                        log_event(self.target, "lock-stale-break", None,
                                  {"lock": self.path.name, "age_seconds": int(age)})
                    continue
                if time.monotonic() >= deadline:
                    raise PlanLockBusy(
                        f"{self.path.name} is held by another plan_tool process "
                        f"(waited {LOCK_ACQUIRE_SECONDS:g}s); nothing was written — retry in a "
                        f"moment. If no other process is running, delete {self.path}.")
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


# ── plan structure queries (one matcher per anchor, shared by every consumer) ─
_STATUS_ANCHOR_RE = re.compile(r'data-status-for="([^"]+)"[^>]*>(\[[^\]]*\])')
_PHASE_DIV_RE = re.compile(r'<div\b[^>]*\bclass="phase"[^>]*>')


def iter_status_markers(text: str) -> list[tuple[str, str]]:
    """(id, marker) for every data-status-for anchor, in document order."""
    return [(m.group(1), m.group(2)) for m in _STATUS_ANCHOR_RE.finditer(text)]


def phase_numbers(text: str) -> list[str]:
    """data-phase values of every .phase div, in document order."""
    out = []
    for m in _PHASE_DIV_RE.finditer(text):
        dm = re.search(r'\bdata-phase="([^"]+)"', m.group(0))
        if dm:
            out.append(dm.group(1))
    return out


def phase_segment(text: str, pnum: str) -> str | None:
    """Raw HTML of the phase whose data-phase == pnum, up to the next .phase div.

    The trailing phase has no successor to bound it, so it ends at the </section>
    that closes the implementation-phases container.
    """
    phases = list(_PHASE_DIV_RE.finditer(text))
    for i, m in enumerate(phases):
        dm = re.search(r'\bdata-phase="([^"]+)"', m.group(0))
        if not dm or dm.group(1) != pnum:
            continue
        start = m.start()
        if i + 1 < len(phases):
            return text[start:phases[i + 1].start()]
        close = text.find("</section>", start)
        return text[start:close if close != -1 else len(text)]
    return None


def _fmt_ids(ids: list[str], limit: int = 12) -> str:
    """Comma-joined id list, truncated with a remainder count so errors stay readable."""
    shown = ", ".join(ids[:limit])
    return shown + (f", ... (+{len(ids) - limit} more)" if len(ids) > limit else "")


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

    # Structural integrity of the hand-duplicated phase/task ids. These are errors,
    # not warnings: each one breaks machine addressing — a duplicate id makes
    # `status --id` ambiguous (it now refuses), and a data-task/data-status-for
    # mismatch means the CLI flips a different box than the checklist item claims.
    markers = iter_status_markers(text)
    ids = [sid for sid, _ in markers]
    dupes = sorted({s for s in ids if ids.count(s) > 1})
    if dupes:
        problems.append(f"duplicate data-status-for id(s): {_fmt_ids(dupes)} — status ids must "
                        f"be unique (use `plan_tool addphase` instead of copying a phase block)")

    for m in re.finditer(r'<li\b[^>]*\bdata-task="([^"]+)"[^>]*>(.*?)</li>', text, re.S):
        tid = m.group(1)
        sm = re.search(r'data-status-for="([^"]+)"', m.group(2))
        if sm and sm.group(1) != tid:
            problems.append(f'task data-task="{tid}" carries data-status-for="{sm.group(1)}" '
                            f"— the two ids on a checklist item must match")

    pnums = phase_numbers(text)
    dupe_phases = sorted({p for p in pnums if pnums.count(p) > 1})
    if dupe_phases:
        problems.append(f"duplicate data-phase value(s): {', '.join(dupe_phases)} — "
                        f"`plan_tool phase --id` cannot address them unambiguously")
    # Numbering gaps are cosmetic by comparison: every id still addresses exactly one
    # thing, the sequence just reads wrong. Warning, in line with the other
    # "correct but suspicious" findings above.
    if pnums and all(p.isdigit() for p in pnums) and \
            [int(p) for p in pnums] != list(range(1, len(pnums) + 1)):
        warns.append(f"phase numbering is not a gapless 1..{len(pnums)} sequence "
                     f"(found {', '.join(pnums)})")

    # Early notice of the `built` gate (cmd_meta refuses that transition while any
    # marker is un-terminal). Suppressed while draft, where nothing is built yet by
    # definition and the notice would be pure noise on every write.
    if status != "draft":
        open_ids = [sid for sid, mark in markers if mark not in TERMINAL_MARKERS]
        if open_ids:
            warns.append(f"{len(open_ids)} status marker(s) still open (not [x]/[f]): "
                         f"{_fmt_ids(open_ids)} — status=built is refused until they are terminal")

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


# `modified` is stamped on every CLI write, so an unbounded list buries the header a
# reader opens first — a 40-task build produced 40+ timestamps. Keep the newest
# MODIFIED_KEEP stamps and elide the rest into a single trailing `(+N earlier)`
# marker whose count stays exact across repeated compactions. The marker is a
# distinct list entry, so `split_list` still yields clean timestamps around it and
# `latest_modified` (the one consumer that wants a date) skips over it.
MODIFIED_KEEP = 5
_ELIDED_RE = re.compile(r"^\(\+(\d+) earlier\)$")


def compact_modified(entries: list[str], keep: int = MODIFIED_KEEP) -> list[str]:
    elided = 0
    kept: list[str] = []
    for e in entries:
        m = _ELIDED_RE.match(e)
        if m:
            elided += int(m.group(1))  # absorb the marker left by an earlier compaction
        else:
            kept.append(e)
    if len(kept) > keep:
        elided += len(kept) - keep
        kept = kept[-keep:]
    return kept + ([f"(+{elided} earlier)"] if elided else [])


def latest_modified(meta: dict) -> str:
    """Newest real timestamp in a (possibly compacted) `modified` list."""
    for v in reversed(split_list(meta.get("modified", ""))):
        if not _ELIDED_RE.match(v):
            return v
    return ""


def _set_modified(text: str, iso: str) -> tuple[str, int]:
    cur = get_meta_raw(text, "modified")
    if cur is None:
        return text, 0
    entries = split_list(cur)
    if iso in entries:
        return text, 1  # already stamped this second — no-op, but still "found"
    entries.append(esc(iso))
    return set_meta(text, "modified", ", ".join(compact_modified(entries)))


def stamp_modified(text: str, iso: str) -> str:
    new, n = _set_modified(text, iso)
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
        new, n = pat.subn(lambda m: m.group(1) + marker, text)
        if n == 0:
            return fail(f"no status anchor data-status-for={args.id!r} found (run init-ids?)")
        # Flipping only the first of several same-id anchors silently reports success
        # while leaving the others stale, so refuse instead of guessing which was meant.
        if n > 1:
            return fail(f"status anchor data-status-for={args.id!r} appears {n} times in "
                        f"{path.name}; ids must be unique — fix the duplicates "
                        f"(run: plan_tool validate {path}) before flipping it")
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
        elif args.field == "modified":
            new, n = _set_modified(text, args.value)  # compacts like an automatic stamp
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
        # `built` is the one status that asserts the work is finished, so it gates on
        # the status markers themselves rather than on prose. --force is the deliberate
        # override for recording a knowingly incomplete build.
        if args.field == "status" and args.value == "built" and not args.force:
            open_ids = [sid for sid, mark in iter_status_markers(new)
                        if mark not in TERMINAL_MARKERS]
            if open_ids:
                return fail(
                    f"cannot move {path.name} to status='built': {len(open_ids)} status "
                    f"marker(s) are not [x] or [f]: {_fmt_ids(open_ids)}. Resolve each via "
                    f"`plan_tool status {path} --id <id> --state x|f`, or pass --force to "
                    f"record the build as deliberately incomplete.")
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


# ── addphase (the tool owns phase structure; the model owns phase content) ────
# Kept in step with the one example phase in templates/plan.html, but with the three
# coupled structural attributes (data-phase / data-task / data-status-for) stamped
# here instead of hand-renumbered by whoever copies a block. Content stays as {{}}
# slots for the authoring agent — same contract as `new`.
PHASE_TASK_BLOCK = """\
      <h4>{{TASK_NUMBER}}. {{TASK_NAME}}</h4>
      <ul class="checklist">
        <li data-task="{{PHASE_NUMBER}}.{{TASK_NUMBER}}"><code class="status" data-status-for="{{PHASE_NUMBER}}.{{TASK_NUMBER}}">[]</code> {{SPECIFIC_ACTION}}</li>
      </ul>"""

PHASE_BLOCK = """\
    <div class="phase" data-phase="{{PHASE_NUMBER}}">
      <h3><code class="status" data-status-for="phase-{{PHASE_NUMBER}}">[]</code> Phase {{PHASE_NUMBER}}: {{PHASE_NAME}}</h3>
      <p>{{PHASE_DESCRIPTION}}</p>

      <!-- Optional focused image for this phase, synced to :root identity -->
      <figure>
        <!-- {{PHASE_IMAGE: subject describing this phase's architecture/flow}} -->
        <figcaption>{{PHASE_IMAGE_CAPTION}}</figcaption>
      </figure>

{{TASK_BLOCKS}}

      <!-- Final task of every phase: Testing Strategy + validation loop -->
      <h4>{{LAST_TASK_NUMBER}}. Testing Strategy</h4>
      <p>{{TESTING_APPROACH: technology used to test/validate, including edge cases}}</p>
      <ul class="checklist">
        <li data-task="{{PHASE_NUMBER}}.{{LAST_TASK_NUMBER}}"><code class="status" data-status-for="{{PHASE_NUMBER}}.{{LAST_TASK_NUMBER}}">[]</code> <code>{{VALIDATION_COMMAND}}</code> — {{WHAT_IT_PROVES}}</li>
      </ul>
      <div class="loop">
        🔁 <strong>Do not exit this phase until every box above is <code>[x]</code> or <code>[f]</code>.</strong>
        If a command fails, fix the cause and re-run; loop until it passes. <code>[f]</code> is terminal — only when a box genuinely cannot be made to pass, mark it <code>[f]</code> (with a one-line reason via <code>PLAN_TOOL status … --state f --reason "…"</code>) and move on.
      </div>
    </div>"""


def render_phase_block(pnum: int, tasks: int, title: str | None, nl: str) -> str:
    """Structural HTML for one phase: `tasks` work tasks plus a Testing Strategy task."""
    blocks = [PHASE_TASK_BLOCK.replace("{{TASK_NUMBER}}", str(t)) for t in range(1, tasks + 1)]
    out = PHASE_BLOCK.replace("{{TASK_BLOCKS}}", "\n\n".join(blocks))
    out = out.replace("{{LAST_TASK_NUMBER}}", str(tasks + 1))
    out = out.replace("{{PHASE_NUMBER}}", str(pnum))
    if title:
        out = out.replace("{{PHASE_NAME}}", esc(title))
    return out.replace("\n", nl)


def _phases_insert_at(text: str) -> int | None:
    """Index of the </section> closing the implementation-phases container."""
    m = re.search(r'<section\b[^>]*\bid="phases"[^>]*>', text)
    if not m:
        return None
    close = text.find("</section>", m.end())
    return close if close != -1 else None


def cmd_addphase(args) -> int:
    path = Path(args.plan)
    if not path.exists():
        return fail(f"plan not found: {path}")
    if args.tasks < 1:
        return fail("--tasks must be >= 1 (the Testing Strategy task is appended on top of it)")
    with _PlanLock(path):
        text = read(path)
        if not _require_anchored(path, text):
            return 1
        if not schema_ok(path, text):
            return 1
        at = _phases_insert_at(text)
        if at is None:
            return fail('no <section id="phases"> ... </section> container to append into '
                        '(is this a plan scaffolded from templates/plan.html?)')
        nums = [int(p) for p in phase_numbers(text) if p.isdigit()]
        pnum = max(nums) + 1 if nums else 1
        if f'data-status-for="phase-{pnum}"' in text:
            return fail(f"phase-{pnum} already exists in {path.name}; fix the phase numbering "
                        f"(run: plan_tool validate {path}) before appending")
        nl = detect_nl(text)
        block = render_phase_block(pnum, args.tasks, args.title, nl)
        text = text[:at].rstrip() + nl + block + nl + "  " + text[at:]
        text = stamp_modified(text, now_iso())
        write(path, text)
        log_event(path, "addphase", args,
                  {"phase": pnum, "tasks": args.tasks, "title": args.title or ""})
    print(f"addphase: phase-{pnum} appended to {path.name} "
          f"({args.tasks} task(s) {pnum}.1-{pnum}.{args.tasks}, "
          f"Testing Strategy {pnum}.{args.tasks + 1})")
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
                           ("provides", "—"), ("consumes", "—"), ("issues", "—")):
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


def render_index_html(plans: list[dict], dangling: list, as_of: str = "",
                      unprovided: list = ()) -> str:
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
    if unprovided:
        # The half worth flagging (ADR-0003): a dead edge wastes a lookup, a missing
        # one makes "nothing depends on this" read as confident and true.
        items = "".join(f"<li>{esc(f)} consumes → <code>{esc(c)}</code></li>" for f, c in unprovided)
        danger += (f'<div class="danger"><strong>Consumed but provided by nothing:</strong>'
                   f'<ul>{items}</ul>'
                   f'<p>Mark it <code>external:&lt;contract&gt;</code> if it is owned outside this repo.</p></div>')
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
    specs = under(Path(args.root), args.specs)
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
            "modified": latest_modified(meta),
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

    # Unprovided consumption: a contract some plan consumes that no plan provides.
    # A dead edge only wastes a lookup; a MISSING edge makes an impact answer read
    # "nothing depends on this" with confidence, so this is the half worth flagging.
    # `external:` marks a contract owned outside the repo, which nothing here provides.
    provided = {c for p in plans for c in p["provides"] if c and c != "\u2014"}
    unprovided = []
    for p in plans:
        for c in p["consumes"]:
            c = c.strip()
            if not c or c == "\u2014" or c.startswith("external:"):
                continue
            if c not in provided:
                unprovided.append((p["file"], c))

    # Deterministic output: stamp with the newest content timestamp, not the run
    # time, so re-running index on unchanged inputs produces a byte-identical file.
    as_of = max((p["modified"] or p["created"] for p in plans), default="")
    (specs / "_index.json").write_text(
        json.dumps({"as_of": as_of, "plans": plans, "dangling": dangling,
                    "unprovided": unprovided},
                   indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (specs / "_index.html").write_text(
        render_index_html(plans, dangling, as_of, unprovided), encoding="utf-8")

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
    # A contract consumed but provided by nothing was computed into _index.json and
    # then never surfaced: the command printed a clean bill of health while the gap
    # sat in the file. ADR-0003 names that exact failure — a confident "nothing
    # depends on this" is worse than no answer at all.
    if unprovided:
        print(f"  consumed but provided by nothing ({len(unprovided)}):")
        for f, c in unprovided:
            print(f"    {f} consumes -> {c}")
        print("    (mark it `external:<contract>` if it is owned outside this repo)")
    if not dangling and not drift and not unprovided:
        print("  clean: no dangling refs, no unprovided contracts, no doc drift")
    return 0


# ── new (deterministic plan scaffolding from templates/plan.html) ─────────────
def template_candidates(name: str = "plan.html", skill: str = "cozyplan") -> list[Path]:
    """Ordered locations to look for a named template.

    Mirrors how the hooks resolve plan_tool.py: prefer CLAUDE_PLUGIN_ROOT (the
    bundled plugin), then the project cwd, then this script's own location — each
    with the in-project `.claude/skills/...` layout and the moved-as-a-unit layout.
    """
    rels = [
        Path(".claude") / "skills" / skill / "templates" / name,
        Path("skills") / skill / "templates" / name,
        Path(skill) / "templates" / name,   # from a <skills>/ root, for a sibling skill
        Path("templates") / name,
    ]
    roots: list[Path] = []
    pr = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if pr:
        roots.append(Path(pr))
    roots.append(Path.cwd())
    roots.append(Path(__file__).resolve().parent.parent)  # <skill>/scripts/ -> <skill>/ (templates/ sits beside scripts/)
    roots.append(Path(__file__).resolve().parent.parent.parent)  # -> <skills>/, for a sibling skill
    seen: list[Path] = []
    for root in roots:
        for rel in rels:
            c = root / rel
            if c not in seen:
                seen.append(c)
    return seen


def resolve_template(name: str = "plan.html", skill: str = "cozyplan") -> Path | None:
    for c in template_candidates(name, skill):
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


# ── phase / next (the other half of two-tier recall: brief indexes, phase reads) ─
# `brief` is the cheap whole-plan index; `phase` is the expensive-but-scoped read of
# exactly the block being built, so a build agent never re-reads the whole HTML.
_PHASE_TEXT_RE = re.compile(r"<(?P<tag>h3|h4|p|li)\b[^>]*>(?P<body>.*?)</(?P=tag)>", re.S)
_STATUS_CODE_RE = re.compile(r'<code\b[^>]*\bclass="status"[^>]*>(\[[^\]]*\])</code>', re.S)


def _plain(body: str) -> str:
    """Readable one-line text for an element body, minus its status marker."""
    return re.sub(r"\s+", " ", html.unescape(strip_tags(_STATUS_CODE_RE.sub("", body)))).strip()


def cmd_phase(args) -> int:
    path = Path(args.plan)
    if not path.exists():
        return fail(f"plan not found: {path}")
    m = re.fullmatch(r"(?:phase-)?(\d+)", str(args.id).strip())
    if not m:
        return fail(f"--id must be 'phase-<n>' or a bare '<n>' (got {args.id!r})")
    pnum = m.group(1)
    text = read(path)
    seg = phase_segment(text, pnum)
    if seg is None:
        known = ", ".join(phase_numbers(text)) or "none"
        return fail(f'no phase with data-phase="{pnum}" in {path.name} '
                    f"(phases present: {known})")

    title = html.unescape(extract_title(text)) or path.stem
    lines = [f"# {title} — phase {pnum}  ({path.name})", ""]
    for b in _PHASE_TEXT_RE.finditer(seg):
        tag, body = b.group("tag"), b.group("body")
        sm = _STATUS_CODE_RE.search(body)
        mark = sm.group(1) if sm else ""
        am = re.search(r'data-status-for="([^"]+)"', sm.group(0)) if sm else None
        sid = am.group(1) if am else ""
        txt = _plain(body)
        if tag == "h3":
            lines.append(f"{mark:<6} {sid:<10} {txt}")
        elif tag == "h4":
            lines.append("")
            lines.append(txt)
        elif tag == "li":
            lines.append(f"  {mark:<6} {sid:<10} {txt}")
        elif txt:  # <p>: phase description / testing approach
            lines.append(f"  {txt}")
    print("\n".join(lines))
    return 0


def cmd_next(args) -> int:
    path = Path(args.plan)
    if not path.exists():
        return fail(f"plan not found: {path}")
    for sid, mark in iter_status_markers(read(path)):
        if mark not in TERMINAL_MARKERS:
            print(sid)
            return 0
    print("done")
    return 0


# ── hooks (register/unregister the coherence hooks in settings.json) ──────────
# Bare-skill installs (npx skills add) carry the hook scripts but nothing
# registers them — this command closes that gap. Keyed by script filename so
# re-running re-points a stale path instead of duplicating the entry.
# Tool events take a matcher; session and prompt events do not. "" means register
# without one — the loop below omits the key entirely rather than writing a field
# Claude Code ignores, which would read as a filter that is silently doing nothing.
HOOK_MATCHERS = {
    "guard_plan_edit.py": ("PreToolUse", "Edit|MultiEdit|Write"),
    "lint_plan.py": ("PostToolUse", "Edit|MultiEdit|Write|Bash"),
    "steer_build.py": ("UserPromptSubmit", ""),
    "report_drift.py": ("SessionStart", ""),
}

# The plugin manifest that registers the same four hooks for a plugin install.
# Absent on a bare-skill (`npx skills add`) or vendored layout, where the skill
# travels without the plugin wrapper — callers must tolerate it not existing.
PLUGIN_HOOKS_JSON = Path(__file__).resolve().parents[3] / "hooks" / "hooks.json"

# What each hook exits when no interpreter resolves, mirrored in hooks/hooks.json.
# 2 blocks on the events that can block; UserPromptSubmit must NEVER use 2,
# because exit 2 there erases the user's prompt instead of reporting anything.
HOOK_DEAD_EXIT = {
    "guard_plan_edit.py": 2,
    "lint_plan.py": 2,
    "steer_build.py": 1,
    "report_drift.py": 1,
}

# Where a plugin install records itself. Read rather than assumed, because the
# install path is version-pinned and lives outside any repo.
PLUGIN_STATE = Path.home() / ".claude" / "plugins" / "installed_plugins.json"


def plugin_install_roots(root: Path) -> list[Path]:
    """Installed cozyplan plugin roots that are actually active for `root`.

    CLAUDE_PLUGIN_ROOT is set only WHILE a hook is executing, so a `doctor` or
    `hooks selftest` run from a terminal never sees it. Reading only that
    variable reported "not registered" to every plugin user forever — a record
    consulted in the one context where it is always empty, which is the exact
    error this layer exists to catch, inside the check meant to catch it.

    A project-scoped install belongs to one projectPath and is inert everywhere
    else, so an install pinned to another repo must not count as wiring here.
    """
    out: list[Path] = []
    env_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if env_root:
        out.append(Path(env_root))
    if not PLUGIN_STATE.exists():
        return out
    try:
        data = json.loads(read(PLUGIN_STATE))
    except (OSError, ValueError):
        return out
    for key, installs in (data.get("plugins") or {}).items():
        if key.split("@")[0] != "cozyplan":
            continue
        for inst in installs or []:
            path = inst.get("installPath")
            if not path:
                continue
            if inst.get("scope") == "project":
                owner = inst.get("projectPath")
                try:
                    if not owner or Path(owner).resolve() != root.resolve():
                        continue  # installed, but scoped to a different project
                except OSError:
                    continue
            out.append(Path(path))
    return out


def active_plugin_hooks_json(root: Path | None = None) -> Path | None:
    """The manifest, but only when the plugin is genuinely installed AND active
    for this project. The file existing beside this script proves nothing — a
    source checkout has one too — so this never falls back to the checkout."""
    for base in plugin_install_roots(root or Path(".")):
        p = base / "hooks" / "hooks.json"
        if p.exists():
            return p
    return None


def cmd_hooks(args) -> int:
    hook_dir = resolve_hook_dir(Path(getattr(args, "root", ".")))
    if args.settings:
        settings_path = Path(args.settings)
    elif args.global_:
        settings_path = Path.home() / ".claude" / "settings.json"
    else:
        settings_path = Path(".claude") / "settings.json"

    launcher = hook_dir / "run-hook.sh"
    if args.hooks_cmd == "install":
        missing = [n for n in HOOK_MATCHERS if not (hook_dir / n).exists()]
        if not launcher.exists():
            missing.append(launcher.name)
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

    # .claude/settings.json is a COMMITTED file, so an absolute path in it is a
    # path that is right on exactly one machine and travels to everyone else.
    # Claude Code substitutes ${CLAUDE_PROJECT_DIR} into hook commands before the
    # shell sees them, so when the scripts live inside the project — vendored, or
    # a source checkout, which covers the ordinary cases — the registration can be
    # written relative and stay correct on every clone.
    #
    # Not for --global: that file is one user's, shared across projects, and
    # ${CLAUDE_PROJECT_DIR} would re-point it at whichever repo is open.
    project = None if args.global_ else Path(getattr(args, "root", "."))

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
            # Through run-hook.sh, exactly as the plugin manifest does. This route
            # used to bake `uv run` and an absolute interpreter in at INSTALL time,
            # so a host that later lost uv — or a colleague who never had it — got
            # a registered hook that could not start, with no message. Resolving at
            # call time and failing loud is the whole of ADR-0010, and it has to
            # hold on both registration paths or the layer is only half fixed.
            cmd_str = hook_command(script,
                                   registered_path(hook_dir / script, project),
                                   registered_path(launcher, project))
            block = {"hooks": [{"type": "command", "shell": "bash", "command": cmd_str}]}
            if matcher:
                block["matcher"] = matcher
            entries.append(block)
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


# ── hooks selftest (ADR-0010) ────────────────────────────────────────────────
# The four-probe problem this closes. guard_plan_edit fails open on an
# unreadable payload, on a non-plan path, and on a new file. Each is correct.
# Each also exits 0 in silence, which is indistinguishable from the hook never
# having run — the state a machine without uv was actually in. Three consecutive
# probes therefore "passed" while the layer was inert, and a report written after
# any of them would have looked exactly like a correct one.
#
# So this drives every hook with a payload that MUST produce a visible reaction,
# through the command the host actually registered, and fails when any hook stays
# silent. Registration is a record. A refusal is an outcome.

SELFTEST_PLAN = """<!doctype html>
<html><body>
<span data-meta="status">active</span>
<div class="phase" data-phase="1">
  <code class="status" data-status-for="phase-1">[]</code>
</div>
</body></html>
"""


def _selftest_fixture(tmp: Path) -> None:
    """A throwaway repo shaped so all four hooks have something to say.

    Deliberately NOT the caller's repo: a selftest whose result depends on
    whether this project happens to have an active plan today reports the
    repo's contents, not whether the hook layer runs."""
    (tmp / "specs").mkdir(parents=True, exist_ok=True)
    (tmp / "docs").mkdir(parents=True, exist_ok=True)
    # report_drift returns early unless this exists — it is the one artifact
    # every wired cozyplan repo has and no other tool creates.
    write(tmp / "docs" / "state.ndjson", "")
    write(tmp / "specs" / "selftest-plan.html", SELFTEST_PLAN)
    # Anchored but defective, NOT merely malformed. `validate` classifies a file
    # with no data-* anchors as legacy and passes it with reduced checks, so the
    # obvious "garbage html" fixture made lint_plan correctly say nothing and
    # read as a dead hook. The defect has to be one validate actually rejects.
    write(tmp / "specs" / "broken-plan.html", SELFTEST_PLAN.replace("[]", "[bogus]"))
    write(tmp / "specs" / "_index.json", json.dumps(
        {"plans": [{"id": "selftest", "file": "selftest-plan.html", "status": "active"}]}))


def _selftest_cases(tmp: Path) -> dict:
    plan = (tmp / "specs" / "selftest-plan.html").as_posix()
    broken = (tmp / "specs" / "broken-plan.html").as_posix()
    return {
        "guard_plan_edit.py": {
            "payload": {"tool_name": "Edit", "cwd": str(tmp), "tool_input": {
                "file_path": plan,
                "old_string": '<span data-meta="status">active</span>',
                "new_string": '<span data-meta="status">built</span>'}},
            "expect": "refuse",
            "want": "deny an edit that rewrites a CLI-managed metadata region",
        },
        "lint_plan.py": {
            "payload": {"tool_name": "Write", "cwd": str(tmp),
                        "tool_input": {"file_path": broken}},
            "expect": "context",
            "want": "report a validate failure for a malformed plan",
        },
        "steer_build.py": {
            "payload": {"cwd": str(tmp), "prompt": "continue the build"},
            "expect": "context",
            "want": "surface the active plan's re-entry point",
        },
        "report_drift.py": {
            "payload": {"cwd": str(tmp), "source": "startup"},
            "expect": "context",
            "want": "report wiring gaps (the fixture repo is deliberately unwired)",
        },
    }


def _selftest_observe(expect: str, stdout: str) -> str | None:
    """What the hook was observed to DO, or None when it said nothing.

    None is the failure. It is also what a hook that never ran produces, which
    is the point: the two are the same result and must both count as broken."""
    text = (stdout or "").strip()
    if not text.startswith("{"):
        return None  # silence, or plain text where a decision was required
    try:
        data = json.loads(text)
    except ValueError:
        return None
    out = data.get("hookSpecificOutput") or {}
    if expect == "refuse":
        return "DENIED the edit" if out.get("permissionDecision") == "deny" else None
    ctx = (out.get("additionalContext") or "").strip()
    if not ctx:
        return None
    return "reported: " + ctx.splitlines()[0][:52]


def registered_hook_commands(root: Path) -> tuple[dict, str, Path | None]:
    """({script: command}, where-it-came-from, plugin root) for this project.

    settings.json wins over the plugin manifest only because a project that has
    run `hooks install` is stating a preference; both are reported by doctor."""
    settings = root / ".claude" / "settings.json"
    manifest = active_plugin_hooks_json(root)
    for label, path, proot in (("`.claude/settings.json`", settings, None),
                               ("the plugin manifest", manifest,
                                manifest.parent.parent if manifest else None)):
        if not path or not path.exists():
            continue
        try:
            data = json.loads(read(path))
        except (OSError, ValueError):
            continue
        found = {}
        for _event, blocks in (data.get("hooks") or {}).items():
            for blk in blocks or []:
                for h in (blk.get("hooks") or []):
                    cmd = (h.get("command") or "") if isinstance(h, dict) else ""
                    for script in HOOK_MATCHERS:
                        if script in cmd:
                            found[script] = cmd
        if found:
            return found, label, proot
    return {}, "", None


def vendor_source_problem(root: Path) -> str | None:
    """Why this plan_tool may not act as a `--vendor` SOURCE, or None if it may.

    Two failures, one missing guard. The only check that existed compared the
    source against `root/skills`, which catches cozyplan's own source layout and
    nothing else — a vendored copy lives at `.claude/skills/`, so both of these
    proceeded silently:

    1. **A vendored copy is not an upstream.** Its git repository is the
       CONSUMING repo, so provenance is stamped from the wrong history: version
       `unknown`, source commit the consumer's own sha, source remote the
       consumer's own remote. `doctor` then reports that upstream is *not
       reachable* rather than that anything is wrong — so the freshness row, the
       one check that names this drift, is silently disabled by the exact act it
       exists to guard against. Reported by cozycode, which reproduced it twice.

    2. **Vendoring into the tree being read from destroys it.** When source and
       destination are the same directory, the `rmtree` that clears the
       destination deletes the source, and the copy then fails part-way. Observed
       here: 21 files removed before `FileNotFoundError`. Recoverable from git
       only because they were committed.

    Refused, not warned. A warning here is a prompt in different clothes, and the
    damage is done by the time anyone reads it.
    """
    me = Path(__file__).resolve()
    src_dir = me.parent.parent.parent  # <skills>/cozyplan/scripts/plan_tool.py -> <skills>

    if ".claude" in me.parts:
        return ("this plan_tool is itself a vendored copy, so it cannot be a vendor source: "
                "its git history belongs to the consuming repo, and provenance stamped from "
                "it would record that repo as its own upstream. Run cozyplan's own checkout "
                "instead:\n"
                "  SRC=\"$(git config cozyplan.source)\"\n"
                "  python3 \"$SRC/skills/cozyplan/scripts/plan_tool.py\" init --root "
                f"\"{root}\" --vendor")

    # Narrow on purpose: the danger is not "source inside root" — a source may sit
    # inside the target harmlessly. It is the copy clearing a directory that
    # CONTAINS its own source, which is only true when the two are the same tree.
    dest_dir = (root / ".claude" / "skills")
    try:
        src_dir.relative_to(dest_dir.resolve())
    except (ValueError, OSError):
        return None
    return (f"the skills being vendored ({src_dir}) are inside the destination "
            f"({dest_dir}), so clearing it would delete the source mid-copy. Run "
            "cozyplan's own checkout from outside this repo.")


def resolve_git_hook_tool(root: Path) -> str:
    """The plan_tool the git hooks should run, as a path they should record.

    Prefers a copy inside the repo, recorded RELATIVE — git runs hooks from the
    worktree top level, so a relative path resolves there and survives the repo
    being moved or cloned to a different absolute path.

    Before this, `git-install` recorded `Path(__file__).resolve()` — wherever the
    tool happened to be invoked from. A consuming repo wired from a maintainer's
    checkout therefore ran *that* checkout's plan_tool to answer "is this repo
    healthy", while carrying a perfectly good vendored copy of its own. Two
    plan_tools answering the same question on one machine is a drift defect
    waiting to happen, and nothing compared them. Reported by cozycode.
    """
    for rel in (Path(".claude") / "skills" / "cozyplan" / "scripts" / "plan_tool.py",
                Path("skills") / "cozyplan" / "scripts" / "plan_tool.py",
                Path("scripts") / "plan_tool.py"):
        if (root / rel).exists():
            return rel.as_posix()
    # Nothing in the repo: fall back to this file, absolute. Correct here, and
    # inert on any other machine — the hooks open with `|| exit 0`, so doctor is
    # what has to say so.
    return str(Path(__file__).resolve())


def resolve_hook_dir(root: Path) -> Path:
    """The hook scripts to REGISTER: a copy vendored inside the project wins over
    the running tool's own.

    Same order SKILL.md and the CI workflow already use. Without it, running
    `init --vendor` from a source checkout copied the skill into the repo and then
    registered the *checkout* — so the repo carried a perfectly good vendored copy
    and a committed settings.json naming a path that exists on one machine.
    """
    vendored = root / ".claude" / "skills" / "cozyplan" / "scripts" / "hooks"
    if (vendored / "run-hook.sh").exists():
        return vendored
    return Path(__file__).resolve().parent / "hooks"


def hook_launcher() -> Path:
    """run-hook.sh, which ships BESIDE the hook scripts rather than in the plugin's
    hooks/ directory. The skill directory travels as one unit through every
    distribution shape — plugin install, `npx skills add`, vendored into a repo —
    and the plugin wrapper does not. Kept at the plugin root, the launcher was
    missing from two of those three, so the hooks it launches would have shipped
    without it."""
    return Path(__file__).resolve().parent / "hooks" / "run-hook.sh"


def registered_path(target: Path, project: Path | None) -> str:
    """How a path is written into a registration: ${CLAUDE_PROJECT_DIR}-relative
    when it lives inside the project, absolute otherwise.

    Computed as a real relative path rather than by substituting the project
    prefix into the string. The first attempt did the latter and silently never
    matched on macOS, where /tmp resolves to /private/tmp — so it emitted absolute
    paths while every test that checked the *logic* still passed.
    """
    if project is not None:
        try:
            rel = target.resolve().relative_to(project.resolve())
            return "${CLAUDE_PROJECT_DIR}/" + rel.as_posix()
        except (OSError, ValueError):
            pass
    return target.as_posix()


def shell_arg(s: str) -> str:
    """Quote one path for a shell command string.

    `shlex.quote` emits SINGLE quotes, which protect everything — including a
    `${...}` placeholder the shell is supposed to expand. A registration written
    that way reached `sh` as the literal string `${CLAUDE_PROJECT_DIR}/...`, which
    is not a filename, so every hook exited 127 on every matched tool call while
    the paths inside were perfectly correct.

    Double quotes are what a placeholder needs: they expand `$` and still hold a
    path together across spaces, which this project's own path has. Everything a
    double quote does NOT cover is escaped — a literal backslash, a double quote,
    a backtick. `$` is deliberately left alone; expanding it is the point.
    """
    if "${" not in s:
        return shlex.quote(s)
    esc = s.replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`")
    return f'"{esc}"'


def hook_command(script: str, target: str, launcher: str) -> str:
    """The one command string both registration paths write, so the plugin route
    and the settings.json route cannot drift into behaving differently."""
    return (f'sh {shell_arg(launcher)} '
            f'{shell_arg(target)} {HOOK_DEAD_EXIT[script]}')


def _shipped_hook_commands() -> tuple[dict, str, Path | None]:
    """The hooks as they ship, launched exactly the way the manifest launches
    them — through run-hook.sh. Lets a developer (and this repo's own CI, which
    is not a plugin install) verify the scripts before any wiring exists."""
    launcher = hook_launcher()
    hook_dir = Path(__file__).resolve().parent / "hooks"
    cmds = {}
    for script in HOOK_MATCHERS:
        target = hook_dir / script
        if launcher.exists():
            cmds[script] = hook_command(script, target.as_posix(), launcher.as_posix())
        else:
            exe, arg = _hook_runner_parts()
            cmds[script] = " ".join(shlex.quote(x) for x in
                                    ([exe] + ([arg] if arg else []) + [target.as_posix()]))
    return cmds, "the shipped scripts (not registered anywhere)", None


def _run_registered(cmd: str, payload: dict, cwd: Path, plugin_root: Path | None,
                    project_root: Path | None = None):
    """Run a registered hook command the way the host runs it: verbatim, through a
    shell, with the ${...} variables supplied in the ENVIRONMENT.

    The command is NOT rewritten. An earlier version substituted the placeholders
    itself and then ran the result, which removed the fault before looking for it:
    a registration whose paths were single-quoted could never expand under a real
    shell, and selftest reported `4/4 observed` while all four hooks were exiting
    127 on every tool call. A check that edits its subject cannot observe it.

    project_root is the REAL project, not the throwaway fixture in cwd — the
    registered command names its scripts relative to ${CLAUDE_PROJECT_DIR}, and
    pointing that at the fixture aims every hook at a directory with no scripts.
    """
    if shutil.which("sh"):
        argv = ["sh", "-c", cmd]
    else:
        # No POSIX shell. hooks.json pins "shell": "bash", so this host cannot run
        # the plugin hooks at all — say so by failing, never by skipping. Nothing
        # expands here, which is itself the honest result on such a host.
        argv = shlex.split(cmd)
    # report_drift runs `doctor`, and doctor runs this selftest. Without a marker
    # the two call each other forever: doctor -> selftest -> report_drift ->
    # doctor -> ... Each level is a real subprocess, so it exhausts the machine
    # rather than raising RecursionError. doctor skips its selftest row when set.
    env = os.environ.copy()
    env["COZYPLAN_SELFTEST"] = "1"
    # The host sets these; the shell expands them. Supplying them the same way is
    # what lets a mis-quoted registration fail here exactly as it fails in a real
    # session, instead of being quietly repaired by the check.
    env["CLAUDE_PROJECT_DIR"] = str((project_root or cwd).resolve())
    env["CLAUDE_PLUGIN_ROOT"] = str(plugin_root or PLUGIN_HOOKS_JSON.parent.parent)
    return subprocess.run(argv, input=json.dumps(payload), capture_output=True,
                          text=True, cwd=str(cwd), timeout=90, env=env)


def run_hooks_selftest(root: Path, shipped: bool = False):
    """(rows, failures, source), where rows are (script, event, result, ok).

    Shared by `hooks selftest` and `doctor` so the two can never disagree about
    whether the layer runs. Empty rows means nothing was registered — which is a
    finding, not an absence of one, and each caller says so in its own voice."""
    if shipped:
        commands, source, plugin_root = _shipped_hook_commands()
    else:
        commands, source, plugin_root = registered_hook_commands(root)
    if not commands:
        return [], [], ""

    rows, failures = [], []
    with tempfile.TemporaryDirectory(prefix="cozyplan-selftest-") as td:
        tmp = Path(td)
        _selftest_fixture(tmp)
        for script, case in _selftest_cases(tmp).items():
            event = HOOK_MATCHERS[script][0]
            cmd = commands.get(script)
            if not cmd:
                rows.append((script, event, "NOT REGISTERED", False))
                failures.append((script, "no command registered for this hook"))
                continue
            try:
                r = _run_registered(cmd, case["payload"], tmp, plugin_root, root)
            except (OSError, subprocess.SubprocessError) as e:
                rows.append((script, event, "COULD NOT LAUNCH", False))
                failures.append((script, f"launching it raised {type(e).__name__}: {e}"))
                continue
            observed = _selftest_observe(case["expect"], r.stdout)
            if observed:
                rows.append((script, event, observed, True))
            else:
                # Three different diagnoses, and calling them all "silent" hides the
                # worst one. Reported by cozycode, whose own gate hit it: `set -e`
                # plus a loop ending in a false test exited 1 with no output — "a
                # gate that looks like it ran and refused, with nothing to read".
                err = (r.stderr or "").strip()
                if r.returncode != 0 and not err:
                    # Blocked the action and gave nobody a reason. On PreToolUse the
                    # docs are explicit that the blocking message falls back to
                    # stderr, so an empty stderr is a refusal with an empty reason.
                    label = "REFUSED, NO REASON"
                    detail = (f"exited {r.returncode} and wrote nothing — it blocks the "
                              f"action and leaves nothing to read. Expected it to "
                              f"{case['want']}")
                elif r.returncode != 0:
                    label = "FAILED"
                    detail = (f"exited {r.returncode}: {err.splitlines()[0][:90]} "
                              f"(expected it to {case['want']})")
                else:
                    label = "SILENT"
                    detail = (f"exit 0 and no output, which is what a hook that never ran "
                              f"also produces. Expected it to {case['want']}")
                rows.append((script, event, label, False))
                failures.append((script, detail))

    return rows, failures, source


def _doctor_selftest(root: Path) -> tuple[int, int, str]:
    """(observed, total, detail) for doctor's outcome row.

    Never falls back to --shipped: that would report "4/4 observed" on a repo
    where nothing is wired, which is the reassuring-but-false line this whole
    change exists to delete."""
    rows, failures, source = run_hooks_selftest(root)
    if not rows:
        return 0, 0, "no hooks registered, so none can run (`plan_tool hooks install`)"
    observed = sum(1 for r in rows if r[3])
    if failures:
        return observed, len(rows), (f"via {source}; silent: "
                                     + ", ".join(s for s, _ in failures))
    return observed, len(rows), f"via {source}"


def cmd_hooks_selftest(args) -> int:
    root = Path(args.root)
    rows, failures, source = run_hooks_selftest(root, shipped=args.shipped)
    if not rows:
        print("cozyplan hooks selftest — nothing is registered for this project.\n")
        print("  Not a warning: an unregistered hook layer is silent in exactly the")
        print("  way a broken one is. Nothing checked any plan write here.\n")
        print("  Fix with one of:")
        print("    plan_tool hooks install      register in .claude/settings.json")
        print("    /plugin install cozyplan     register via the plugin manifest")
        print("  Or test the shipped scripts without wiring: --shipped")
        return 1

    print(f"cozyplan hooks selftest — via {source}\n")
    width = max(len(s) for s in HOOK_MATCHERS)
    for script, event, result, ok in rows:
        print(f"  [{_MARK[OK] if ok else _MARK[GAP]}] {script:<{width}}  {event:<16} {result}")

    print(f"\n{len(rows) - len(failures)}/{len(rows)} observed")
    if failures:
        print("\na hook that says nothing cannot be told from one that never ran, and one "
              "that\nrefuses without a reason is worse — both are broken:")
        for script, detail in failures:
            print(f"  - {script}: {detail}")
        return 1
    return 0


# ── state check (STATE.md against git reality) ────────────────────────────────
# The snapshot claims things about the repo; git knows whether they still hold.
# This check is deliberately STATIC — it never executes a proof command it found
# in a file (that would be arbitrary code execution from repo content, and slow
# in CI). It verifies shape, anchoring, and freshness, and reports what it cannot
# know. Per ADR-0004 the derivation tolerates gaps: missing anchors narrow the
# report to a warning rather than failing the run.

# "- <capability> — verified by `<command>` (<when>)" where <when> is an ISO date
# optionally followed by the short sha the proof was true at.
STATE_CLAIM_RE = re.compile(
    r"^-\s+(?P<what>.+?)\s+[—-]\s+verified by\s+`(?P<cmd>[^`]+)`\s+"
    r"\((?P<when>[^)]+)\)\s*$"
)
STATE_WHEN_RE = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2})(?:\s*,\s*(?P<sha>[0-9a-f]{7,40}))?$")
REPO_STATE_RE = re.compile(r"^\|\s*Repo state\s*\|\s*(?P<branch>\S+)\s*@\s*(?P<sha>[0-9a-f]{7,40})\s*\|",
                           re.M)
LAST_SYNCED_RE = re.compile(r"^\|\s*Last synced\s*\|\s*(?P<ts>[^|]+?)\s*\|", re.M)
ADR_FILE_RE = re.compile(r"^(?P<num>\d{4})-")


def which_exe(name: str) -> str:
    """Absolute path to `name`, or `name` unchanged when it cannot be found.

    Windows CreateProcess appends only `.exe` when searching PATH, so a tool installed
    as a `.cmd` or `.bat` shim — which is how gh arrives from several package managers
    — is invisible to subprocess even though it is plainly on PATH. shutil.which
    honours PATHEXT and finds it. A no-op on POSIX."""
    return shutil.which(name) or name


def git(root: Path, *argv: str) -> tuple[bool, str]:
    """Run a git command, returning (ok, stripped stdout). Never raises: a missing
    git binary or a non-repo is a condition the caller reports, not a crash."""
    try:
        r = subprocess.run(["git", *argv], cwd=str(root), capture_output=True,
                           stdin=subprocess.DEVNULL,
                           text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False, ""
    return r.returncode == 0, r.stdout.strip()


def git_stdin(root: Path, argv: list[str], text: str) -> tuple[bool, str]:
    """git with its input on stdin, so one batched call can replace a per-item loop.

    Separate from `git()` deliberately: that one closes stdin, and its call count is
    what pins the O(1)-in-claims property this module is measured on. `ok` is true
    for exit 0 and exit 1, because `check-ignore` uses 1 for "matched nothing",
    which is an answer rather than a failure.
    """
    try:
        r = subprocess.run(["git", *argv], cwd=str(root), input=text,
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False, ""
    return r.returncode in (0, 1), r.stdout


def rev_count(root: Path, rng: str) -> int | None:
    """Commits in `rng`, or None when git could not answer. None is not zero: a
    missing binary, shallow clone or corrupt object must be reported, never read
    as "no drift" — that silently opens every gate built on this count."""
    ok, out = git(root, "rev-list", "--count", rng)
    return int(out) if ok and out.isdigit() else None


class HistoryIndex:
    """Three git calls that answer, for every claim, what the checker used to ask
    git about each claim separately.

    `state check` cost 18 ms per claim, all of it subprocess spawn: one
    `rev-list --count` and one `diff`/`ls-files` per claim. That is linear in the
    ledger, so 400 claims took 7 s and 10,000 would take three minutes -- in a
    pre-commit hook and a CI gate. Measured, not guessed: the ndjson itself renders
    5,000 entries in 0.09 s, so the file was never the limit and a different store
    would not have moved this number.

    Built once per run:

      depth        full sha -> commits between it and HEAD. One `rev-list HEAD`.
      last_change  path -> the smallest depth at which it changed. One `log`.
      tracked      every path git carries here. One `ls-files`.
      ignored      which of the claims' untracked paths git is ignoring on purpose.
                   One `check-ignore --stdin`, fed every claim path at once.

    `last_change` is CONSERVATIVE by construction. A path whose most recent change
    is older than the claim is identical in both trees, so "unchanged" is exact and
    there are no false negatives. A path changed and then reverted reports as
    changed, which over-warns; `-m` is passed so a merge's files are attributed
    rather than skipped, for the same reason. Over-warning is a nuisance. Under-
    warning is the defect this whole check exists to prevent (ADR-0010).
    """

    def __init__(self, root: Path, paths: list[str] | None = None):
        self.ok = False
        self.depth: dict[str, int] = {}
        self.last_change: dict[str, int] = {}
        self.tracked: set[str] = set()
        self.ignored: set[str] = set()
        self._short: dict[str, str] = {}

        ok_r, revs = git(root, "rev-list", "HEAD")
        if not ok_r:
            return
        order = [s for s in revs.split() if s]
        self.depth = {s: i for i, s in enumerate(order)}
        # Claims record short shas. Resolve by prefix rather than shelling out per
        # claim, which is the cost this class exists to remove.
        for s in order:
            for n in (7, 8, 9, 10, 12):
                self._short.setdefault(s[:n], s)

        ok_l, log = git(root, "log", "--format=%x00%H", "--name-only", "-m", "HEAD")
        if not ok_l:
            return
        cur = None
        for line in log.splitlines():
            if line.startswith("\x00"):
                cur = self.depth.get(line[1:].strip())
            elif line.strip() and cur is not None:
                p = line.strip()
                if p not in self.last_change or cur < self.last_change[p]:
                    self.last_change[p] = cur

        ok_t, files = git(root, "ls-files")
        if not ok_t:
            return
        self.tracked = {p for p in files.splitlines() if p.strip()}

        # An untracked path is two different facts wearing one face. Under ADR-0019 a
        # ledger entry may name a path inside a gitignored sibling repository — normal,
        # permanent, and unreachable from here. Or the file was renamed or deleted, and
        # the claim now points at nothing. `ls-files` cannot tell them apart;
        # `check-ignore` can, and it is asked ONCE for every claim path in the run,
        # never once per claim (test_history_is_read_once_not_once_per_claim).
        #
        # git, never the filesystem: whether the sibling repo happens to be cloned on
        # this disk is a fact about the machine, and a check that reads it reports a
        # different answer to two people looking at the same commit.
        unresolved = [p.rstrip("/") for p in dict.fromkeys(paths or ())]
        unresolved = [p for p in unresolved if p and not self.is_tracked(p)]
        if unresolved:
            ok_i, out = git_stdin(root, ["check-ignore", "-z", "--stdin"],
                                  "\0".join(unresolved) + "\0")
            if ok_i:
                self.ignored = {p for p in out.split("\0") if p}
        self.ok = True

    def age(self, sha: str) -> int | None:
        """Commits since `sha`, or None when this history cannot answer -- which is
        not zero, and must never be read as one."""
        full = self._short.get(sha) or (sha if sha in self.depth else None)
        return self.depth.get(full) if full else None

    def is_tracked(self, path: str) -> bool:
        p = path.rstrip("/")
        return p in self.tracked or any(t.startswith(p + "/") for t in self.tracked)

    def is_ignored(self, path: str) -> bool:
        """True when git is ignoring this path on purpose — so the checker cannot look,
        rather than having looked and found nothing. Only meaningful for a path the
        constructor was given; anything else is simply unknown here and reads False."""
        return path.rstrip("/") in self.ignored

    def changed_since(self, paths: list[str], age: int) -> list[str]:
        """Every file under `paths` that changed in the `age` commits since the claim.

        Every file, not the first one found: the warning reports a COUNT, and a count
        that means "how many of the claim's paths matched" while reading "how many
        files changed" is a number that lies quietly. Sorted so two runs of the same
        check name the same example.
        """
        hits = set()
        stems = [p.rstrip("/") for p in paths]
        for f, d in self.last_change.items():
            if d < age and any(f == q or f.startswith(q + "/") for q in stems):
                hits.add(f)
        return sorted(hits)


def section_body(text: str, heading: str) -> str:
    """The lines under a `## heading`, up to the next heading of the same level."""
    m = re.search(rf"^##\s+{re.escape(heading)}\s*$(?P<body>.*?)(?=^##\s|\Z)",
                  text, re.M | re.S)
    return m.group("body") if m else ""


def check_state(state_path: Path, root: Path, adr_dir: Path, journal: Path,
                max_drift: int | None,
                max_claim_age: int | None = None,
                log_path: Path | None = None) -> tuple[list[str], list[str], list[str]]:
    """Return (problems, warns, notes). Problems fail the run; warns and notes do not."""
    problems: list[str] = []
    warns: list[str] = []
    notes: list[str] = []

    text = read(state_path)

    # 0. The file under test is a RENDER of the log, and every other check below reads
    #    only the render. So `state add` without `state render` leaves a log and a
    #    snapshot that disagree, and this command printed OK over both -- observed
    #    2026-09-01 with 123 passed in one file and 114 in the other. That is ADR-0010
    #    inside the checking tool: it observed the record of the outcome.
    #
    #    Compare against the LOG, not against a fresh render. A render also depends on
    #    --origin, --project and --specs, which `state check` does not take, so two
    #    renders of the same log differ whenever a repo passes any of them -- a warn
    #    that fires on correct state is the noise this tool already has too much of.
    #    Known limit: this catches an entry the log has and the file lacks. A `--clear`
    #    with no re-render leaves a retracted entry visible and is not caught here.
    if log_path is not None:
        try:
            projected = project_state(read_state_log(root, log_path))
            missing = [ev.get("what", "") for kind in STATE_KINDS for ev in projected[kind]
                       if ev.get("what") and ev["what"] not in text]
        except Exception as exc:                  # noqa: BLE001 - reported, never swallowed
            # Loud on the apparatus. Unable to look is not the same as nothing to report.
            notes.append(f"could not compare {state_path.name} against the log: "
                         f"{type(exc).__name__}: {exc}")
        else:
            if missing:
                warns.append(
                    f"{state_path.name} is stale against the log: {len(missing)} projected "
                    f"entr(ies) missing from it, e.g. {missing[0][:60]!r}. "
                    f"Run `plan_tool state render`.")

    # 1. No unfilled scaffold slots. A placeholder in a snapshot is a lie with a
    #    template's face on it.
    tokens = re.findall(r"\{\{.*?\}\}", text, re.S)
    if tokens:
        problems.append(f"{len(tokens)} unfilled {{{{}}}} placeholder token(s) in {state_path.name}")

    # 2. The sync block must be parseable — everything downstream keys off it.
    m_repo = REPO_STATE_RE.search(text)
    m_sync = LAST_SYNCED_RE.search(text)
    if not m_sync:
        problems.append("no parseable 'Last synced' row in the Sync block")
    if not m_repo:
        problems.append("no parseable 'Repo state | <branch> @ <sha>' row in the Sync block")

    in_git, _ = git(root, "rev-parse", "--is-inside-work-tree")
    if not in_git:
        notes.append("not a git work tree (or git unavailable) — freshness checks skipped")

    # 3. Snapshot freshness. The sha is recorded today but never read back; reading
    #    it is the whole point of this check.
    if in_git and m_repo:
        sha = m_repo.group("sha")
        ok_obj, _ = git(root, "cat-file", "-e", f"{sha}^{{commit}}")
        if not ok_obj:
            problems.append(f"Repo state names {sha}, which is not a commit in this repo")
        else:
            ok_anc, _ = git(root, "merge-base", "--is-ancestor", sha, "HEAD")
            if not ok_anc:
                problems.append(
                    f"Repo state {sha} is not an ancestor of HEAD — the snapshot was taken "
                    "on a branch this one does not contain")
            else:
                behind = rev_count(root, f"{sha}..HEAD")
                if behind is None:
                    problems.append(
                        f"cannot compute drift: `git rev-list --count {sha}..HEAD` failed")
                else:
                    notes.append(f"snapshot is {behind} commit(s) behind HEAD")
                    if max_drift is not None and behind > max_drift:
                        problems.append(f"snapshot is {behind} commit(s) behind HEAD (max-drift {max_drift})")
        ok_st, dirty = git(root, "status", "--porcelain")
        if ok_st and dirty:
            warns.append(f"working tree has {len(dirty.splitlines())} uncommitted change(s); "
                         "any claim proved against it is not reproducible from HEAD")

    # 4. Every Current Working State line carries its proof, in a shape a machine
    #    can read. A claim whose proof cannot be parsed cannot be checked later.
    body = section_body(text, "Current Working State")
    body_lines = body.splitlines()
    claims = []
    for i, ln in enumerate(body_lines):
        if ln.strip().startswith("- ") and "<!--" not in ln:
            # The pointer trail sits on the next line, indented under the claim. It is
            # where `path:` lives, and paths are what make the staleness check specific
            # instead of merely temporal.
            trail = body_lines[i + 1] if i + 1 < len(body_lines) else ""
            claims.append((ln, trail if trail.strip().startswith("\u21b3") else ""))
    if not claims:
        notes.append("Current Working State is empty")
    # One index for every claim, instead of two git calls per claim. See HistoryIndex.
    # It is handed every claim path up front so the ignore question is one call too.
    claim_paths = [p for _, trail in claims for p in re.findall(r"path:(\S+)", trail)]
    hist = HistoryIndex(root, claim_paths) if in_git else None
    unverifiable = 0
    for ln, trail in claims:
        m = STATE_CLAIM_RE.match(ln.strip())
        if not m:
            problems.append(f"claim does not name its proof: {ln.strip()[:90]}")
            continue
        mw = STATE_WHEN_RE.match(m.group("when").strip())
        if not mw:
            problems.append(
                f"claim's proof timestamp is not '<YYYY-MM-DD>' or '<YYYY-MM-DD>, <sha>': "
                f"{m.group('when').strip()[:60]}")
            continue
        sha = mw.group("sha")
        if not sha:
            warns.append(f"claim is date-anchored but not commit-anchored, so staleness "
                         f"cannot be computed: {m.group('what')[:60]}")
            continue
        if in_git:
            if hist is None or not hist.ok:
                warns.append(f"cannot read this repository's history, so staleness "
                             f"cannot be computed: {m.group('what')[:60]}")
                continue
            age = hist.age(sha)
            if age is None:
                # Not in the ancestry of HEAD. Either the object is unknown, or it is
                # real and sits on another branch, and those are different reports.
                ok_obj, _ = git(root, "cat-file", "-e", f"{sha}^{{commit}}")
                if ok_obj:
                    problems.append(f"claim cites {sha}, which is a commit here but not "
                                    f"an ancestor of HEAD: {m.group('what')[:60]}")
                else:
                    problems.append(f"claim cites {sha}, which is not a commit in this "
                                    f"repo: {m.group('what')[:60]}")
                continue
            aged_out = False
            if age:
                # A claim nobody re-proves is the thing this layer exists to prevent,
                # so it can be made fatal rather than only mentioned.
                msg = f"claim proved {age} commit(s) ago: {m.group('what')[:60]}"
                if max_claim_age is not None and age > max_claim_age:
                    problems.append(f"{msg} (limit {max_claim_age}) — re-run its proof "
                                    f"and re-anchor it, or record it as a gap")
                    aged_out = True
                else:
                    notes.append(msg)
            # Commit distance says a claim is old. Path intersection says it is
            # probably wrong, which is the difference between a count and a signal:
            # a test run or a spike touches nothing a claim depends on and stays quiet.
            #
            # But `git diff` returns nothing for a path this repo does not track, and
            # nothing is exactly what an untouched path returns. Silence therefore
            # means two different things, and the caller cannot tell which — the
            # shape ADR-0018 rule 5 names: never answer "empty" when you mean
            # "unreachable". Found live in cozycode, where 18 of 35 aged claims point
            # into a gitignored sibling repository and every one of them read clean.
            #
            # Untracked was one bucket and is two, and ADR-0010 gives them opposite
            # volumes because they are opposite kinds of failure.
            #
            # GONE — untracked and not ignored. The file was renamed or deleted, so the
            # proof can never be re-run and the claim points at nothing. That is a defect
            # in the subject, it is exactly the shape of "claim cites <sha>, which is not
            # a commit in this repo" one field over, and it is fatal for the same reason.
            # It is NOT gated on the age limit: a claim whose path no longer exists is
            # wrong on the day it is written, and waiting N commits to say so is the
            # under-warning this check exists to prevent. Silent until now.
            #
            # UNVERIFIABLE HERE — untracked because git is ignoring it, which under
            # ADR-0019 means it lives in a sibling repository this one structurally
            # cannot see. Normal and permanent. That is the apparatus admitting it
            # cannot look, and ADR-0010 forbids only one thing about it: leaving the
            # same trace as a verified claim. So it leaves a different one and is never
            # fatal — every solution and every deliverable would be permanently red for
            # a fact no commit here can change. One census note per run rather than one
            # note per claim, because 42 identical lines is how a report teaches people
            # to skim past it; the per-claim detail appears where somebody is already
            # being asked to re-prove the thing, i.e. past the age limit.
            paths = re.findall(r"path:(\S+)", trail)
            gone = [p for p in paths if not hist.is_tracked(p) and not hist.is_ignored(p)]
            if gone:
                # Reported for any claim carrying one, including a claim whose other
                # paths are tracked — that case used to fall through to the diff and
                # report clean.
                problems.append(
                    f"claim names {len(gone)} path(s) this repo neither tracks nor "
                    f"ignores — renamed or deleted, so its proof cannot be re-run "
                    f"(e.g. {gone[0]}): {m.group('what')[:60]}")
            if not paths:
                if aged_out:
                    warns.append(
                        f"claim names no path, so whether its subject changed cannot be "
                        f"checked — it is unverified here, not clean: {m.group('what')[:60]}")
            elif not any(hist.is_tracked(p) for p in paths):
                if not gone:
                    unverifiable += 1
                    if aged_out:
                        warns.append(
                            f"claim's subject is git-ignored here, so this checker cannot "
                            f"look at it — unverifiable here, not verified (e.g. "
                            f"{paths[0]}): {m.group('what')[:60]}")
            else:
                touched = hist.changed_since(paths, age or 0)
                if touched:
                    warns.append(
                        f"claim's own code changed since it was proved "
                        f"({len(touched)} file(s), e.g. {touched[0]}): "
                        f"{m.group('what')[:60]}")

    if unverifiable:
        notes.append(
            f"{unverifiable} claim(s) name a subject git ignores here, so they are "
            f"unverifiable in this repository — not verified (ADR-0019: a ledger belongs "
            f"where its subject can be reached)")

    # 5. The ADR register against what git will actually hand a clone.
    #
    #    This deliberately does NOT enumerate the directory. `render_state` builds
    #    Registers from `adr_dir.glob("*.md")`, so checking the register against the
    #    same glob compares a generated list to its own generator: after any render
    #    the two agree by construction, and the check can never fail. It passed on an
    #    ADR git had never seen — rendered into Registers from disk, cited in STATE.md,
    #    absent from every clone (cozyplan#4, found by cozycode).
    #
    #    Render from disk, check against the index: that is what keeps the
    #    disagreement representable. Switching render to the index too would silently
    #    drop the file instead of reporting it.
    #
    #    `--cached` alone, never `--cached --others`. The question here is "will a
    #    clone have this file", so an untracked file is precisely the failure being
    #    looked for. A staged file counts as present, correctly — it is going into the
    #    commit. cozycode's PortabilityTest asks the mirror-image question and needs
    #    `--others` for it; the two look alike and want opposite answers.
    if adr_dir.is_dir():
        ok_ls, ls_out = git(root, "ls-files", "--cached", "--", str(adr_dir))
        tracked = {m.group("num") for line in ls_out.splitlines()
                   if (m := ADR_FILE_RE.match(Path(line.strip()).name))} if ok_ls else set()
        on_disk = {m.group("num") for f in adr_dir.glob("*.md")
                   if (m := ADR_FILE_RE.match(f.name))}
        registers = section_body(text, "Registers")
        listed = set(re.findall(r"ADR-(\d{4})", registers))
        if not ok_ls:
            warns.append("cannot list tracked ADRs (`git ls-files` failed) — the register "
                         "was checked against the working tree, which a clone will not have")
            tracked = on_disk
        for num in sorted(tracked - listed):
            problems.append(f"ADR-{num} is tracked in {adr_dir}/ but missing from the Registers index")
        for num in sorted(listed - tracked):
            if num in on_disk:
                problems.append(
                    f"Registers index lists ADR-{num}, which exists in {adr_dir}/ but is not "
                    f"staged or committed — every clone renders a register citing a file it "
                    f"does not have. Run: git add {adr_dir}/{num}-*.md")
            else:
                problems.append(f"Registers index lists ADR-{num}, which has no file in {adr_dir}/")
    else:
        notes.append(f"no {adr_dir}/ directory — ADR register check skipped")

    # 6. The ledger. Its entry format is prose owned by the journal's own header,
    #    so this checks presence and agreement only — never tries to parse it.
    if not journal.exists():
        warns.append(f"no ledger at {journal} — history has nowhere to accumulate")
    elif m_sync:
        ts = m_sync.group("ts").strip()
        if ts and ts not in read(journal):
            warns.append(f"ledger has no entry stamped '{ts}' — the newest sync may be unrecorded")

    return problems, warns, notes


# ── state log + render (ADR-0005: append-only log, capped projection) ─────────
# The log is Tier 1: union-merged, append-only, never rewritten. STATE.md is
# Tier 2: generated, capped, ranked by importance. Ordering is COMMIT order —
# union merge concatenates without ordering it, and wall clocks skew across
# machines, so the only total order every writer already shares is git's.

STATE_LOG_DEFAULT = "docs/state.ndjson"
STATE_KINDS = ("claim", "indev", "gap")

# The one machine-detectable signal that STATE.md is generated rather than authored.
# `state render` truncates its output file, so this string is what stands between a
# hand-authored snapshot and silent, total data loss (ADR-0005).
STATE_GENERATED_MARKER = "GENERATED by `plan_tool state render`"


def sync_stripped(text: str) -> str:
    """STATE.md minus the two Sync rows.

    `Last synced` and `Repo state` change on every render regardless of whether
    any entry changed, so a byte comparison of two renders is always unequal and
    tells you nothing. Everything else in the file is a function of the log.
    """
    return "\n".join(line for line in text.splitlines()
                      if not LAST_SYNCED_RE.search(line)
                      and not REPO_STATE_RE.search(line))
ZERO_SHA = "0" * 40
BLAME_HDR_RE = re.compile(r"^([0-9a-f]{40})\s+\d+\s+(\d+)")


def state_log_order(root: Path, log_path: Path, n_lines: int) -> list[tuple]:
    """A sort key per line index, taken from the commit that introduced the line.

    Uncommitted lines sort last — they are the newest by definition. Falls back to
    file order when git or blame is unavailable: a degraded order, never a crash
    (ADR-0004)."""
    ok, out = git(root, "blame", "--porcelain", "--", str(log_path))
    if not ok or not out:
        return [(1, 0, i) for i in range(n_lines)]
    # Rank by position in history, NOT by committer-time: timestamps have
    # one-second granularity, so two commits made in the same second tie and fall
    # back to file order — precisely the order union merge does not preserve.
    ok_log, log_out = git(root, "log", "--topo-order", "--reverse",
                          "--format=%H", "--", str(log_path))
    rank = {sha: i for i, sha in enumerate(log_out.split("\n"))} if ok_log else {}
    far = len(rank) + 1
    keys: dict[int, tuple] = {}
    sha, line_no = ZERO_SHA, 0
    for ln in out.split("\n"):
        m = BLAME_HDR_RE.match(ln)
        if m:
            sha, line_no = m.group(1), int(m.group(2))
        elif ln.startswith("\t"):
            # 0 = committed (ordered by history position); 1 = still uncommitted.
            keys[line_no - 1] = ((1, far) if sha == ZERO_SHA
                                 else (0, rank.get(sha, far)))
    return [keys.get(i, (1, far)) + (i,) for i in range(n_lines)]


def read_state_log(root: Path, log_path: Path) -> list[dict]:
    """Every event in the log, in commit order. A malformed line is skipped rather
    than fatal — union merge can land junk, and a log that will not parse must not
    take the render down with it."""
    if not log_path.exists():
        return []
    raw = [ln for ln in read(log_path).split("\n") if ln.strip()]
    order = state_log_order(root, log_path, len(raw))
    seen, events = set(), []
    for i, ln in enumerate(raw):
        if ln in seen:      # union merge can duplicate an identical append
            continue
        seen.add(ln)
        try:
            ev = json.loads(ln)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(ev, dict) or ev.get("kind") not in STATE_KINDS:
            continue
        ev["_ord"] = order[i]
        events.append(ev)
    events.sort(key=lambda e: e["_ord"])
    return events


def project_state(events: list[dict]) -> dict:
    """Reduce the log to current truth: last write wins per (kind, key), and an
    event marked cleared removes the key. Ordered by commit position, which every
    writer already shares: the one total order available without a clock (ADR-0008
    removed the weight ranking this used to apply)."""
    current: dict = {}
    for ev in events:
        k = (ev["kind"], ev.get("key") or ev.get("what", ""))
        if ev.get("cleared"):
            current.pop(k, None)
        else:
            current[k] = ev
    out: dict = {kind: [] for kind in STATE_KINDS}
    for (kind, _), ev in current.items():
        out[kind].append(ev)
    for kind in out:
        out[kind].sort(key=lambda e: e["_ord"])
    return out


def refs_line(ev: dict) -> str:
    """The pointer trail. An entry carries the ids needed to decide whether to
    follow it, never the detail itself, so truncating a view would cost immediacy
    and never reachability (ADR-0005)."""
    r = ev.get("refs") or {}
    bits = []
    for key in ("plan", "phase", "session"):
        if r.get(key):
            bits.append(f"{key}:{r[key]}")
    for key, prefix in (("adr", "adr:"), ("issue", "issue:#")):
        vals = r.get(key) or []
        if isinstance(vals, str):
            vals = [vals]
        bits.extend(f"{prefix}{v}" for v in vals)
    bits.extend(f"path:{p}" for p in (ev.get("paths") or []))
    return "  ↳ " + " ".join(bits) if bits else ""


def state_link(p, root: Path) -> str:
    """Render a path for a link inside STATE.md: relative to the root, POSIX.

    STATE.md is generated AND tracked, so a machine path in it is committed.
    Making every path flag resolve against `--root` was right for reading and
    wrong for writing: `state render --root <absolute>` then wrote that absolute
    root back out inside the Registers links, and cozycode's ADR-0002 guard
    refused the commit. The flag's whole purpose is to be called from elsewhere,
    so "pass a relative root" is not a fix.

    This docstring carries no example of the bad output on purpose. A file that
    is vendored into other repositories must itself pass their absolute-path
    guards, and the first draft of this comment did not.

    POSIX separators for the same reason: the render must be byte-identical on
    Windows and macOS or the file conflicts every time it crosses machines.
    """
    q = Path(p)
    try:
        return q.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        # Genuinely outside the root. Leave it alone rather than emit `../..`.
        return q.as_posix()


def render_state(root: Path, projected: dict, adr_dir: Path,
                 specs: str, journal: Path, origin, project: str | None = None) -> str:
    ok_b, branch = git(root, "rev-parse", "--abbrev-ref", "HEAD")
    ok_s, sha = git(root, "rev-parse", "--short", "HEAD")
    # Deterministic: stamp the newest EVENT, never the run time, so re-rendering
    # unchanged inputs is byte-identical (the same rule `index` follows).
    newest = max((e.get("ts", "") for lst in projected.values() for e in lst), default="")
    lines = [f"# {project or root.resolve().name} — State", "",
             f"<!-- {STATE_GENERATED_MARKER} from docs/state.ndjson.",
             "     Do not hand-edit: append with `plan_tool state add`, then re-render.",
             "     History lives in the log; this file is the current view. -->", "",
             "| Sync | |", "|---|---|",
             f"| Last synced | {newest or '(no events)'} |",
             f"| Repo state | {branch if ok_b else '?'} @ {sha if ok_s else '?'} |"]
    if origin:
        ok_c, counts = git(root, "rev-list", "--left-right", "--count", f"{origin}...HEAD")
        if ok_c and counts:
            behind, ahead = (counts.split() + ["?", "?"])[:2]
            lines.append(f"| Vs {origin} | {behind} behind, {ahead} ahead |")
    lines.append("")

    def section(title: str, kind: str, fmt) -> None:
        items = projected.get(kind, [])
        lines.extend([f"## {title}", ""])
        if not items:
            lines.extend(["_none recorded_", ""])
            return
        for ev in items:
            lines.append(fmt(ev))
            rl = refs_line(ev)
            if rl:
                lines.append(rl)
        lines.append("")

    section("Current Working State", "claim", lambda e: (
        f"- {e.get('what', '')} — verified by `{e.get('proof', '')}` "
        f"({e.get('date', '')}{', ' + e['sha'] if e.get('sha') else ''})"))
    section("In Development", "indev", lambda e: (
        f"- {e.get('what', '')} — {e.get('status', 'in-development')}"
        + (f" · {e['owner']}" if e.get("owner") else "")))
    section("Known Gaps / Risks", "gap", lambda e: f"- {e.get('what', '')}")

    specs_l, adr_l = state_link(specs, root), state_link(adr_dir, root)
    lines.extend(["## Registers", "",
                  f"- **Plans** — [{specs_l}/_index.html]({specs_l}/_index.html)",
                  f"- **Decisions (ADRs)** — [{adr_l}/]({adr_l}/)"])
    # Derived, so the register cannot drift from the directory — the drift
    # `state check` caught by hand is now impossible by construction.
    if adr_dir.is_dir():
        for f in sorted(adr_dir.glob("*.md")):
            m = ADR_FILE_RE.match(f.name)
            if not m:
                continue
            title = next((ln[7:].strip() for ln in read(f).split("\n")
                          if ln.startswith("title: ")), "")
            lines.append(f"  - ADR-{m.group('num')} — {title or f.stem}")
    journal_l = state_link(journal, root)
    lines.extend(["- **Components** — [SYSTEM.md](SYSTEM.md)",
                  f"- **Ledger** — [{journal_l}]({journal_l})", ""])
    return "\n".join(lines).rstrip() + "\n"



def migrate_state(text: str, who: str) -> tuple[list[dict], list[str]]:
    """Parse a hand-authored STATE.md into events, plus a list of what could not be
    carried. Honest by construction: it never invents a field the old format has no
    source for (ADR-0005)."""
    events: list[dict] = []
    lost: list[str] = []

    def ev(kind: str, what: str, **extra) -> None:
        e = {"kind": kind, "key": what[:60], "what": what, "by": who,
             "ts": extra.pop("ts", None) or now_iso()}
        e["date"] = e["ts"][:10]
        e.update({k: v for k, v in extra.items() if v})
        events.append(e)

    for ln in section_body(text, "Current Working State").splitlines():
        m = STATE_CLAIM_RE.match(ln.strip())
        if not m:
            continue
        mw = STATE_WHEN_RE.match(m.group("when").strip())
        date = mw.group("date") if mw else ""
        # No sha is left absent, never back-filled to HEAD: that would assert a proof
        # ran at a commit where it never ran, and check_state would then report a
        # staleness distance computed from a fiction.
        sha = mw.group("sha") if mw else ""
        ev("claim", m.group("what").strip(), proof=m.group("cmd").strip(), sha=sha,
           ts=f"{date}T00:00:00" if date else None)

    for ln in section_body(text, "In Development").splitlines():
        ln = ln.strip()
        if not ln.startswith("|") or re.match(r"^\|[\s|:-]+\|$", ln):
            continue
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if len(cells) < 2 or cells[0].lower() in ("item", ""):
            continue
        item, typ = cells[0], cells[1] if len(cells) > 1 else ""
        status = cells[2] if len(cells) > 2 else ""
        owner = cells[3] if len(cells) > 3 else ""
        record = cells[4] if len(cells) > 4 else ""
        refs = {}
        adrs = re.findall(r"(?:ADR-|adr/)(\d{4})", record)
        if adrs:
            refs["adr"] = adrs
        elif record and record not in ("-", "—"):
            lost.append(f"In Development record link, no id to key on: {record}")
        ev("indev", item, status=status, owner=owner, refs=refs or None)
        if typ and typ not in ("-", "—"):
            lost.append(f"In Development Type column has no event field: {item} ({typ})")

    for heading in ("Known Gaps / Risks", "Known Gaps", "Gaps / Risks"):
        body = section_body(text, heading)
        if body:
            for ln in body.splitlines():
                ln = ln.strip()
                if ln.startswith("- ") and "{{" not in ln:
                    ev("gap", ln[2:].strip())
            break

    if section_body(text, "How to Run / Verify").strip():
        lost.append("the `## How to Run / Verify` block — no event kind and no rendered "
                    "section; copy it into CLAUDE.md or a README before re-rendering")
    if re.search(r"^\|\s*Synced by\s*\|", text, re.M):
        lost.append("the `Synced by` row — the schema has no email field and `by` is "
                    "never rendered; migrated events are attributed to you")
    if events:
        lost.append("paths on every claim — no source in the old format, so the "
                    "path-intersection sync trigger cannot fire for migrated claims")
    return events, lost


CLAUDE_MD_STUB = """# {name}

<!-- Written by `plan_tool init`. This is a stub: replace the placeholders with
     what is actually true of this repo. A clone's entry point is only worth the
     accuracy of what it says. -->

## Project state

Start here, in this order. Each answers a different question.

| Read | To answer |
| --- | --- |
| `STATE.md` | Where the project left off, and what is verified working right now |
| `docs/adr/` | Why the system is built this way |
| `docs/journal.md` | The append-only history of who changed what and why |

`STATE.md` is **generated** by `plan_tool state render` from `docs/state.ndjson`.
Never hand-edit it: append an event with `plan_tool state add`, then re-render.

## First session in a fresh clone

`.git/hooks` is never cloned, so a clone arrives with the tracked hooks present and
inactive. Git refuses to let a clone set its own config, which is a security property,
not an oversight — so this one step cannot be automated away, only done for the human.

At the start of a session in a clone you did not wire yourself, run `plan_tool doctor`.
If it reports `git hooks  core.hooksPath unset`, run `plan_tool hooks git-install` once.
Both commands are idempotent, and `doctor` reports the result rather than assuming it.

Skipping this is safe. The hooks only inject commit trailers, which makes history
answer "why was it built this way" further back. Without them the derived reports get
thinner, never wrong (ADR-0004).
{vendor_note}
## Agent skills

### Issue tracker

See `docs/agents/issue-tracker.md`.
"""

GITATTRIBUTES_STANZA = """
# Append-only state event log (ADR-0005): union-merge so concurrent appends
# from different sessions and agents combine instead of conflicting.
docs/state.ndjson merge=union
"""



def state_log_union_merged(root: Path) -> bool:
    """Ask git, never the file: the attribute can come from .git/info/attributes or a
    parent directory, so string-matching .gitattributes both misses and duplicates."""
    ok, attr = git(root, "check-attr", "merge", "--", STATE_LOG_DEFAULT)
    return ok and attr.strip().endswith(": union")


def a_workflow_runs_state_check(root: Path) -> bool:
    wf = root / ".github" / "workflows"
    if not wf.is_dir():
        return False
    return any("state check" in read(f) or "state_check" in read(f)
               for f in sorted(list(wf.glob("*.yml")) + list(wf.glob("*.yaml"))))


def strip_example_rows(text: str) -> str:
    """Drop a template's illustrative table rows. A fresh repo that ships a map of
    fictional components is the confident-wrong-answer failure SYSTEM.md's own footer
    warns about: a reader stops at the table instead of reading the code."""
    out: list[str] = []
    in_table = False
    for ln in text.splitlines():
        if re.match(r"^\|[\s|:-]+\|\s*$", ln):          # the header separator
            cols = ln.count("|") - 1
            out.append(ln)
            out.append("| _none recorded yet_ " + "| " * (cols - 1) + "|")
            in_table = True
            continue
        if in_table and ln.startswith("|"):
            continue                                       # an example row
        in_table = False
        out.append(ln)
    return "\n".join(out) + "\n"

def cmd_init(args) -> int:
    """Wire a repo for cozyplan: everything `doctor` checks that a command can
    legitimately create. Idempotent and additive — every write is create-if-absent
    or append-if-missing, never a truncation, so brownfield is the normal case
    rather than a special one."""
    root = Path(args.root)
    # Before anything is written or removed. The two failures this prevents both
    # damage the repo on the way to reporting, so a check placed after the copy
    # would be describing wreckage rather than preventing it.
    if args.vendor:
        problem = vendor_source_problem(root)
        if problem:
            return fail("refusing --vendor: " + problem)
    in_git, _ = git(root, "rev-parse", "--is-inside-work-tree")
    if not in_git:
        if not args.git_init:
            return fail(f"{root} is not a git repository — every layer below is wired "
                        f"through git. Run `git init` first, or pass --git-init.")
        ok, _ = git(root, "init")
        if not ok:
            return fail(f"git init failed in {root}")

    made: list[str] = []
    kept: list[str] = []
    # Rewritten every run by design (they re-point a moved interpreter), so they are
    # neither created nor left alone. Reporting them as "created" on a re-run would be
    # a small lie in a tool whose entire value is that its reports are true.
    refreshed: list[str] = []
    manual: list[str] = []

    def ensure_dir(rel: str) -> None:
        d = root / rel
        (kept if d.is_dir() else made).append(rel)
        d.mkdir(parents=True, exist_ok=True)

    def ensure_file(rel: str, body: str) -> None:
        f = root / rel
        if f.exists():
            kept.append(rel)
            return
        f.parent.mkdir(parents=True, exist_ok=True)
        write(f, body)
        made.append(rel)

    def ensure_from_template(rel: str, template: str, subs: "dict[str, str] | None" = None) -> None:
        f = root / rel
        if f.exists():
            kept.append(rel)
            return
        src = resolve_template(template)
        if src is None:
            manual.append(f"{rel} — template `{template}` not found beside this script; "
                          f"create it by hand")
            return
        text = read(src)
        for k, v in (subs or {}).items():
            text = text.replace(k, v)
        f.parent.mkdir(parents=True, exist_ok=True)
        write(f, text)
        made.append(rel)

    # ── vendoring: the repo carries the skill, so a teammate installs nothing ──
    if args.vendor:
        skill_root = Path(__file__).resolve().parent.parent      # <skills>/cozyplan
        src_dir = skill_root.parent                              # <skills>
        dest_dir = root / ".claude" / "skills"
        if src_dir.resolve() == (root / "skills").resolve():
            manual.append(".claude/skills — this repo IS the skill source; vendoring it into "
                          "itself would duplicate it. Run --vendor in the consuming repo.")
        else:
            for name in ("cozyplan", "discuss"):
                src = src_dir / name
                dst = dest_dir / name
                if not src.is_dir():
                    manual.append(f".claude/skills/{name} — not found at {src}")
                    continue
                existed = dst.exists()
                if existed:
                    shutil.rmtree(dst)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(src, dst,
                                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".venv*"))
                (refreshed if existed else made).append(f".claude/skills/{name}")
            # What was vendored, and from where. A consuming repo cannot see upstream,
            # so the only honest drift signal is a recorded origin a human can compare.
            ver = ""
            for cand in (src_dir.parent / ".claude-plugin" / "plugin.json",):
                if cand.exists():
                    with contextlib.suppress(Exception):
                        ver = json.loads(read(cand)).get("version", "")
            ok_sha, sha = git(src_dir.parent, "rev-parse", "--short", "HEAD")
            # The remote, not only the local path. `vendored from` is one machine's
            # absolute path, which tells a teammate nothing and cannot be compared
            # against anything from their clone. The remote is the same string
            # everywhere, so `doctor` can find a local checkout of it and report how
            # far behind this copy has drifted.
            ok_rem, src_remote = git(src_dir.parent, "remote", "get-url", "origin")
            write(dest_dir / "VENDORED.md",
                  "# Vendored cozyplan\n\n"
                  "These skills are committed into this repo so a clone needs no install.\n"
                  "Do not hand-edit them: re-vendor with `plan_tool init --vendor` from a\n"
                  "newer cozyplan, and review the diff.\n\n"
                  f"| Field | Value |\n| --- | --- |\n"
                  f"| version | {ver or 'unknown'} |\n"
                  f"| source commit | {sha if ok_sha else 'unknown'} |\n"
                  f"| source remote | {src_remote.strip() if ok_rem and src_remote.strip() else 'unknown'} |\n\n"
                  "`plan_tool doctor` compares the source commit above against upstream when it\n"
                  "can reach a checkout of the remote, and says so plainly when it cannot —\n"
                  "a copy that is merely old looks identical to a current one otherwise.\n\n"
                  "Every field here is the same on every machine. The path to a local cozyplan\n"
                  "checkout is not, so it lives in this clone's git config as `cozyplan.source`\n"
                  "rather than in a tracked file.\n")
            # The local checkout path goes in git config: per-clone, untracked, and
            # correct on exactly the machine it describes. It used to be written into
            # VENDORED.md, where it was wrong for everyone else — a consuming repo
            # deleted it by hand as an absolute path in a tracked file, and the next
            # re-vendor put it straight back, which is what generated files do.
            git(root, "config", "cozyplan.source", str(src_dir.parent))
            made.append(".claude/skills/VENDORED.md")

    # ── records and the event log ────────────────────────────────────────────
    ensure_dir("docs/adr")
    ensure_file(STATE_LOG_DEFAULT, "")
    ensure_from_template("docs/journal.md", "journal.md")

    slug = (args.repo or "").strip()
    if not slug:
        ok_rem, remote = git(root, "remote", "get-url", "origin")
        if ok_rem and remote:
            m = re.search(r"[:/]([^/:]+/[^/]+?)(?:\.git)?$", remote.strip())
            slug = m.group(1) if m else ""
    if slug:
        ensure_from_template("docs/agents/issue-tracker.md", "issue-tracker.md",
                             {"{{REPO_SLUG}}": slug})
    elif (root / "docs/agents/issue-tracker.md").exists():
        kept.append("docs/agents/issue-tracker.md")
    else:
        manual.append("docs/agents/issue-tracker.md — no `origin` remote, so the repo slug "
                      "cannot be filled in. Re-run with `--repo <owner>/<name>`, add a remote, "
                      "or write the file by hand. A guessed slug would point every issue "
                      "command at someone else's repo.")

    # ── union merge: ask git, not the file. The attribute can come from
    #    .git/info/attributes or a parent dir, and appending blindly duplicates it.
    if state_log_union_merged(root):
        kept.append(".gitattributes (merge=union)")
    else:
        ga = root / ".gitattributes"
        existing = read(ga) if ga.exists() else ""
        write(ga, (existing.rstrip("\n") + "\n\n" if existing.strip() else "") + GITATTRIBUTES_STANZA.lstrip("\n"))
        made.append(".gitattributes (merge=union)")

    # The gh-less queue holds intended issues, not repo content (ADR-0001), so a
    # fresh repo should not commit it.
    gi = root / ".gitignore"
    gi_text = read(gi) if gi.exists() else ""
    if re.search(r"^\.scratch/?\s*$", gi_text, re.M):
        kept.append(".gitignore (.scratch/)")
    else:
        write(gi, (gi_text.rstrip("\n") + "\n\n" if gi_text.strip() else "")
              + "# Queued work items awaiting `gh` (ADR-0001) — replayed, never versioned.\n"
              + ".scratch/\n")
        made.append(".gitignore (.scratch/)")

    # ── CI ───────────────────────────────────────────────────────────────────
    if a_workflow_runs_state_check(root):
        kept.append(".github/workflows (a workflow already runs state check)")
    else:
        ensure_from_template(".github/workflows/state-check.yml", "state-check.yml")

    # ── git hooks. A foreign core.hooksPath means another manager owns them;
    #    overwriting it silently is the one genuinely destructive move here.
    ok_hp, hooks_path = git(root, "config", "core.hooksPath")
    foreign = ok_hp and hooks_path.strip() and hooks_path.strip() != args.hooks_dir
    if foreign and not args.force_hooks:
        manual.append(f"core.hooksPath is already set to `{hooks_path.strip()}` — another hook "
                      f"manager owns this repo. Re-run with --force-hooks to take it over, "
                      f"or install the commit-msg trailer hook into that manager by hand")
    else:
        ns = argparse.Namespace(hooks_cmd="git-install", root=args.root, dir=args.hooks_dir)
        if cmd_hooks_git(ns) == 0:
            refreshed.append(f"{args.hooks_dir}/ + core.hooksPath")

    # ── Claude Code hooks (advisory layer; bare-skill installs need this) ────
    if args.claude_hooks:
        # root matters: it is what lets the registration be written against
        # ${CLAUDE_PROJECT_DIR} instead of this machine's absolute paths. `init`
        # wires a repo other people will clone, so this is the case that most
        # needs a settings.json that is correct on a machine it has never seen.
        ns = argparse.Namespace(hooks_cmd="install", settings=str(root / ".claude" / "settings.json"),
                                global_=False, root=str(root))
        if cmd_hooks(ns) == 0:
            refreshed.append(".claude/settings.json (guard + lint hooks)")
        else:
            manual.append(".claude/settings.json — hook registration failed; run "
                          "`plan_tool hooks install` and read the error")

    # SYSTEM.md answers "what breaks if I change this" (ADR-0003), and the README
    # routes two of the four questions at it. Nothing created it, so every repo shipped
    # a dead link — including the generated STATE.md's own Registers block.
    if (root / "SYSTEM.md").exists():
        kept.append("SYSTEM.md")
    else:
        src = resolve_template("system.md", skill="discuss")
        if src is None:
            manual.append("SYSTEM.md — the discuss skill's templates/system.md was not found "
                          "beside this script; copy it by hand")
        else:
            write(root / "SYSTEM.md", strip_example_rows(read(src)))
            made.append("SYSTEM.md")

    # ── entry point ──────────────────────────────────────────────────────────
    if (root / "CLAUDE.md").exists() or (root / "AGENTS.md").exists():
        kept.append("CLAUDE.md / AGENTS.md")
    else:
        vendor_note = ("\nNothing else needs installing: the cozyplan and discuss skills are "
                       "committed\nunder `.claude/skills/`, and `plan_tool.py` ships inside them. "
                       "See\n`.claude/skills/VENDORED.md` for the version this repo carries.\n"
                       if args.vendor else "")
        ensure_file("CLAUDE.md", CLAUDE_MD_STUB.format(name=root.resolve().name,
                                                       vendor_note=vendor_note))

    # ── STATE.md last: render refuses to overwrite an authored snapshot, which
    #    is exactly the behaviour we want here, so route the user to migrate.
    state_file = root / "STATE.md"
    if state_file.exists():
        if STATE_GENERATED_MARKER in read(state_file):
            kept.append("STATE.md (generated)")
        else:
            manual.append("STATE.md exists but was authored by hand — run "
                          "`plan_tool state migrate` to carry it into the event log, "
                          "then `plan_tool state render`")
    else:
        ns = argparse.Namespace(state_cmd="render", root=args.root, log=STATE_LOG_DEFAULT,
                                file=str(state_file), adr_dir=str(root / "docs" / "adr"),
                                specs=args.specs, journal=str(root / "docs" / "journal.md"),
                                origin=None, project=None, force=False, dry_run=False)
        if cmd_state(ns) == 0:
            made.append("STATE.md")

    # ── report ───────────────────────────────────────────────────────────────
    print(f"\ncozyplan init — {root.resolve()}\n")
    for title, items in (("created", made), ("refreshed (rewritten every run)", refreshed),
                         ("already present, left alone", kept)):
        if items:
            print(f"  {title}:")
            for i in items:
                print(f"    - {i}")
    # Steps no command can do are named, never faked (ADR-0004).
    rows = doctor_checks(root, 20)
    checks = {name: (status, detail) for _, status, name, detail in rows}
    for name in ("identity", "remote", "gh", "required check"):
        if name in checks and checks[name][0] != OK:
            manual.append(f"{name} — {checks[name][1]}")
    if manual:
        print("\n  needs a human:")
        for i in manual:
            print(f"    - {i}")
    gaps = [(n, d) for _, st, n, d in rows if st == GAP]
    print(f"\n  {len(gaps)} gap(s) remain — run `plan_tool doctor` for the full picture.")
    return 0


# ── issue filing, with a queue for when gh is absent ──────────────────────────
# ADR-0001 made GitHub the source of truth for work items and promised that a
# gh-less session queues rather than forking that truth into files. That promise
# lived only in prose for a release. An agent told in markdown to "write the body
# to .scratch/ and append the command" follows it approximately, which is the same
# reason every other structured write in this tool is a command.

SCRATCH_DIR = ".scratch"
QUEUE_SCRIPT_HEADER = """#!/bin/sh
# cozyplan: issues intended while `gh` was unavailable (ADR-0001).
# Replay with `plan_tool issue replay --run`, or run this file directly.
set -e
"""


def gh_ready() -> bool:
    """gh installed AND authenticated. Installed-but-logged-out fails at the API
    call, so treating it as ready would lose the issue instead of queueing it."""
    if not shutil.which("gh"):
        return False
    try:
        return subprocess.run([which_exe("gh"), "auth", "status"], capture_output=True,
                              stdin=subprocess.DEVNULL,
                              timeout=30).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def slugify(text: str) -> str:
    out = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (out[:50].rstrip("-") or "issue")


def queue_issue(root: Path, title: str, body: str, labels: list, plan: str) -> tuple:
    """Write the intended issue body to its own file and append a one-line gh command
    that reads it with --body-file. Inlining the body would put newlines inside the
    queued command, so the script stops being one-command-per-line and stops being
    listable, and the body would live in two places that can disagree.
    Returns (body_path, script_path)."""
    scratch = root / SCRATCH_DIR
    pending = scratch / "pending-issues"
    pending.mkdir(parents=True, exist_ok=True)
    slug = slugify(title)
    body_path = pending / f"{slug}.md"
    n = 2
    while body_path.exists():
        body_path = pending / f"{slug}-{n}.md"
        n += 1
    text = body.rstrip("\n")
    if plan:
        text = f"{text}\n\nPlan: {plan}".strip("\n")
    write(body_path, text + "\n")

    rel = body_path.relative_to(root) if body_path.is_relative_to(root) else body_path
    # as_posix(), not str(): this line is replayed through `sh -c`, and a Windows
    # backslash path is eaten as escape characters there — the queued command would
    # name a file that does not exist, on the one path where nothing re-checks it.
    argv = ["gh", "issue", "create", "--title", title, "--body-file", rel.as_posix()]
    for lb in labels:
        argv += ["--label", lb]
    script = scratch / "pending-gh.sh"
    existing = read(script) if script.exists() else QUEUE_SCRIPT_HEADER
    write(script, existing.rstrip("\n") + "\n" + " ".join(shlex.quote(a) for a in argv) + "\n")
    script.chmod(0o755)
    return body_path, script


def queued_commands(root: Path) -> list:
    script = root / SCRATCH_DIR / "pending-gh.sh"
    if not script.exists():
        return []
    return [ln for ln in read(script).splitlines()
            if ln.strip().startswith("gh ")]


def cmd_issue(args) -> int:
    root = Path(args.root)
    if args.issue_cmd == "file":
        if not args.title:
            return fail("--title is required")
        labels = [l.strip() for l in (args.label or "").split(",") if l.strip()]
        body = args.body or ""
        if args.plan:
            body = f"{body}\n\nPlan: {args.plan}".strip("\n")
        if gh_ready() and not args.queue:
            argv = [which_exe("gh"), "issue", "create", "--title", args.title, "--body", body]
            for lb in labels:
                argv += ["--label", lb]
            r = subprocess.run(argv, cwd=str(root), capture_output=True, text=True,
                               stdin=subprocess.DEVNULL)
            if r.returncode == 0:
                print(f"issue: filed {r.stdout.strip()}")
                return 0
            # Never drop it. A failed create is exactly when the queue earns its place.
            print(f"  warn: gh issue create failed ({r.stderr.strip()[:120]}); queueing instead")
        bp, sp = queue_issue(root, args.title, args.body or "", labels, args.plan or "")
        print(f"issue: queued -> {bp}")
        print(f"       replay with `plan_tool issue replay --run` once gh is available ({sp})")
        return 0

    if args.issue_cmd == "replay":
        cmds = queued_commands(root)
        if not cmds:
            print("issue: nothing queued")
            return 0
        if not args.run:
            # Filing issues is outward-facing and hard to undo, so the default is to
            # show the queue rather than to fire it.
            print(f"issue: {len(cmds)} queued — pass --run to file them")
            for c in cmds:
                print(f"  {c}")
            return 0
        if not gh_ready():
            return fail("gh is not installed or not authenticated — nothing was replayed")
        script = root / SCRATCH_DIR / "pending-gh.sh"

        def rewrite(pending: list) -> None:
            write(script, QUEUE_SCRIPT_HEADER + ("\n".join(pending) + "\n" if pending else ""))

        # One command at a time, and the queue is rewritten after each success. Running
        # the whole script and leaving it untouched on failure meant the commands that
        # already succeeded stayed queued, so the next --run filed them a second time —
        # duplicates in the tracker ADR-0001 made the source of truth.
        pending = list(cmds)
        for cmd in cmds:
            # shlex.split, not `sh -c`: Windows has no sh unless Git Bash happens to
            # be on PATH, which made replay a POSIX-only command while looking portable.
            # Every queued line is `shlex.quote`d argv from queue_issue, and quote/split
            # are inverses — so this runs exactly what was queued, and without a shell
            # there is no line for a title with a backtick in it to escape into.
            try:
                argv_cmd = shlex.split(cmd)
            except ValueError as e:
                rewrite(pending)
                return fail(f"replay stopped: cannot parse queued command ({e}): {cmd}")
            argv_cmd = [which_exe(argv_cmd[0])] + argv_cmd[1:]
            # Every stream is explicit — none inherited. gh reads no stdin when it is
            # fully argumented, and a parent whose stdout handle another child already
            # invalidated would otherwise turn the whole replay into WinError 6 at
            # Popen. Capturing costs the streaming view of one URL per issue and buys
            # a failure message that can name what gh actually said.
            r = subprocess.run(argv_cmd, cwd=str(root), stdin=subprocess.DEVNULL,
                               capture_output=True, text=True)
            if r.stdout.strip():
                print(f"  {r.stdout.strip()}")
            if r.returncode != 0:
                rewrite(pending)
                why = (r.stderr or r.stdout or "").strip().splitlines()
                return fail(f"replay stopped at a failing command; {len(pending)} still "
                            f"queued in {script}. The ones already filed were removed."
                            + (f"\n  gh said: {why[-1][:200]}" if why else ""))
            pending.pop(0)
            rewrite(pending)
        print(f"issue: replayed {len(cmds)} queued issue(s); {script} reset")
        return 0
    return fail(f"unknown issue command: {args.issue_cmd}")

def cmd_state(args) -> int:
    root = Path(args.root)
    log_path = under(root, args.log)

    if args.state_cmd == "add":
        if not args.what:
            return fail("--what is required")
        # `render_state` writes the proof inside backticks and STATE_CLAIM_RE reads
        # it back with [^`]+, so a backtick in the proof produces a line that cannot
        # be parsed. `state check` then reports "claim does not name its proof",
        # which is true of the LINE and false of the claim -- the work was done and
        # the recording is unreadable. Refused here rather than stripped: the log is
        # append-only, so a silently altered proof is wrong forever, and quietly
        # recording something the operator did not write is the failure this whole
        # layer exists to prevent. A newline does the same thing to a one-line entry.
        for field in ("what", "proof"):
            val = getattr(args, field, None) or ""
            bad = next((c for c in ("`", "\n", "\r") if c in val), None)
            if bad:
                shown = {"`": "a backtick", "\n": "a newline", "\r": "a carriage return"}[bad]
                return fail(f"--{field} contains {shown}, which STATE.md cannot render "
                            f"as one parseable line. Rewrite it without that character "
                            f"-- name the command in plain text.")
        _, who = git(root, "config", "user.name")
        ev = {"kind": args.kind, "key": args.key or args.what[:60], "what": args.what,
              "by": who or "",
              "ts": args.ts or datetime.now().astimezone().isoformat(timespec="seconds")}
        # The proof date is the event's own date — one field, never disagreeing
        # with the timestamp beside it.
        ev["date"] = ev["ts"][:10]
        for name in ("proof", "sha", "status", "owner"):
            if getattr(args, name, None):
                ev[name] = getattr(args, name)
        if args.paths:
            ev["paths"] = [p.strip() for p in args.paths.split(",") if p.strip()]
        refs = {n: getattr(args, n) for n in ("plan", "phase", "session") if getattr(args, n, None)}
        if args.adr:
            refs["adr"] = [a.strip() for a in args.adr.split(",") if a.strip()]
        if args.issue:
            refs["issue"] = [i.strip().lstrip("#") for i in args.issue.split(",") if i.strip()]
        if refs:
            ev["refs"] = refs
        if args.clear:
            ev["cleared"] = True
            # A clear only does anything if some earlier event carries the same key,
            # and keys are derived by truncating `--what`, so they are easy to get
            # subtly wrong. Appending a clear for a key nothing matches is a no-op
            # that printed "(cleared)" and looked exactly like a successful one —
            # a command reporting an outcome it never observed, which is the whole
            # of ADR-0010. It happened three times in one session before this.
            # Only keys an event actually SET. A previous mistyped clear is itself in
            # the log, so counting clears would let one typo validate the next.
            known = {e.get("key") for e in read_state_log(root, log_path)
                     if e.get("key") and not e.get("cleared")}
            if ev["key"] not in known:
                near = [k for k in sorted(known)
                        if k and (k.startswith(ev["key"][:20]) or ev["key"].startswith(k[:20]))]
                msg = (f"nothing to clear: no earlier event has key {ev['key']!r}. "
                       f"Keys are derived from --what and truncated, so pass --key exactly.")
                if near:
                    msg += "\n  did you mean:\n" + "\n".join(f"    {k!r}" for k in near[:3])
                return fail(msg)
        # A missing root is refused rather than created. mkdir(parents=True)
        # used to fabricate a whole ledger at a stale path and report success, so
        # the claim landed where nobody reads and the real ledger got nothing --
        # a false positive, which is worse than a failure. The log's own parent is
        # still created, because docs/ legitimately does not exist yet on the
        # first claim in a repository.
        if not root.is_dir():
            return fail(f"--root {root} does not exist, so nothing was recorded. "
                        f"A recorded path is a fact about the machine on the day "
                        f"it was recorded; re-point it rather than create it.")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(ev, ensure_ascii=False, sort_keys=True) + "\n")
        print(f"state: appended {args.kind} '{ev['key']}'"
              + (" (cleared)" if args.clear else "") + f" -> {log_path}")
        return 0

    if args.state_cmd == "migrate":
        src = under(root, args.file)
        if not src.exists():
            return fail(f"state file not found: {src}")
        text = read(src)
        if STATE_GENERATED_MARKER in text:
            print(f"state: {src} is already generated — nothing to migrate")
            return 0
        _, who = git(root, "config", "user.name")
        events, lost = migrate_state(text, who or "")
        if not events:
            return fail(f"{src} has no recognisable claims, In Development rows, or gaps "
                        f"— migrate it by hand with `plan_tool state add`")
        backup = src.with_name(src.name + ".pre-migration")
        if not args.dry_run and backup.exists():
            return fail(f"{backup} already exists — migration has already run here. "
                        f"Move it aside first if you really mean to migrate again.")
        if args.dry_run:
            for e in events:
                print(json.dumps(e, ensure_ascii=False, sort_keys=True))
        else:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "a", encoding="utf-8", newline="\n") as f:
                for e in events:
                    f.write(json.dumps(e, ensure_ascii=False, sort_keys=True) + "\n")
            # The old file is set aside rather than left in place: leaving it would
            # deadlock the user between migrate and render's guard, and the sections
            # that could not be carried are only recoverable from it.
            src.rename(backup)
            print(f"state: migrated {len(events)} entr(ies) from {src} -> {log_path}")
            print(f"       kept the original at {backup}")
        # Never silently. Everything the old format could not express is named here,
        # because a migration that reports nothing reads as a migration that lost nothing.
        if lost:
            print("\nnot carried over — handle these by hand:")
            for item in lost:
                print(f"  - {item}")
        if not args.dry_run:
            print(f"\nnext: review the log, then `plan_tool state render` to write a "
                  f"fresh {src.name}. Delete {backup.name} once you have salvaged "
                  f"anything above.")
        return 0

    if args.state_cmd in ("render", "show"):
        projected = project_state(read_state_log(root, log_path))
        if args.state_cmd == "show":
            for kind in STATE_KINDS:
                items = projected[kind]
                print(f"{kind} ({len(items)}):")
                for ev in items:
                    print(f"  {ev.get('what', '')}")
            return 0
        out = under(root, args.file)
        # render TRUNCATES. A STATE.md without the marker was written by hand (or by
        # a pre-3.0 cozyplan), and rendering over it destroys every claim, gap, and
        # the How to Run block with no error and exit 0 — and `state check` then
        # passes on the emptied file, so no later layer catches it either. Refuse by
        # default: the users at risk are exactly those who do not know the semantics
        # changed, so an opt-in flag would not protect them.
        if out.exists() and not args.force and STATE_GENERATED_MARKER not in read(out):
            return fail(
                f"{out} was not generated by `state render` — it has no generated marker, "
                f"so rendering would overwrite hand-authored content.\n"
                f"       Migrate it first:  plan_tool state migrate --file {out}\n"
                f"       Or discard it:     plan_tool state render --force")
        rendered = render_state(root, projected, under(root, args.adr_dir),
                                str(under(root, args.specs)), under(root, args.journal),
                                args.origin, args.project)
        if args.dry_run:
            print(rendered, end="")
            return 0
        write(out, rendered)
        n = sum(len(v) for v in projected.values())
        print(f"state: rendered {out} from {n} projected entr(ies)")
        return 0

    state_path = under(root, args.file)
    if not state_path.exists():
        return fail(f"state file not found: {state_path} - run the Init State workflow first")
    problems, warns, notes = check_state(
        state_path, root, under(root, args.adr_dir), under(root, args.journal), args.max_drift,
        args.max_claim_age, log_path)
    for note in notes:
        print(f"  note: {note}")
    for w in warns:
        print(f"  warn: {w}")
    if problems:
        print(f"FAIL {state_path.name}: {len(problems)} problem(s)")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"OK {state_path.name}: consistent with git")
    return 0


# ── doctor (ADR-0004: wiring is observable) ──────────────────────────────────
# The failure this guards against is SILENT misconfiguration. hooks.json shipped
# a note saying "if uv is missing, enforcement silently disappears", and that is
# exactly what happened — for months, on any machine without uv. So doctor does
# not ask whether a hook is *registered*; it runs the interpreter that hook would
# use and reports whether it actually works.
#
# It never claims protection it cannot verify. Whether a CI check is *required*
# lives in GitHub branch protection, which is not visible from a clone, so doctor
# says so instead of implying a gate exists.

OK, WARN, GAP = "ok", "warn", "gap"
_MARK = {OK: "  ok  ", WARN: " warn ", GAP: " gap  "}



# A command named in prose but absent from the parser sends a reader (or an agent)
# to run something that does not exist. This drifted twice already: init-state.md and
# sync-state.md described the 2.x model for a whole release. Checking it is a grep.
_DOC_CMD_RE = re.compile(r"(?:^|`)(?:PLAN_TOOL|plan_tool(?:\.py)?)\s+([a-z][a-z0-9-]*)", re.M)


def subcommand_names() -> set:
    """The verbs the parser actually accepts, read off the parser itself so this can
    never disagree with it."""
    for act in build_parser()._actions:
        if isinstance(act, argparse._SubParsersAction):
            return set(act.choices)
    return set()


def header_command_drift() -> list:
    """(direction, verb) where this file's own `Commands:` block disagrees with the
    parser. The prose check below reads SKILL.md, workflows/, and reference/ — never
    this script — so the header was the one place drift could hide from it, and did."""
    known = subcommand_names()
    if not known:
        return []
    m = re.search(r"^Commands[^\n]*:\n(?P<body>(?:  \S.*\n)+)", __doc__ or "", re.M)
    if not m:
        return [("missing", "the Commands: block itself")]
    listed = set(re.findall(r"^  ([a-z][a-z0-9-]*)\s{2,}", m.group("body"), re.M))
    return ([("undocumented", v) for v in sorted(known - listed)]
            + [("stale", v) for v in sorted(listed - known)])


def doc_command_drift(skill_root: Path) -> list:
    """(file, verb) for every command named in the skill's prose that does not exist."""
    known = subcommand_names()
    if not known:
        return []
    docs = [skill_root / "SKILL.md"]
    for sub in ("workflows", "reference"):
        d = skill_root / sub
        if d.is_dir():
            docs.extend(sorted(d.glob("*.md")))
    out = []
    for f in docs:
        if not f.exists():
            continue
        for verb in set(_DOC_CMD_RE.findall(read(f))):
            if verb not in known:
                out.append((f.name, verb))
    return sorted(out)

def _hook_runner_parts() -> tuple[str, str]:
    """(executable, extra arg) for the hooks — kept as parts, never joined into one
    string. An interpreter path can contain spaces, and a hook that word-splits its
    runner fails open silently, which is the exact failure ADR-0004 exists to catch."""
    return ("uv", "run") if shutil.which("uv") else (sys.executable, "")


def _hook_runner() -> list[str]:
    """The same resolution the hooks use: prefer uv, fall back to this interpreter."""
    exe, arg = _hook_runner_parts()
    return [exe, arg] if arg else [exe]


def _stored_hook_runner(root: Path) -> "list[str] | None":
    """The runner this clone actually recorded, or None if it has not been wired.
    doctor must test this rather than its own resolution: they differ exactly when
    the clone is misconfigured, which is the case worth reporting."""
    ok, exe = git(root, "config", "cozyplan.runner")
    if not ok or not exe.strip():
        return None
    ok_arg, arg = git(root, "config", "cozyplan.runnerarg")
    return [exe.strip(), arg.strip()] if ok_arg and arg.strip() else [exe.strip()]


def _vendored_field(text: str, name: str) -> str:
    m = re.search(rf"\|\s*{re.escape(name)}\s*\|\s*([^|]+?)\s*\|", text)
    return m.group(1).strip() if m else ""


def _vendored_freshness(root: Path, vend_text: str) -> tuple[str, str, str, str]:
    """(section, status, name, detail) — how far behind upstream this copy is.

    A vendored copy is a snapshot pinned at a commit, and nothing about it changes
    when upstream moves, so a stale copy and a current one are byte-indistinguishable
    from inside the repo. That cost three separate incidents in one session: a
    rehearsal run against a copy that predated the fix being rehearsed, and a
    consuming repo twice carrying a plan_tool without the fixes it had itself asked
    for.

    Upstream is reachable from some machines and not others, so this reports what it
    could observe and names what it could not, rather than implying freshness it did
    not check (ADR-0010).
    """
    recorded = _vendored_field(vend_text, "source commit")
    remote = _vendored_field(vend_text, "source remote")

    if not recorded or recorded == "unknown":
        return ("adapter", WARN, "vendored freshness",
                "VENDORED.md records no source commit, so there is nothing to compare "
                "against — re-vendor from a git checkout to stamp one")

    # Where a local cozyplan checkout lives is machine-specific, so it is read from
    # this clone's git config, not from the tracked marker. `vendored from` is the
    # legacy field: still read so a repo vendored before this change keeps working,
    # never written. Guessing at likely locations would be worse than reporting
    # honestly that we did not look.
    ok_src, cfg_src = git(root, "config", "cozyplan.source")
    local = cfg_src.strip() if ok_src and cfg_src.strip() else _vendored_field(vend_text, "vendored from")
    src = Path(local) if local and local != "unknown" else None
    if src is None or not (src / ".git").exists():
        where = f" (recorded remote: {remote})" if remote and remote != "unknown" else ""
        return ("adapter", WARN, "vendored freshness",
                f"vendored at {recorded}; upstream is not reachable from this machine, "
                f"so staleness could not be checked{where}")

    ok_has, _ = git(src, "cat-file", "-e", f"{recorded}^{{commit}}")
    if not ok_has:
        return ("adapter", WARN, "vendored freshness",
                f"vendored at {recorded}, which the checkout at {src} does not contain "
                f"— it may be behind, or the copy came from elsewhere")
    ok_n, n = git(src, "rev-list", "--count", f"{recorded}..HEAD")
    if not ok_n or not n.strip().isdigit():
        return ("adapter", WARN, "vendored freshness",
                f"vendored at {recorded}; could not count commits since it")
    behind = int(n.strip())
    if behind == 0:
        return ("adapter", OK, "vendored freshness", f"current with {src} at {recorded}")
    return ("adapter", WARN, "vendored freshness",
            f"{behind} commit(s) behind {src} (vendored at {recorded}) — "
            f"re-vendor with `plan_tool init --root {root} --vendor`")


def doctor_checks(root: Path, commits: int) -> list[tuple[str, str, str, str]]:
    """(section, status, name, detail) for every wiring fact worth knowing."""
    out: list[tuple[str, str, str, str]] = []

    def add(section, status, name, detail=""):
        out.append((section, status, name, detail))

    # ── git ──────────────────────────────────────────────────────────────────
    in_git, _ = git(root, "rev-parse", "--is-inside-work-tree")
    if not in_git:
        add("git", GAP, "work tree", "not a git repository — nothing below can be wired")
        return out
    _, branch = git(root, "rev-parse", "--abbrev-ref", "HEAD")
    _, sha = git(root, "rev-parse", "--short", "HEAD")
    add("git", OK, "work tree", f"{branch} @ {sha}")

    ok_r, remote = git(root, "remote", "get-url", "origin")
    add("git", OK if ok_r else WARN, "remote",
        remote if ok_r else "no origin — GitHub-backed workflows have no target")

    _, name = git(root, "config", "user.name")
    _, email = git(root, "config", "user.email")
    if name and email:
        add("git", OK, "identity", f"{name} <{email}>")
    else:
        # A warn, not a gap: identity is attribution config, not wiring. It is
        # routinely unset on a CI runner, and failing --strict there would be a
        # false positive — the fastest way to teach a team to delete the check.
        add("git", WARN, "identity",
            "user.name/user.email unset — journal entries and ADR authorship land blank")

    # ── enforcement layering (ADR-0004) ──────────────────────────────────────
    # Two ways to be wired, and both count. A plugin install registers via the
    # bundled hooks/hooks.json and never writes settings.json, so checking only
    # settings.json reported "not registered" to every plugin user forever.
    def _registers_all(path: Path) -> bool:
        if not path.exists():
            return False
        try:
            blob = json.dumps(json.loads(read(path)))
        except (json.JSONDecodeError, ValueError):
            return False
        # Sourced from HOOK_MATCHERS rather than a hardcoded pair: a manifest
        # carrying half the hooks reporting "registered" is the same failure this
        # check exists to catch, and the pair went stale the moment a third landed.
        return all(Path(s).stem in blob for s in HOOK_MATCHERS)

    settings = root / ".claude" / "settings.json"
    via_settings = _registers_all(settings)
    plugin_manifest = active_plugin_hooks_json(root)
    via_plugin = _registers_all(plugin_manifest) if plugin_manifest else False
    # Deliberately labelled as a record, and deliberately never OK on its own.
    # `all 4 registered` printed as a healthy row is what let an inert hook layer
    # read as a working one; registration is a claim about a config file and says
    # nothing about whether any hook ran. The row below is the one that knows.
    add("enforcement", WARN if not (via_settings or via_plugin) else OK,
        "hooks registered",
        f"a record only — all {len(HOOK_MATCHERS)} listed in "
        + (".claude/settings.json" if via_settings else "the plugin manifest")
        if (via_settings or via_plugin)
        else "not registered — run `plan_tool hooks install` (advisory layer only)")

    # The outcome. Runs each hook against a payload it must react to, and reports
    # what was observed rather than what is configured (ADR-0010).
    if os.environ.get("COZYPLAN_SELFTEST"):
        add("enforcement", WARN, "hooks observed",
            "not evaluated — already inside a selftest (recursion guard)")
    else:
        observed, total, detail = _doctor_selftest(root)
        # A gap is reserved for the dangerous state: registered, and inert anyway.
        # That is the one that reads as protection while providing none. Nothing
        # registered is honest absence — the row above already says so, and it is
        # the normal condition on a CI runner, where a gap would fail --strict on
        # every run and teach the team to drop the flag.
        if not total:
            status = WARN
        elif observed == total:
            status = OK
        else:
            status = GAP
        add("enforcement", status, "hooks observed",
            f"{observed}/{total} produced the reaction they owe — {detail}" if total
            else f"nothing to observe — {detail}")

    # The check that matters: does the interpreter those hooks name actually run?
    tool = Path(__file__).resolve()
    stored = _stored_hook_runner(root)
    runner = stored or _hook_runner()
    # Run what the hook runs, not a proxy for it. `--help` passed happily while the
    # commit-msg hook was dead, because the break was in the runner, not the tool.
    try:
        r = subprocess.run(runner + [str(tool), "trailers", "--print", "--root", str(root)],
                           capture_output=True, text=True, timeout=30, cwd=str(root),
                           stdin=subprocess.DEVNULL)
        runs = r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        runs = False
    src = " (recorded by git-install)" if stored else " (not wired here; this is what it would use)"
    add("enforcement", OK if runs else GAP, "hook interpreter",
        f"`{' '.join(runner)}` runs the trailer path{src}" if runs
        else f"`{' '.join(runner)}` cannot run the trailer path{src} — hooks fail open, silently")

    ok_hp, hooks_path = git(root, "config", "core.hooksPath")
    if ok_hp and hooks_path:
        d = root / hooks_path
        n = len([f for f in d.iterdir() if f.is_file()]) if d.is_dir() else 0
        add("enforcement", OK if n else WARN, "git hooks",
            f"core.hooksPath={hooks_path} ({n} hook(s))" if n
            else f"core.hooksPath={hooks_path} but no hooks in it")
    else:
        add("enforcement", WARN, "git hooks",
            "core.hooksPath unset — .git/hooks is not cloned, so nothing is installed here")

    # WHICH plan_tool those hooks run. The row above counts files and never opens
    # one, so it passed while the hooks executed a plan_tool from another repo
    # entirely — a record, unlabelled, exactly what `hooks registered` was fixed
    # for. Both hooks open with `TOOL=$(git config ...) || exit 0`, so an unset or
    # dead path is a silent no-op on every machine but the one that wired it.
    ok_pt, plantool = git(root, "config", "cozyplan.plantool")
    plantool = plantool.strip() if ok_pt else ""
    if not plantool:
        add("enforcement", WARN, "git hook tool",
            "cozyplan.plantool unset — the git hooks exit 0 without running anything "
            "here; run `plan_tool hooks git-install`")
    else:
        target = (root / plantool) if not Path(plantool).is_absolute() else Path(plantool)
        inside = False
        with contextlib.suppress(OSError, ValueError):
            target.resolve().relative_to(root.resolve())
            inside = True
        if not target.exists():
            add("enforcement", GAP, "git hook tool",
                f"cozyplan.plantool={plantool} does not exist — both git hooks exit 0 "
                f"without running; re-run `plan_tool hooks git-install`")
        elif inside:
            add("enforcement", OK, "git hook tool", f"{plantool} (inside this repo)")
        else:
            add("enforcement", WARN, "git hook tool",
                f"{plantool} — OUTSIDE this repo, so the hooks run another checkout's "
                f"plan_tool and nothing compares the two; re-run `hooks git-install` to "
                f"prefer a copy in-repo")

    skill_root = Path(__file__).resolve().parent.parent
    if (skill_root / "SKILL.md").exists():
        drift = ([f"{f}:{v}" for f, v in doc_command_drift(skill_root)]
                 + [f"plan_tool.py header {d}: {v}" for d, v in header_command_drift()])
        add("enforcement", OK if not drift else GAP, "docs match the CLI",
            "the skill prose and this file's own header both match the parser" if not drift
            else "documented commands disagree with the parser: " + ", ".join(drift))

    vend = root / ".claude" / "skills" / "VENDORED.md"
    if vend.exists():
        add(*_vendored_freshness(root, read(vend)))
        m = re.search(r"\| version \| ([^|]+) \|", read(vend))
        ver = (m.group(1).strip() if m else "unknown")
        ok_d, dirty = git(root, "status", "--porcelain", "--", ".claude/skills")
        modified = [l for l in dirty.splitlines() if l.strip()] if ok_d else []
        add("adapter", WARN if modified else OK, "vendored skills",
            f"cozyplan {ver}, committed in-repo — a clone needs no install" if not modified
            else f"cozyplan {ver}, but {len(modified)} file(s) under .claude/skills/ are "
                 f"modified — re-vendor with `init --vendor` rather than hand-editing")

    wf = root / ".github" / "workflows"
    ci = [f.name for f in wf.glob("*.yml")] + [f.name for f in wf.glob("*.yaml")] if wf.is_dir() else []
    ci_text = "\n".join(read(wf / f) for f in ci) if ci else ""
    has_state_ci = ("state check" in ci_text or "state_check" in ci_text)
    # Labelled a record, like `hooks registered`. This greps a YAML file for a
    # string: a workflow that is syntactically broken, or has never once gone
    # green, passes it identically to one that guards every push. Whether it ran
    # is answerable only from the forge, which a clone cannot reach — so the row
    # says what it observed instead of implying more (ADR-0010, cozycode's report).
    add("enforcement", OK if has_state_ci else GAP, "ci workflow",
        f"a record only — {', '.join(ci)} names `state check`; whether it has ever "
        f"passed is not visible from a clone" if has_state_ci
        else "no workflow runs `state check` — no enforcing layer exists")

    # The selftest is the one check that proves the hook layer runs, and `init`
    # deliberately leaves an existing workflow alone — so a repo wired before the
    # selftest existed never gains the step and nothing ever says so. cozycode had
    # it in neither CI nor any hook: the best instrument in the toolkit, running
    # only when a human typed it.
    if ci:
        runs_selftest = "hooks selftest" in ci_text
        add("enforcement", OK if runs_selftest else WARN, "ci runs selftest",
            "a workflow runs `hooks selftest`" if runs_selftest
            else "no workflow runs `hooks selftest`, so nothing proves the hook layer "
                 "runs on a clean machine — add a step: "
                 "`python <plan_tool> hooks selftest --shipped`")

    add("enforcement", WARN, "required check",
        "not verifiable from a clone — confirm in GitHub Settings > Branches, or CI only reports")

    # ── tooling ──────────────────────────────────────────────────────────────
    if shutil.which("gh"):
        authed = gh_ready()
        add("tooling", OK if authed else WARN, "gh",
            "installed and authenticated" if authed else "installed but not authenticated (`gh auth login`)")
    else:
        add("tooling", WARN, "gh",
            "not installed — issue operations queue to .scratch/ instead (ADR-0001)")
    # "so this is fine" was true of plan_tool and false of the hooks, and the two
    # sat one line apart reading as a clean bill of health on a host where the
    # hook layer could not start. uv is now a fallback, not a requirement: the
    # hooks resolve python3/python/py first (see hooks/run-hook.sh), so what
    # matters is whether ANY interpreter resolves — which `hooks observed` above
    # answers by running them. This row is inventory, so it never reads as proof.
    _py = next((c for c in ("python3", "python", "py") if shutil.which(c)), None)
    add("tooling", OK if (shutil.which("uv") or _py) else GAP, "hook runtime",
        (f"{_py or 'uv'} resolves"
         + ("" if _py else " (uv only — no bare python on PATH)")
         + "; see `hooks observed` for whether the hooks actually ran")
        if (shutil.which("uv") or _py)
        else "no python3/python/py/uv on PATH — every hook exits without running")
    add("tooling", OK, "python", sys.version.split()[0])

    # ── state layer (ADR-0005) ───────────────────────────────────────────────
    state_md, log = root / "STATE.md", root / STATE_LOG_DEFAULT
    add("state", OK if state_md.exists() else GAP, "STATE.md",
        "present" if state_md.exists() else "missing — run the Init State workflow")
    n_ev = len([l for l in read(log).split("\n") if l.strip()]) if log.exists() else 0
    add("state", OK if log.exists() else WARN, "event log",
        f"{STATE_LOG_DEFAULT} ({n_ev} event(s))" if log.exists()
        else f"no {STATE_LOG_DEFAULT} — STATE.md is still hand-authored")
    ok_at, attr = git(root, "check-attr", "merge", "--", STATE_LOG_DEFAULT)
    union = ok_at and attr.strip().endswith(": union")
    add("state", OK if union else GAP, "union merge",
        "state log is union-merged" if union
        else f"`{STATE_LOG_DEFAULT} merge=union` missing from .gitattributes — concurrent appends will conflict")
    adr = root / "docs" / "adr"
    n_adr = len(list(adr.glob("*.md"))) if adr.is_dir() else 0
    add("state", OK if n_adr else WARN, "ADRs", f"{n_adr} recorded" if n_adr else "none recorded")

    # ── skill adapter ────────────────────────────────────────────────────────
    tracker = root / "docs" / "agents" / "issue-tracker.md"
    add("adapter", OK if tracker.exists() else GAP, "issue tracker",
        "docs/agents/issue-tracker.md" if tracker.exists()
        else "missing — to-spec/to-tickets/triage/wayfinder halt; run `plan_tool init` "
             "(or /setup-matt-pocock-skills for the wider skill set)")
    agent_doc = next((f for f in ("CLAUDE.md", "AGENTS.md") if (root / f).exists()), None)
    add("adapter", OK if agent_doc else GAP, "agent doc",
        f"{agent_doc} present" if agent_doc else "no CLAUDE.md or AGENTS.md — a clone has no entry point")

    # ── trailer coverage (what backward grounding depends on, ADR-0006) ──────
    ok_l, log_out = git(root, "log", f"-{commits}", "--format=%H%x1f%(trailers:key=Plan,valueonly)"
                        "%x1f%(trailers:key=ADR,valueonly)%x1e")
    if ok_l and log_out:
        recs = [r for r in log_out.split("\x1e") if r.strip()]
        with_tr = sum(1 for r in recs if any(p.strip() for p in r.split("\x1f")[1:]))
        pct = round(100 * with_tr / len(recs)) if recs else 0
        add("grounding", OK if pct >= 50 else WARN, "trailer coverage",
            f"{with_tr}/{len(recs)} of the last {len(recs)} commits carry Plan:/ADR: ({pct}%)"
            + ("" if pct >= 50 else " — backward grounding will return thin answers"))
    return out


def cmd_doctor(args) -> int:
    root = Path(args.root)
    rows = doctor_checks(root, args.commits)
    print(f"cozyplan doctor — {root.resolve()}\n")
    section = None
    for sec, status, name, detail in rows:
        if sec != section:
            print(f"{sec}")
            section = sec
        print(f"  [{_MARK[status]}] {name:<18} {detail}")
    gaps = [r for r in rows if r[1] == GAP]
    warns = [r for r in rows if r[1] == WARN]
    print(f"\n{len(rows) - len(gaps) - len(warns)} ok, {len(warns)} warn, {len(gaps)} gap")
    if gaps:
        print("gaps are wiring that is absent, not merely unconfigured:")
        for _, _, name, detail in gaps:
            print(f"  - {name}: {detail}")
    return 1 if (gaps and args.strict) else 0


# ── trailers + git hooks (ADR-0004: hooks advise by injecting, never rejecting) ─
# A commit-msg hook that REJECTS teaches people to type --no-verify, and then you
# have neither the trailer nor the habit. So this only ever adds what it can
# demonstrate: ADRs from the staged files, and a plan whose id matches the branch.
# Anything it cannot prove, it leaves alone.
#
# It fails open on the SUBJECT and loud on the APPARATUS (ADR-0010). Both hooks
# used to end in `|| true`, which collapsed the two: on a host whose recorded
# runner had left PATH, the hook wrote nothing, said nothing and exited 0 —
# byte-identical to a healthy run of a commit with no trailer to add. That is the
# third registration path, and it kept the defect the other two lost.
#
# Loud here means stderr, never a non-zero exit: a git hook that exits non-zero
# rejects the commit or the push, which ADR-0004 forbids for exactly the reason
# above. Git hook stderr reaches the terminal, which is why ADR-0010 rejected
# self-reporting for PostToolUse and it is right here — that stream is read.

GIT_HOOK_NAMES = ("commit-msg", "pre-push")

# Resolution happens at CALL time, the rule ADR-0010 already set for the two
# Claude Code registration paths. `git-install` records a runner, but a recorded
# runner is a fact about the machine on the day it was wired: uv gets uninstalled,
# interpreters move. So the record is preferred, verified, and re-resolved when it
# no longer answers — and the re-resolution is reported, because a stale record is
# a half-wired clone that still looks configured.
#
# Candidates are PROBED, not merely found on PATH: `command -v python3` succeeds
# against the Windows Store alias stub, which is not an interpreter.
#
# Every branch here exits 0. The hook is advisory (ADR-0004); what changes is that
# it no longer stays quiet about its own absence.
_GIT_HOOK_PREAMBLE = r"""
say() { echo "cozyplan $HOOK: $*" >&2; }

TOOL=$(git config cozyplan.plantool 2>/dev/null)
if [ -z "$TOOL" ] || [ ! -f "$TOOL" ]; then
    say "plan_tool not resolved (cozyplan.plantool=${TOOL:-unset}) — $WHAT did not run."
    say "This clone is half-wired. Fix with: plan_tool hooks git-install"
    exit 0
fi

RUN=$(git config cozyplan.runner 2>/dev/null)
ARG=$(git config cozyplan.runnerarg 2>/dev/null)
if [ -n "$RUN" ] && ! command -v "$RUN" >/dev/null 2>&1; then
    say "recorded runner '$RUN' is not on PATH — re-resolving. Re-record with: plan_tool hooks git-install"
    RUN=""
    ARG=""
fi
if [ -z "$RUN" ]; then
    for c in python3 python py; do
        command -v "$c" >/dev/null 2>&1 || continue
        if "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' \
            >/dev/null 2>&1; then
            RUN="$c"
            ARG=""
            break
        fi
    done
fi
if [ -z "$RUN" ] && command -v uv >/dev/null 2>&1; then
    RUN=uv
    ARG=run
fi
if [ -z "$RUN" ]; then
    say "no Python 3.9+ resolved (tried python3, python, py, uv) — $WHAT did not run."
    say "Fix by installing Python 3.9+ or uv, then: plan_tool hooks git-install"
    exit 0
fi
"""

# Quoted throughout: an interpreter path or a repo path may contain spaces.
# Unquoted, $RUN word-splits, the command is not found, and the trailer vanishes.
COMMIT_MSG_HOOK = (
    r"""#!/bin/sh
# cozyplan: add the trailers that can be demonstrated from this commit.
# Advisory by design — never blocks, never rejects (ADR-0004). Loud about its own
# absence, which is a different thing (ADR-0010).
HOOK=commit-msg
WHAT="trailer injection"
"""
    + _GIT_HOOK_PREAMBLE
    + r"""
if ! OUT=$("$RUN" ${ARG:+"$ARG"} "$TOOL" trailers --message-file "$1" 2>&1); then
    say "plan_tool trailers failed — this commit gets no trailer."
    printf '%s\n' "$OUT" >&2
fi
exit 0
"""
)

PRE_PUSH_HOOK = (
    r"""#!/bin/sh
# cozyplan: report snapshot drift before a push. Never blocks (ADR-0004). Loud
# about its own absence, which is a different thing (ADR-0010).
HOOK=pre-push
WHAT="the drift report"
"""
    + _GIT_HOOK_PREAMBLE
    + r"""
# `state check` exits non-zero on a real FAIL, which is a finding about the
# subject, not an apparatus failure — so the exit code alone cannot tell the two
# apart. A finding prints the lines grepped below; a crash prints neither, and
# that is the combination worth reporting.
OUT=$("$RUN" ${ARG:+"$ARG"} "$TOOL" state check 2>&1)
ST=$?
REPORT=$(printf '%s\n' "$OUT" | grep -E "behind HEAD|FAIL") || true
if [ -n "$REPORT" ]; then
    printf '%s\n' "$REPORT"
elif [ "$ST" -ne 0 ]; then
    say "state check exited $ST with no report — the drift check did not run."
    printf '%s\n' "$OUT" >&2
fi
exit 0
"""
)


def infer_trailers(root: Path) -> list[str]:
    """Trailers this commit can prove. Never a guess: an ADR is inferred only from
    a staged ADR file, and a plan only from a branch segment that names a real
    plan in specs/."""
    out: list[str] = []

    ok, staged = git(root, "diff", "--cached", "--name-only")
    if ok and staged:
        nums = []
        for path in staged.split("\n"):
            name = Path(path).name
            if "docs/adr/" in path.replace("\\", "/"):
                m = ADR_FILE_RE.match(name)
                if m and m.group("num") not in nums:
                    nums.append(m.group("num"))
        if nums:
            out.append("ADR: " + ",".join(sorted(nums)))

    ok_b, branch = git(root, "rev-parse", "--abbrev-ref", "HEAD")
    if ok_b and branch and branch != "HEAD":
        # feat/streaming-ingest, streaming-ingest, or bug/streaming-ingest-2 all
        # get a chance; only an id with a real plan file behind it is used.
        for seg in [branch] + branch.split("/"):
            if (root / "specs" / f"{seg}.html").exists():
                out.append(f"Plan: {seg}")
                break
    return out


def cmd_trailers(args) -> int:
    root = Path(args.root)
    trailers = infer_trailers(root)
    if args.print_only:
        for t in trailers:
            print(t)
        return 0
    if not args.message_file:
        return fail("--message-file or --print is required")
    msg = Path(args.message_file)
    if not msg.exists() or not trailers:
        return 0
    argv = ["interpret-trailers", "--in-place", "--if-exists", "doNothing"]
    for t in trailers:
        argv += ["--trailer", t]
    argv.append(str(msg))
    # git owns the trailer grammar (last paragraph, no blank lines inside the
    # block). Hand-rolling it is how the first pass at this silently dropped
    # every trailer behind a Co-Authored-By line.
    git(root, *argv)
    return 0


def cmd_hooks_git(args) -> int:
    root = Path(args.root)
    hooks_dir = root / args.dir
    if args.hooks_cmd == "git-remove":
        for name in GIT_HOOK_NAMES:
            (hooks_dir / name).unlink(missing_ok=True)
        git(root, "config", "--unset", "core.hooksPath")
        git(root, "config", "--unset", "cozyplan.plantool")
        git(root, "config", "--unset", "cozyplan.runner")
        git(root, "config", "--unset", "cozyplan.runnerarg")
        print(f"hooks: removed {args.dir}/ hooks and unset core.hooksPath")
        return 0

    hooks_dir.mkdir(parents=True, exist_ok=True)
    for name, body in (("commit-msg", COMMIT_MSG_HOOK), ("pre-push", PRE_PUSH_HOOK)):
        p = hooks_dir / name
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(body)
        p.chmod(0o755)
    # .git/hooks is not cloned, so the hooks live in a TRACKED directory and each
    # clone opts in with one command. doctor reports when that has not happened.
    git(root, "config", "core.hooksPath", args.dir)
    git(root, "config", "cozyplan.plantool", resolve_git_hook_tool(root))
    runner_exe, runner_arg = _hook_runner_parts()
    git(root, "config", "cozyplan.runner", runner_exe)
    if runner_arg:
        git(root, "config", "cozyplan.runnerarg", runner_arg)
    else:
        git(root, "config", "--unset", "cozyplan.runnerarg")
    print(f"hooks: wrote {args.dir}/commit-msg and {args.dir}/pre-push, "
          f"set core.hooksPath={args.dir}")
    print("       commit these — .git/hooks is not cloned, so each clone runs "
          "`plan_tool hooks git-install` once (doctor reports when it has not).")
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
    sp.add_argument("--force", action="store_true",
                    help="override a write-once field (id/created/schema), or set status=built "
                         "while status markers are still un-terminal")
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

    sp = sub.add_parser("hooks", parents=[parent],
                        help="register/unregister the coherence hooks in .claude/settings.json (for bare-skill installs)")
    sp.add_argument("hooks_cmd",
                    choices=["install", "remove", "git-install", "git-remove", "selftest"],
                    help="install/remove the Claude Code hooks, git-install/git-remove "
                         "the tracked .githooks (commit-msg trailer injection, pre-push "
                         "drift), or selftest to prove the registered hooks actually run")
    sp.add_argument("--shipped", action="store_true",
                    help="selftest: test the shipped hook scripts even when nothing is "
                         "registered (for CI and pre-install verification)")
    sp.add_argument("--dir", dest="dir", default=".githooks",
                    help="git-install: tracked hooks directory (default: .githooks)")
    sp.add_argument("--root", default=".", help="repo root (default: .)")
    sp.add_argument("--settings", default=None,
                    help="explicit settings.json path (default: ./.claude/settings.json)")
    sp.add_argument("--global", dest="global_", action="store_true",
                    help="target ~/.claude/settings.json instead of the project settings")
    sp.set_defaults(func=lambda a: cmd_hooks_git(a) if a.hooks_cmd.startswith("git-")
                    else cmd_hooks_selftest(a) if a.hooks_cmd == "selftest"
                    else cmd_hooks(a))

    sp = sub.add_parser("trailers", parents=[parent],
                        help="add the commit trailers this commit can demonstrate (advisory)")
    sp.add_argument("--message-file", default=None, help="commit message file to amend in place")
    sp.add_argument("--print", dest="print_only", action="store_true",
                    help="print the inferred trailers instead of writing them")
    sp.add_argument("--root", default=".", help="repo root (default: .)")
    sp.set_defaults(func=cmd_trailers)

    sp = sub.add_parser("doctor", parents=[parent],
                        help="report what is actually wired in this clone (ADR-0004)")
    sp.add_argument("--root", default=".", help="repo root (default: .)")
    sp.add_argument("--commits", type=int, default=20,
                    help="commits to sample for trailer coverage (default: 20)")
    sp.add_argument("--strict", action="store_true",
                    help="exit non-zero when any gap is found (for CI)")
    sp.set_defaults(func=cmd_doctor)

    sp = sub.add_parser("init", parents=[parent],
                        help="wire this repo for cozyplan: everything doctor checks that "
                             "a command can legitimately create (idempotent)")
    sp.add_argument("--root", default=".", help="repo root (default: .)")
    sp.add_argument("--specs", default="specs", help="specs directory (default: specs)")
    sp.add_argument("--hooks-dir", default=".githooks",
                    help="tracked git hooks directory (default: .githooks)")
    sp.add_argument("--git-init", action="store_true",
                    help="run `git init` when root is not a repository")
    sp.add_argument("--force-hooks", action="store_true",
                    help="take over core.hooksPath even when another hook manager owns it")
    sp.add_argument("--vendor", action="store_true",
                    help="copy the cozyplan and discuss skills into .claude/skills/ so a "
                         "clone of this repo needs no install")
    sp.add_argument("--repo", default=None, metavar="OWNER/NAME",
                    help="repo slug for the issue-tracker adapter when there is no origin")
    sp.add_argument("--no-claude-hooks", dest="claude_hooks", action="store_false",
                    help="skip registering the Claude Code hooks in .claude/settings.json")
    sp.set_defaults(func=cmd_init, claude_hooks=True)

    # One subparser per verb. A single shared flag list meant `state render --proof x`
    # parsed happily and did nothing, which is the kind of defect a 32-flag command hides.
    sp = sub.add_parser("issue", parents=[parent],
                        help="file a work item on the tracker, queueing it when gh is absent")
    sp.add_argument("issue_cmd", choices=["file", "replay"],
                    help="file one issue, or replay the queue built while gh was away")
    sp.add_argument("--root", default=".", help="repo root (default: .)")
    sp.add_argument("--title", default=None, help="file: issue title")
    sp.add_argument("--body", default=None, help="file: issue body")
    sp.add_argument("--label", default=None, help="file: comma-separated labels")
    sp.add_argument("--plan", default=None, help="file: plan id to reference in the body")
    sp.add_argument("--queue", action="store_true",
                    help="file: queue even when gh is available")
    sp.add_argument("--run", action="store_true",
                    help="replay: actually file the queued issues (default: list them)")
    sp.set_defaults(func=cmd_issue)

    sp = sub.add_parser("state", help="append to / render / inspect / check the state layer")
    state_common = argparse.ArgumentParser(add_help=False)
    state_common.add_argument("--root", default=".", help="repo root (default: .)")
    state_common.add_argument("--log", default=STATE_LOG_DEFAULT,
                              help=f"append-only event log (default: {STATE_LOG_DEFAULT})")
    ssub = sp.add_subparsers(dest="state_cmd", metavar="{add,render,show,check,migrate}")
    ssub.required = True

    q = ssub.add_parser("add", parents=[parent, state_common], help="append one event to the log")
    q.add_argument("--kind", choices=list(STATE_KINDS), default="claim", help="event kind (default: claim)")
    q.add_argument("--key", default=None,
                   help="stable identity for last-write-wins (default: derived from --what)")
    q.add_argument("--what", default=None, help="the capability, item, or gap")
    q.add_argument("--proof", default=None, help="the command that demonstrated a claim")
    q.add_argument("--sha", default=None, help="the commit the proof was true at")
    q.add_argument("--paths", default=None, help="comma-separated paths this entry depends on")
    q.add_argument("--status", default=None, help="status, for --kind indev")
    q.add_argument("--owner", default=None, help="owner, for --kind indev")
    q.add_argument("--plan", default=None, help="plan id ref")
    q.add_argument("--phase", default=None, help="phase/task id ref")
    q.add_argument("--adr", default=None, help="comma-separated ADR numbers")
    q.add_argument("--issue", default=None, help="comma-separated issue numbers")
    q.add_argument("--ts", default=None, help="explicit ISO timestamp (default: now)")
    q.add_argument("--clear", action="store_true",
                   help="retract this key from the projection (the log keeps the history)")
    q.set_defaults(func=cmd_state)

    q = ssub.add_parser("render", parents=[parent, state_common],
                        help="rebuild STATE.md from the log")
    q.add_argument("--file", default="STATE.md", help="rendered state file (default: STATE.md)")
    q.add_argument("--adr-dir", default="docs/adr", help="ADR directory (default: docs/adr)")
    q.add_argument("--journal", default="docs/journal.md", help="ledger (default: docs/journal.md)")
    q.add_argument("--specs", default="specs", help="specs directory (default: specs)")
    q.add_argument("--origin", default=None,
                   help="also report position vs this ref, e.g. origin/main")
    q.add_argument("--project", default=None,
                   help="project name for the heading (default: the repo directory)")
    q.add_argument("--force", action="store_true",
                   help="overwrite a STATE.md carrying no generated marker (discards it)")
    q.add_argument("--dry-run", action="store_true", help="print the result instead of writing it")
    q.set_defaults(func=cmd_state)

    q = ssub.add_parser("show", parents=[parent, state_common], help="print the projection")
    q.set_defaults(func=cmd_state)

    q = ssub.add_parser("check", parents=[parent, state_common],
                        help="verify STATE.md against git")
    q.add_argument("--file", default="STATE.md", help="rendered state file (default: STATE.md)")
    q.add_argument("--adr-dir", default="docs/adr", help="ADR directory (default: docs/adr)")
    q.add_argument("--journal", default="docs/journal.md", help="ledger (default: docs/journal.md)")
    q.add_argument("--max-drift", type=int, default=None,
                   help="fail when the snapshot is more than N commits behind HEAD")
    q.add_argument("--max-claim-age", type=int, default=None,
                   help="fail when a claim was last proved more than N commits ago")
    q.set_defaults(func=cmd_state)

    q = ssub.add_parser("migrate", parents=[parent, state_common],
                        help="carry a hand-authored STATE.md into the event log")
    q.add_argument("--file", default="STATE.md", help="the file to migrate (default: STATE.md)")
    q.add_argument("--dry-run", action="store_true",
                   help="print the events instead of appending them")
    q.set_defaults(func=cmd_state)

    sp = sub.add_parser("brief", parents=[parent],
                        help="compact plain-text extract of a plan (or --all for a one-liner index)")
    sp.add_argument("plan", nargs="?", help="plan path (omit with --all)")
    sp.add_argument("--all", action="store_true", help="one line per plan from _index.json")
    sp.add_argument("--specs", default="specs", help="specs directory (for --all; default: specs)")
    sp.set_defaults(func=cmd_brief)

    sp = sub.add_parser("phase", parents=[parent],
                        help="print one phase in full — tasks, actions, Testing Strategy")
    sp.add_argument("plan")
    sp.add_argument("--id", required=True, help="phase id, e.g. phase-3 (a bare 3 also works)")
    sp.set_defaults(func=cmd_phase)

    sp = sub.add_parser("next", parents=[parent],
                        help="print the first status id that is not [x]/[f] (or 'done')")
    sp.add_argument("plan")
    sp.set_defaults(func=cmd_next)

    sp = sub.add_parser("addphase", parents=[parent],
                        help="append a correctly-numbered phase block (structure, not content)")
    sp.add_argument("plan")
    sp.add_argument("--tasks", type=int, required=True,
                    help="number of work tasks; a Testing Strategy task is numbered after them")
    sp.add_argument("--title", help="phase name; left as a {{PHASE_NAME}} slot if omitted")
    sp.set_defaults(func=cmd_addphase)

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
    try:
        return args.func(args)
    except PlanLockBusy as e:
        return fail(str(e))  # fail closed: the plan was left exactly as it was


if __name__ == "__main__":
    raise SystemExit(main())
