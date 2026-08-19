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
  phase      print one phase in full — its tasks, actions, and Testing Strategy
  next       print the first status id that is not [x]/[f] (or 'done')
  addphase   append a correctly-numbered phase block (structure, not content)

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
import shutil
import subprocess
import sys
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
def template_candidates(name: str = "plan.html") -> list[Path]:
    """Ordered locations to look for a named template.

    Mirrors how the hooks resolve plan_tool.py: prefer CLAUDE_PLUGIN_ROOT (the
    bundled plugin), then the project cwd, then this script's own location — each
    with the in-project `.claude/skills/...` layout and the moved-as-a-unit layout.
    """
    rels = [
        Path(".claude") / "skills" / "cozyplan" / "templates" / name,
        Path("skills") / "cozyplan" / "templates" / name,
        Path("templates") / name,
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


def resolve_template(name: str = "plan.html") -> Path | None:
    for c in template_candidates(name):
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


def git(root: Path, *argv: str) -> tuple[bool, str]:
    """Run a git command, returning (ok, stripped stdout). Never raises: a missing
    git binary or a non-repo is a condition the caller reports, not a crash."""
    try:
        r = subprocess.run(["git", *argv], cwd=str(root), capture_output=True,
                           text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False, ""
    return r.returncode == 0, r.stdout.strip()


def section_body(text: str, heading: str) -> str:
    """The lines under a `## heading`, up to the next heading of the same level."""
    m = re.search(rf"^##\s+{re.escape(heading)}\s*$(?P<body>.*?)(?=^##\s|\Z)",
                  text, re.M | re.S)
    return m.group("body") if m else ""


def check_state(state_path: Path, root: Path, adr_dir: Path, journal: Path,
                max_drift: int | None) -> tuple[list[str], list[str], list[str]]:
    """Return (problems, warns, notes). Problems fail the run; warns and notes do not."""
    problems: list[str] = []
    warns: list[str] = []
    notes: list[str] = []

    text = read(state_path)

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
                ok_cnt, out = git(root, "rev-list", "--count", f"{sha}..HEAD")
                behind = int(out or 0) if ok_cnt else 0
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
    claims = [ln for ln in body.splitlines()
              if ln.strip().startswith("- ") and "<!--" not in ln]
    if not claims:
        notes.append("Current Working State is empty")
    for ln in claims:
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
            ok_obj, _ = git(root, "cat-file", "-e", f"{sha}^{{commit}}")
            if not ok_obj:
                problems.append(f"claim cites {sha}, which is not a commit in this repo: "
                                f"{m.group('what')[:60]}")
                continue
            ok_cnt, out = git(root, "rev-list", "--count", f"{sha}..HEAD")
            if ok_cnt and int(out or 0):
                notes.append(f"claim proved {out} commit(s) ago: {m.group('what')[:60]}")

    # 5. The ADR register is a hand-maintained copy of a directory listing, so it
    #    drifts. Comparing the two is cheap and catches it immediately.
    if adr_dir.is_dir():
        on_disk = {m.group("num") for f in adr_dir.glob("*.md")
                   if (m := ADR_FILE_RE.match(f.name))}
        registers = section_body(text, "Registers")
        listed = set(re.findall(r"ADR-(\d{4})", registers))
        for num in sorted(on_disk - listed):
            problems.append(f"ADR-{num} exists in {adr_dir}/ but is missing from the Registers index")
        for num in sorted(listed - on_disk):
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
    event marked cleared removes the key. Ranked by weight first so a capped view
    keeps the most significant state, not merely the most recent."""
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
        out[kind].sort(key=lambda e: (-int(e.get("weight", 3) or 3), e["_ord"]))
    return out


def refs_line(ev: dict) -> str:
    """The pointer trail. An entry carries the ids needed to decide whether to
    follow it, never the detail itself — so capping costs immediacy, never
    reachability (ADR-0005)."""
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


def render_state(root: Path, projected: dict, cap: int, adr_dir: Path,
                 specs: str, journal: Path, origin, project: str | None = None) -> str:
    ok_b, branch = git(root, "rev-parse", "--abbrev-ref", "HEAD")
    ok_s, sha = git(root, "rev-parse", "--short", "HEAD")
    # Deterministic: stamp the newest EVENT, never the run time, so re-rendering
    # unchanged inputs is byte-identical (the same rule `index` follows).
    newest = max((e.get("ts", "") for lst in projected.values() for e in lst), default="")
    lines = [f"# {project or root.resolve().name} — State", "",
             f"<!-- {STATE_GENERATED_MARKER} from docs/state.ndjson.",
             "     Do not hand-edit: append with `plan_tool state add`, then re-render.",
             "     History lives in the log; this file is the capped current view. -->", "",
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
        for ev in items[:cap]:
            lines.append(fmt(ev))
            rl = refs_line(ev)
            if rl:
                lines.append(rl)
        if len(items) > cap:
            lines.extend(["", f"_{len(items) - cap} more — `plan_tool state show --all`_"])
        lines.append("")

    section("Current Working State", "claim", lambda e: (
        f"- {e.get('what', '')} — verified by `{e.get('proof', '')}` "
        f"({e.get('date', '')}{', ' + e['sha'] if e.get('sha') else ''})"))
    section("In Development", "indev", lambda e: (
        f"- {e.get('what', '')} — {e.get('status', 'in-development')}"
        + (f" · {e['owner']}" if e.get("owner") else "")))
    section("Known Gaps / Risks", "gap", lambda e: f"- {e.get('what', '')}")

    lines.extend(["## Registers", "",
                  f"- **Plans** — [{specs}/_index.html]({specs}/_index.html)",
                  f"- **Decisions (ADRs)** — [{adr_dir}/]({adr_dir}/)"])
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
    lines.extend(["- **Components** — [SYSTEM.md](SYSTEM.md)",
                  f"- **Ledger** — [{journal}]({journal})", ""])
    return "\n".join(lines).rstrip() + "\n"



def migrate_state(text: str, who: str) -> tuple[list[dict], list[str]]:
    """Parse a hand-authored STATE.md into events, plus a list of what could not be
    carried. Honest by construction: it never invents a field the old format has no
    source for. weight defaults to 3 for everything, so ranking is a human's job
    afterwards — a migrated cap that dropped entries by guessed importance would be
    worse than one that says it guessed nothing (ADR-0005)."""
    events: list[dict] = []
    lost: list[str] = []

    def ev(kind: str, what: str, **extra) -> None:
        e = {"kind": kind, "key": what[:60], "what": what, "weight": 3, "by": who,
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
        lost.append(f"weight on all {len(events)} event(s) — the old format has no "
                    f"importance signal, so every one defaults to 3; re-weight what "
                    f"matters or the cap will drop entries arbitrarily")
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

Run `plan_tool doctor` to see what is actually wired in this clone.

## Agent skills

### Issue tracker

See `docs/agents/issue-tracker.md`.
"""

GITATTRIBUTES_STANZA = """
# Append-only state event log (ADR-0005): union-merge so concurrent appends
# from different sessions and agents combine instead of conflicting.
docs/state.ndjson merge=union
"""


def cmd_init(args) -> int:
    """Wire a repo for cozyplan: everything `doctor` checks that a command can
    legitimately create. Idempotent and additive — every write is create-if-absent
    or append-if-missing, never a truncation, so brownfield is the normal case
    rather than a special one."""
    root = Path(args.root)
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

    # ── records and the event log ────────────────────────────────────────────
    ensure_dir("docs/adr")
    ensure_file(STATE_LOG_DEFAULT, "")
    ensure_from_template("docs/journal.md", "journal.md")

    ok_rem, remote = git(root, "remote", "get-url", "origin")
    slug = ""
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
                      "cannot be filled in. Add a remote and re-run, or write it by hand")

    # ── union merge: ask git, not the file. The attribute can come from
    #    .git/info/attributes or a parent dir, and appending blindly duplicates it.
    ok_attr, attr = git(root, "check-attr", "merge", "--", STATE_LOG_DEFAULT)
    if ok_attr and attr.strip().endswith(": union"):
        kept.append(".gitattributes (merge=union)")
    else:
        ga = root / ".gitattributes"
        existing = read(ga) if ga.exists() else ""
        write(ga, (existing.rstrip("\n") + "\n\n" if existing.strip() else "") + GITATTRIBUTES_STANZA.lstrip("\n"))
        made.append(".gitattributes (merge=union)")

    # ── CI ───────────────────────────────────────────────────────────────────
    wf = root / ".github" / "workflows"
    runs_check = any("state check" in read(f) or "state_check" in read(f)
                     for f in sorted(list(wf.glob("*.yml")) + list(wf.glob("*.yaml")))) if wf.is_dir() else False
    if runs_check:
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
        ns = argparse.Namespace(hooks_cmd="install", settings=str(root / ".claude" / "settings.json"),
                                global_=False)
        if cmd_hooks(ns) == 0:
            refreshed.append(".claude/settings.json (guard + lint hooks)")
        else:
            manual.append(".claude/settings.json — hook registration failed; run "
                          "`plan_tool hooks install` and read the error")

    # ── entry point ──────────────────────────────────────────────────────────
    if (root / "CLAUDE.md").exists() or (root / "AGENTS.md").exists():
        kept.append("CLAUDE.md / AGENTS.md")
    else:
        ensure_file("CLAUDE.md", CLAUDE_MD_STUB.format(name=root.resolve().name))

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
                                file=str(state_file), cap=20, adr_dir=str(root / "docs" / "adr"),
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
    checks = {name: (status, detail) for _, status, name, detail in doctor_checks(root, 20)}
    for name in ("identity", "remote", "gh", "required check"):
        if name in checks and checks[name][0] != OK:
            manual.append(f"{name} — {checks[name][1]}")
    if manual:
        print("\n  needs a human:")
        for i in manual:
            print(f"    - {i}")
    gaps = [(n, d) for _, st, n, d in doctor_checks(root, 20) if st == GAP]
    print(f"\n  {len(gaps)} gap(s) remain — run `plan_tool doctor` for the full picture.")
    return 0

def cmd_state(args) -> int:
    root = Path(args.root)
    log_path = Path(args.log)

    if args.state_cmd == "add":
        if not args.what:
            return fail("--what is required")
        _, who = git(root, "config", "user.name")
        ev = {"kind": args.kind, "key": args.key or args.what[:60], "what": args.what,
              "weight": args.weight, "by": who or "",
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
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(ev, ensure_ascii=False, sort_keys=True) + "\n")
        print(f"state: appended {args.kind} '{ev['key']}'"
              + (" (cleared)" if args.clear else "") + f" -> {log_path}")
        return 0

    if args.state_cmd == "migrate":
        src = Path(args.file)
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
                shown = items if args.all else items[:args.cap]
                print(f"{kind} ({len(items)}):")
                for ev in shown:
                    print(f"  [w{ev.get('weight', 3)}] {ev.get('what', '')}")
                if len(items) > len(shown):
                    print(f"  ... {len(items) - len(shown)} more (--all)")
            return 0
        out = Path(args.file)
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
        rendered = render_state(root, projected, args.cap, Path(args.adr_dir),
                                args.specs, Path(args.journal), args.origin, args.project)
        if args.dry_run:
            print(rendered, end="")
            return 0
        write(out, rendered)
        n = sum(len(v) for v in projected.values())
        print(f"state: rendered {out} from {n} projected entr(ies)")
        return 0

    state_path = Path(args.file)
    if not state_path.exists():
        return fail(f"state file not found: {state_path} - run the Init State workflow first")
    problems, warns, notes = check_state(
        state_path, root, Path(args.adr_dir), Path(args.journal), args.max_drift)
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
    settings = root / ".claude" / "settings.json"
    registered = False
    if settings.exists():
        try:
            blob = json.dumps(json.loads(read(settings)))
            registered = "guard_plan_edit" in blob and "lint_plan" in blob
        except (json.JSONDecodeError, ValueError):
            registered = False
    add("enforcement", OK if registered else WARN, "claude hooks",
        "guard + lint registered in .claude/settings.json" if registered
        else "not registered — run `plan_tool hooks install` (advisory layer only)")

    # The check that matters: does the interpreter those hooks name actually run?
    tool = Path(__file__).resolve()
    stored = _stored_hook_runner(root)
    runner = stored or _hook_runner()
    try:
        r = subprocess.run(runner + [str(tool), "--help"],
                           capture_output=True, text=True, timeout=30, cwd=str(root))
        runs = r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        runs = False
    src = " (recorded by git-install)" if stored else " (not wired here; this is what it would use)"
    add("enforcement", OK if runs else GAP, "hook interpreter",
        f"`{' '.join(runner)}` runs plan_tool{src}" if runs
        else f"`{' '.join(runner)}` cannot run plan_tool{src} — hooks fail open, silently")

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

    wf = root / ".github" / "workflows"
    ci = [f.name for f in wf.glob("*.yml")] + [f.name for f in wf.glob("*.yaml")] if wf.is_dir() else []
    has_state_ci = any("state check" in read(wf / f) or "state_check" in read(wf / f) for f in ci) if ci else False
    add("enforcement", OK if has_state_ci else GAP, "ci workflow",
        f"{', '.join(ci)}" if has_state_ci else "no workflow runs `state check` — no enforcing layer exists")
    add("enforcement", WARN, "required check",
        "not verifiable from a clone — confirm in GitHub Settings > Branches, or CI only reports")

    # ── tooling ──────────────────────────────────────────────────────────────
    if shutil.which("gh"):
        authed = subprocess.run(["gh", "auth", "status"], capture_output=True,
                                text=True).returncode == 0
        add("tooling", OK if authed else WARN, "gh",
            "installed and authenticated" if authed else "installed but not authenticated (`gh auth login`)")
    else:
        add("tooling", WARN, "gh",
            "not installed — issue operations queue to .scratch/ instead (ADR-0001)")
    add("tooling", OK if shutil.which("uv") else WARN, "uv",
        "present" if shutil.which("uv") else "absent — plan_tool runs on plain python3, so this is fine")
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
        else "missing — to-spec/to-tickets/triage/wayfinder halt; run /setup-matt-pocock-skills")
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
# Anything it cannot prove, it leaves alone. It fails open on every error — a
# hook that blocks a commit because it could not read a file is worse than a
# missing trailer.

