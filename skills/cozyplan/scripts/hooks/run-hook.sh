#!/bin/sh
# cozyplan: resolve a Python, run a hook script — and say so loudly when it cannot.
#
# WHY THIS FILE EXISTS. hooks/hooks.json is a static manifest: it cannot ask the
# host what it has, so it hardcoded `uv run` and did not run on any host without
# uv. Resolution has to happen at call time, which means it has to happen here.
#
# ADR-0010: fail open on the subject, fail loud on the apparatus. Not finding a
# reason to object is a finding. Not being able to look is not — and the two must
# never leave the same exit code behind.
#
# Usage: run-hook.sh <hook-script.py> <dead-exit-code>
#
#   dead-exit-code is what to exit when NO interpreter resolves:
#     2  blocks, on the events that can block (PreToolUse). Use for the guard.
#     1  reports without blocking. Use everywhere else, and NEVER use 2 on
#        UserPromptSubmit — exit 2 there erases the user's prompt (see
#        HOOK_MATCHERS in plan_tool.py, which is the source of these codes).

set -u

SCRIPT="${1:-}"
DEAD="${2:-1}"

if [ -z "$SCRIPT" ]; then
    echo "cozyplan run-hook.sh: no hook script given" >&2
    exit "$DEAD"
fi

if [ ! -f "$SCRIPT" ]; then
    echo "cozyplan: hook script not found — $SCRIPT" >&2
    echo "The hook did NOT run, so this action was not checked. The plugin install" >&2
    echo "is incomplete or stale. Verify with: plan_tool hooks selftest" >&2
    exit "$DEAD"
fi

# Ordered by measured cost on a warm host: python3 24ms/call vs `uv run` 62ms.
# plan_tool and every hook declare `dependencies = []`, so uv buys nothing here
# but latency on a hook that fires on each tool call. It stays as the fallback
# that still produces a modern interpreter when the host's own python is absent
# or too old to run the tool.
#
# Each candidate is PROBED, not merely found on PATH. `command -v python3`
# succeeds against the Windows Store alias stub, which is not an interpreter and
# opens the Store instead of running anything; and against a python2 still named
# `python` on older Linux. Probing for the version the scripts declare
# (requires-python >=3.9) rejects both, and costs one short-lived process.
RUNNER=""
for candidate in python3 python py; do
    command -v "$candidate" >/dev/null 2>&1 || continue
    if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' \
        >/dev/null 2>&1; then
        RUNNER="$candidate"
        break
    fi
done

if [ -n "$RUNNER" ]; then
    exec "$RUNNER" "$SCRIPT"
fi

if command -v uv >/dev/null 2>&1; then
    exec uv run "$SCRIPT"
fi

# Nothing resolved. This is the branch the whole file exists for: before it, the
# manifest's `uv run` produced `sh: uv: command not found` and an exit code that
# reads as "the hook looked and found nothing wrong".
# Shell parameter expansion, not `basename`: this branch runs precisely when the
# host cannot resolve commands, and the first draft called basename here — which
# was itself not found, so the message naming the dead hook came out blank.
HOOK_NAME="${SCRIPT##*/}"
{
    echo "cozyplan: no usable Python found — tried python3, python, py, and uv."
    echo "$HOOK_NAME did NOT run. This action was NOT checked, and plans are unguarded."
    echo "Fix by installing Python 3.9+ or uv, then confirm with:"
    echo "  plan_tool hooks selftest"
} >&2
exit "$DEAD"
