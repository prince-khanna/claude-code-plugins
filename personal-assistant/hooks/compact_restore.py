#!/usr/bin/env python3
"""
SessionStart hook (matcher: compact) for Imli Personal Assistant v2.

Fires after context compaction. Re-injects imli-core.md and session.md
as additionalContext to restore post-compaction context.
"""
import json
import sys
from pathlib import Path

CONTEXT_DIR = Path.home() / ".claude" / ".context"
imli_CORE_PATH = Path.home() / ".claude" / "rules" / "imli-core.md"


def run_hook() -> None:
    """Read imli-core.md and session.md, output as additionalContext."""
    parts = []

    if imli_CORE_PATH.exists():
        parts.append(imli_CORE_PATH.read_text(encoding="utf-8", errors="replace"))
    else:
        parts.append(
            "# Imli -- Personal Assistant Context\n\n"
            "imli-core.md not found. Run /sync-context to regenerate."
        )

    session_path = CONTEXT_DIR / "core" / "session.md"
    if session_path.exists():
        session_content = session_path.read_text(encoding="utf-8", errors="replace")
        if session_content.strip():
            parts.append("## Session Context (restored after compaction)\n" + session_content)

    additional_context = "\n\n".join(parts)

    output = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": additional_context,
        }
    }
    print(json.dumps(output))


def main() -> None:
    """Entry point -- consume stdin then run hook logic."""
    try:
        json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        pass

    run_hook()
    sys.exit(0)


if __name__ == "__main__":
    main()
