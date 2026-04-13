"""Tests for session_start.py -- SessionStart (startup) hook."""
import json
import sys
import textwrap
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

HOOKS_DIR = Path(__file__).resolve().parents[2] / "personal-assistant" / "hooks"
sys.path.insert(0, str(HOOKS_DIR))


class TestParseTriggers:
    def test_finds_upcoming_events(self, tmp_context):
        from session_start import parse_upcoming_triggers
        future_date = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")
        triggers_content = textwrap.dedent(f"""\
            ---
            name: Triggers
            ---
            ## Upcoming

            | Date | Event | Action |
            |------|-------|--------|
            | {future_date} | Client demo | Prepare slides |
        """)
        triggers_path = tmp_context / "core" / "triggers.md"
        triggers_path.write_text(triggers_content)
        result = parse_upcoming_triggers(triggers_path, lookahead_days=7)
        assert len(result) == 1
        assert "Client demo" in result[0]

    def test_ignores_past_events(self, tmp_context):
        from session_start import parse_upcoming_triggers
        past_date = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
        triggers_content = textwrap.dedent(f"""\
            ---
            name: Triggers
            ---
            ## Upcoming

            | Date | Event | Action |
            |------|-------|--------|
            | {past_date} | Old event | Was done |
        """)
        triggers_path = tmp_context / "core" / "triggers.md"
        triggers_path.write_text(triggers_content)
        result = parse_upcoming_triggers(triggers_path, lookahead_days=7)
        assert len(result) == 0

    def test_ignores_far_future_events(self, tmp_context):
        from session_start import parse_upcoming_triggers
        far_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
        triggers_content = textwrap.dedent(f"""\
            ---
            name: Triggers
            ---
            ## Upcoming

            | Date | Event | Action |
            |------|-------|--------|
            | {far_date} | Far event | Not yet |
        """)
        triggers_path = tmp_context / "core" / "triggers.md"
        triggers_path.write_text(triggers_content)
        result = parse_upcoming_triggers(triggers_path, lookahead_days=7)
        assert len(result) == 0

    def test_handles_missing_triggers_file(self, tmp_path):
        from session_start import parse_upcoming_triggers
        result = parse_upcoming_triggers(tmp_path / "nonexistent.md")
        assert result == []

    def test_handles_malformed_dates(self, tmp_context):
        from session_start import parse_upcoming_triggers
        triggers_content = textwrap.dedent("""\
            ---
            name: Triggers
            ---
            ## Upcoming

            | Date | Event | Action |
            |------|-------|--------|
            | not-a-date | Bad event | Nothing |
        """)
        triggers_path = tmp_context / "core" / "triggers.md"
        triggers_path.write_text(triggers_content)
        result = parse_upcoming_triggers(triggers_path, lookahead_days=7)
        assert len(result) == 0

    def test_parses_month_day_year_format(self, tmp_context):
        from session_start import parse_upcoming_triggers
        future = datetime.now() + timedelta(days=3)
        date_str = future.strftime("%b %d, %Y")  # e.g. "Mar 09, 2026"
        triggers_content = textwrap.dedent(f"""\
            ---
            name: Triggers
            ---
            ## Upcoming

            | Date | Event | Action |
            |------|-------|--------|
            | {date_str} | Birthday party | Buy gift |
        """)
        triggers_path = tmp_context / "core" / "triggers.md"
        triggers_path.write_text(triggers_content)
        result = parse_upcoming_triggers(triggers_path, lookahead_days=7)
        assert len(result) == 1
        assert "Birthday party" in result[0]

    def test_parses_bold_date_format(self, tmp_context):
        from session_start import parse_upcoming_triggers
        future = datetime.now() + timedelta(days=2)
        date_str = future.strftime("%b %d, %Y")
        triggers_content = textwrap.dedent(f"""\
            ---
            name: Triggers
            ---
            ## Upcoming

            | Date | Event | Action |
            |------|-------|--------|
            | **{date_str}** | Deadline | Submit |
        """)
        triggers_path = tmp_context / "core" / "triggers.md"
        triggers_path.write_text(triggers_content)
        result = parse_upcoming_triggers(triggers_path, lookahead_days=7)
        assert len(result) == 1
        assert "Deadline" in result[0]

    def test_parses_month_day_no_year_format(self, tmp_context):
        from session_start import parse_upcoming_triggers
        future = datetime.now() + timedelta(days=5)
        date_str = future.strftime("%b %d")  # e.g. "Mar 11"
        triggers_content = textwrap.dedent(f"""\
            ---
            name: Triggers
            ---
            ## Upcoming

            | Date | Event | Person |
            |------|-------|--------|
            | {date_str} | Birthday | Jane |
        """)
        triggers_path = tmp_context / "core" / "triggers.md"
        triggers_path.write_text(triggers_content)
        result = parse_upcoming_triggers(triggers_path, lookahead_days=7)
        assert len(result) == 1
        assert "Birthday" in result[0]

    def test_skips_completed_rows(self, tmp_context):
        from session_start import parse_upcoming_triggers
        future = datetime.now() + timedelta(days=3)
        date_str = future.strftime("%Y-%m-%d")
        triggers_content = textwrap.dedent(f"""\
            ---
            name: Triggers
            ---
            ## Upcoming

            | Date | Event | Status |
            |------|-------|--------|
            | {date_str} | Done thing | ✅ Complete |
            | {date_str} | Failed thing | ❌ Unsuccessful |
            | {date_str} | Active thing | ⏰ Upcoming |
        """)
        triggers_path = tmp_context / "core" / "triggers.md"
        triggers_path.write_text(triggers_content)
        result = parse_upcoming_triggers(triggers_path, lookahead_days=7)
        assert len(result) == 1
        assert "Active thing" in result[0]