GIT_HOOK_NAMES = ("commit-msg", "pre-push")

COMMIT_MSG_HOOK = """#!/bin/sh
# cozyplan: add the trailers that can be demonstrated from this commit.
# Advisory by design — never blocks, never rejects (ADR-0004).
TOOL=$(git config cozyplan.plantool 2>/dev/null) || exit 0
[ -n "$TOOL" ] || exit 0
RUN=$(git config cozyplan.runner 2>/dev/null)
[ -n "$RUN" ] || RUN=python3
ARG=$(git config cozyplan.runnerarg 2>/dev/null)
# Quoted: an interpreter path or a repo path may contain spaces. Unquoted, $RUN
# word-splits, the command is not found, and the trailer vanishes with no error.
"$RUN" ${ARG:+"$ARG"} "$TOOL" trailers --message-file "$1" >/dev/null 2>&1 || true
exit 0
"""

PRE_PUSH_HOOK = """#!/bin/sh
# cozyplan: report snapshot drift before a push. Never blocks (ADR-0004).
TOOL=$(git config cozyplan.plantool 2>/dev/null) || exit 0
[ -n "$TOOL" ] || exit 0
RUN=$(git config cozyplan.runner 2>/dev/null)
[ -n "$RUN" ] || RUN=python3
ARG=$(git config cozyplan.runnerarg 2>/dev/null)
# Quoted: an interpreter path or a repo path may contain spaces. Unquoted, $RUN
# word-splits, the command is not found, and the trailer vanishes with no error.
"$RUN" ${ARG:+"$ARG"} "$TOOL" state check 2>/dev/null | grep -E "behind HEAD|FAIL" || true
exit 0
"""


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
    git(root, "config", "cozyplan.plantool", str(Path(__file__).resolve()))
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

    sp = sub.add_parser("roles", parents=[parent], help="build role manifest + CODEOWNERS")
    sp.add_argument("roles_cmd", choices=["build"], help="subcommand (only 'build')")
    sp.add_argument("--dir", default="roles", help="roles directory (default: roles)")
    sp.add_argument("--codeowners", default=None, help="CODEOWNERS output path (default: .github/CODEOWNERS)")
    sp.set_defaults(func=cmd_roles)

    sp = sub.add_parser("hooks", parents=[parent],
                        help="register/unregister the coherence hooks in .claude/settings.json (for bare-skill installs)")
    sp.add_argument("hooks_cmd", choices=["install", "remove", "git-install", "git-remove"],
                    help="install/remove the Claude Code hooks, or git-install/git-remove "
                         "the tracked .githooks (commit-msg trailer injection, pre-push drift)")
    sp.add_argument("--dir", dest="dir", default=".githooks",
                    help="git-install: tracked hooks directory (default: .githooks)")
    sp.add_argument("--root", default=".", help="repo root (default: .)")
    sp.add_argument("--settings", default=None,
                    help="explicit settings.json path (default: ./.claude/settings.json)")
    sp.add_argument("--global", dest="global_", action="store_true",
                    help="target ~/.claude/settings.json instead of the project settings")
    sp.set_defaults(func=lambda a: cmd_hooks_git(a) if a.hooks_cmd.startswith("git-") else cmd_hooks(a))

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
    sp.add_argument("--no-claude-hooks", dest="claude_hooks", action="store_false",
                    help="skip registering the Claude Code hooks in .claude/settings.json")
    sp.set_defaults(func=cmd_init, claude_hooks=True)

    sp = sub.add_parser("state", parents=[parent],
                        help="append to / render / inspect / check the state layer")
    sp.add_argument("state_cmd", choices=["add", "render", "show", "check", "migrate"],
                    help="add an event, render STATE.md, show the projection, check it, "
                         "or migrate a hand-authored STATE.md into the event log")
    sp.add_argument("--force", action="store_true",
                    help="render: overwrite a STATE.md that carries no generated marker "
                         "(discards hand-authored content)")
    sp.add_argument("--dry-run", action="store_true",
                    help="render: print the result instead of writing it. "
                         "migrate: print the events instead of appending them")
    sp.add_argument("--file", default="STATE.md", help="rendered state file (default: STATE.md)")
    sp.add_argument("--log", default=STATE_LOG_DEFAULT,
                    help=f"append-only event log (default: {STATE_LOG_DEFAULT})")
    sp.add_argument("--root", default=".", help="repo root (default: .)")
    sp.add_argument("--adr-dir", default="docs/adr", help="ADR directory (default: docs/adr)")
    sp.add_argument("--journal", default="docs/journal.md", help="ledger (default: docs/journal.md)")
    sp.add_argument("--specs", default="specs", help="specs directory (default: specs)")
    sp.add_argument("--max-drift", type=int, default=None,
                    help="check: fail when the snapshot is more than N commits behind HEAD")
    sp.add_argument("--cap", type=int, default=20,
                    help="render/show: max entries per section (default: 20)")
    sp.add_argument("--all", action="store_true", help="show: every entry, ignoring --cap")
    sp.add_argument("--origin", default=None,
                    help="render: also report position vs this ref, e.g. origin/main")
    sp.add_argument("--project", default=None,
                    help="render: project name for the heading (default: the repo directory)")
    # add
    sp.add_argument("--kind", choices=list(STATE_KINDS), default="claim",
                    help="add: event kind (default: claim)")
    sp.add_argument("--key", default=None,
                    help="add: stable identity for last-write-wins (default: derived from --what)")
    sp.add_argument("--what", default=None, help="add: the capability, item, or gap")
    sp.add_argument("--proof", default=None, help="add: the command that demonstrated a claim")
    sp.add_argument("--sha", default=None, help="add: the commit the proof was true at")
    sp.add_argument("--paths", default=None,
                    help="add: comma-separated paths this entry depends on")
    sp.add_argument("--weight", type=int, default=3,
                    help="add: importance 1-5; a capped view keeps the heaviest (default: 3)")
    sp.add_argument("--status", default=None, help="add: status, for --kind indev")
    sp.add_argument("--owner", default=None, help="add: owner, for --kind indev")
    sp.add_argument("--plan", default=None, help="add: plan id ref")
    sp.add_argument("--phase", default=None, help="add: phase/task id ref")
    sp.add_argument("--adr", default=None, help="add: comma-separated ADR numbers")
    sp.add_argument("--issue", default=None, help="add: comma-separated issue numbers")
    sp.add_argument("--ts", default=None, help="add: explicit ISO timestamp (default: now)")
    sp.add_argument("--clear", action="store_true",
                    help="add: retract this key from the projection (the log keeps the history)")
    sp.set_defaults(func=cmd_state)

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
