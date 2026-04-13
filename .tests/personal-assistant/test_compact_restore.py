"""Tests for compact_restore.py -- SessionStart (compact) hook."""
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

HOOKS_DIR = Path(__file__).resolve().parents[2] / "personal-assistant" / "hooks"
sys.path.insert(0, str(HOOKS_DIR))


class TestCompactRestore:
    def test_outputs_imli_core_content(self, tmp_context, tmp_rules_dir, capsys):
        from compact_restore import run_hook
        imli_core = tmp_rules_dir / "imli-core.md"
        imli_core.write_text("# Imli Core\nIdentity and rules here.")
        with patch("compact_restore.imli_CORE_PATH", imli_core), \
             patch("compact_restore.CONTEXT_DIR", tmp_context):
            run_hook()
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        ctx = output["hookSpecificOutput"]["additionalContext"]
        assert "Imli Core" in ctx

    def test_includes_session_context(self, tmp_context, tmp_rules_dir, capsys):
        from compact_restore import run_hook
        imli_core = tmp_rules_dir / "imli-core.md"
        imli_core.write_text("# Imli Core")
        session = tmp_context / "core" / "session.md"
        session.write_text("## Current Focus\nWorking on v2 migration")
        with patch("compact_restore.imli_CORE_PATH", imli_core), \
             patch("compact_restore.CONTEXT_DIR", tmp_context):
            run_hook()
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        ctx = output["hookSpecificOutput"]["additionalContext"]
        assert "v2 migration" in ctx

    def test_handles_missing_imli_core(self, tmp_context, tmp_path, capsys):
        from compact_restore import run_hook
        missing = tmp_path / "rules" / "imli-core.md"
        with patch("compact_restore.imli_CORE_PATH", missing), \
             patch("compact_restore.CONTEXT_DIR", tmp_context):
            run_hook()
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        ctx = output["hookSpecificOutput"]["additionalContext"]
        assert "sync-context" in ctx.lower() or "imli" in ctx.lower()

    def test_handles_missing_session(self, tmp_context, tmp_rules_dir, capsys):
        from compact_restore import run_hook
        imli_core = tmp_rules_dir / "imli-core.md"
        imli_core.write_text("# Imli Core")
        session = tmp_context / "core" / "session.md"
        if session.exists():
            session.unlink()
        with patch("compact_restore.imli_CORE_PATH", imli_core), \
             patch("compact_restore.CONTEXT_DIR", tmp_context):
            run_hook()
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert "hookSpecificOutput" in output