class TestParseDateFlexible:
    """Tests for the multi-format date parser."""

    def test_parses_iso_date(self):
        from session_start import parse_date_flexible
        result = parse_date_flexible("2026-03-29")
        assert result is not None
        assert result.year == 2026
        assert result.month == 3
        assert result.day == 29

    def test_parses_month_day_year(self):
        from session_start import parse_date_flexible
        result = parse_date_flexible("Dec 19, 2025")
        assert result is not None
        assert result.year == 2025
        assert result.month == 12
        assert result.day == 19

    def test_parses_month_day_year_long(self):
        from session_start import parse_date_flexible
        result = parse_date_flexible("Mar 29, 2026")
        assert result is not None
        assert result.month == 3
        assert result.day == 29

    def test_parses_month_day_no_year(self):
        from session_start import parse_date_flexible
        result = parse_date_flexible("Mar 29")
        assert result is not None
        assert result.month == 3
        assert result.day == 29

    def test_parses_bold_markdown(self):
        from session_start import parse_date_flexible
        result = parse_date_flexible("**Jan 31, 2026**")
        assert result is not None
        assert result.month == 1
        assert result.day == 31

    def test_parses_day_of_week_prefix(self):
        from session_start import parse_date_flexible
        result = parse_date_flexible("Sat Feb 28, 2026")
        assert result is not None
        assert result.month == 2
        assert result.day == 28

    def test_parses_approximate_date(self):
        from session_start import parse_date_flexible
        result = parse_date_flexible("~Feb-Mar 2026")
        assert result is not None
        assert result.month == 2
        assert result.day == 1

    def test_returns_none_for_garbage(self):
        from session_start import parse_date_flexible
        assert parse_date_flexible("not-a-date") is None
        assert parse_date_flexible("TBD") is None
        assert parse_date_flexible("") is None

    def test_returns_none_for_tbd(self):
        from session_start import parse_date_flexible
        assert parse_date_flexible("TBD") is None
        assert parse_date_flexible("*TBD*") is None


class TestSessionCarryover:
    """Tests for extracting 'Notes for Next Session' from session.md."""

    def test_extracts_notes_for_next_session(self, tmp_context):
        from session_start import extract_session_carryover
        session_path = tmp_context / "core" / "session.md"
        session_path.write_text(textwrap.dedent("""\
            ---
            name: Session
            ---
            ## Current Focus
            Working on feature X

            ## Notes for Next Session

            <guide>Context to carry forward</guide>

            - Remember to check the deploy logs
            - Ask about the API key rotation
        """))
        result = extract_session_carryover(session_path)
        assert "deploy logs" in result
        assert "API key rotation" in result

    def test_ignores_empty_notes_section(self, tmp_context):
        from session_start import extract_session_carryover
        session_path = tmp_context / "core" / "session.md"
        session_path.write_text(textwrap.dedent("""\
            ---
            name: Session
            ---
            ## Current Focus
            Working on feature X

            ## Notes for Next Session

            <guide>Context to carry forward</guide>
        """))
        result = extract_session_carryover(session_path)
        assert result == ""

    def test_handles_missing_session_file(self, tmp_path):
        from session_start import extract_session_carryover
        result = extract_session_carryover(tmp_path / "nonexistent.md")
        assert result == ""

    def test_handles_no_notes_heading(self, tmp_context):
        from session_start import extract_session_carryover
        session_path = tmp_context / "core" / "session.md"
        session_path.write_text(textwrap.dedent("""\
            ---
            name: Session
            ---
            ## Current Focus
            Working on feature X
        """))
        result = extract_session_carryover(session_path)
        assert result == ""

    def test_stops_at_next_heading(self, tmp_context):
        from session_start import extract_session_carryover
        session_path = tmp_context / "core" / "session.md"
        session_path.write_text(textwrap.dedent("""\
            ---
            name: Session
            ---
            ## Notes for Next Session
            - Important note

            ## Some Other Section
            - Should not be included
        """))
        result = extract_session_carryover(session_path)
        assert "Important note" in result
        assert "Should not be included" not in result


class TestBootstrapImliCoreIfMissing:
    def test_generates_imli_core_if_missing(self, tmp_context, tmp_rules_dir):
        from session_start import bootstrap_imli_core_if_missing
        output_path = tmp_rules_dir / "imli-core.md"
        result = bootstrap_imli_core_if_missing(tmp_context, output_path)
        assert result is True
        assert output_path.exists()

    def test_skips_if_already_exists(self, tmp_context, tmp_rules_dir):
        from session_start import bootstrap_imli_core_if_missing
        output_path = tmp_rules_dir / "imli-core.md"
        output_path.write_text("existing content")
        result = bootstrap_imli_core_if_missing(tmp_context, output_path)
        assert result is False
        assert output_path.read_text() == "existing content"


class TestMainOutput:
    def test_outputs_valid_json(self, tmp_context, tmp_rules_dir, capsys):
        from session_start import run_hook
        output_path = tmp_rules_dir / "imli-core.md"
        future_date = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")
        triggers_content = textwrap.dedent(f"""\
            ---
            name: Triggers
            ---
            ## Upcoming

            | Date | Event | Action |
            |------|-------|--------|
            | {future_date} | Big meeting | Prepare |
        """)
        (tmp_context / "core" / "triggers.md").write_text(triggers_content)
        with patch("session_start.CONTEXT_DIR", tmp_context), \
             patch("session_start.imli_CORE_PATH", output_path):
            run_hook()
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert "hookSpecificOutput" in output
        assert "additionalContext" in output["hookSpecificOutput"]
        assert "Big meeting" in output["hookSpecificOutput"]["additionalContext"]

    def test_silent_when_nothing_upcoming(self, tmp_context, tmp_rules_dir, capsys):
        from session_start import run_hook
        output_path = tmp_rules_dir / "imli-core.md"
        output_path.write_text("existing")
        past_date = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
        (tmp_context / "core" / "triggers.md").write_text(textwrap.dedent(f"""\
            ---
            name: Triggers
            ---
            ## Upcoming

            | Date | Event | Action |
            |------|-------|--------|
            | {past_date} | Old event | Done |
        """))
        with patch("session_start.CONTEXT_DIR", tmp_context), \
             patch("session_start.imli_CORE_PATH", output_path):
            run_hook()
        captured = capsys.readouterr()
        if captured.out.strip():
            output = json.loads(captured.out)
            ctx = output.get("hookSpecificOutput", {}).get("additionalContext", "")
            assert ctx == "" or "upcoming" not in ctx.lower()

    def test_outputs_setup_instructions_if_no_context(self, tmp_path, capsys):
        from session_start import run_hook
        with patch("session_start.CONTEXT_DIR", tmp_path / "nonexistent"), \
             patch("session_start.imli_CORE_PATH", tmp_path / "rules" / "imli-core.md"):
            run_hook()
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        ctx = output["hookSpecificOutput"]["additionalContext"]
        assert "setup" in ctx.lower() or "not set up" in ctx.lower()

    def test_surfaces_both_triggers_and_session_notes(self, tmp_context, tmp_rules_dir, capsys):
        from session_start import run_hook
        output_path = tmp_rules_dir / "imli-core.md"
        output_path.write_text("existing")
        future_date = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")
        (tmp_context / "core" / "triggers.md").write_text(textwrap.dedent(f"""\
            ---
            name: Triggers
            ---
            | Date | Event | Action |
            |------|-------|--------|
            | {future_date} | Team meeting | Prepare |
        """))
        (tmp_context / "core" / "session.md").write_text(textwrap.dedent("""\
            ---
            name: Session
            ---
            ## Notes for Next Session
            - Check the deploy pipeline
        """))
        with patch("session_start.CONTEXT_DIR", tmp_context), \
             patch("session_start.imli_CORE_PATH", output_path):
            run_hook()
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        ctx = output["hookSpecificOutput"]["additionalContext"]
        assert "Team meeting" in ctx
        assert "deploy pipeline" in ctx

    def test_surfaces_session_notes_alone(self, tmp_context, tmp_rules_dir, capsys):
        from session_start import run_hook
        output_path = tmp_rules_dir / "imli-core.md"
        output_path.write_text("existing")
        past_date = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
        (tmp_context / "core" / "triggers.md").write_text(textwrap.dedent(f"""\
            ---
            name: Triggers
            ---
            | Date | Event | Action |
            |------|-------|--------|
            | {past_date} | Old event | Done |
        """))
        (tmp_context / "core" / "session.md").write_text(textwrap.dedent("""\
            ---
            name: Session
            ---
            ## Notes for Next Session
            - Follow up on PR review
        """))
        with patch("session_start.CONTEXT_DIR", tmp_context), \
             patch("session_start.imli_CORE_PATH", output_path):
            run_hook()
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        ctx = output["hookSpecificOutput"]["additionalContext"]
        assert "PR review" in ctx
        assert "Upcoming Events" not in ctx
