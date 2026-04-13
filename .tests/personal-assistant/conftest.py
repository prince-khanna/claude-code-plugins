"""Shared fixtures for personal-assistant v2 tests."""
import json
import textwrap
from pathlib import Path

import pytest


@pytest.fixture
def tmp_context(tmp_path):
    """Create a mock ~/.claude/.context/ directory with sample context files."""
    context_dir = tmp_path / ".context"
    core_dir = context_dir / "core"
    core_dir.mkdir(parents=True)

    (core_dir / "identity.md").write_text(textwrap.dedent("""\
        ---
        name: Identity
        ---
        ## Basic Info
        - **Name**: Test User
        - **Location**: California (PT)
        - **Birthday**: Jan 1, 1990

        ## Professional
        - Software engineer at Acme Corp
        - Focus: backend systems

        ## Personal Life
        - Enjoys hiking
    """))

    (core_dir / "preferences.md").write_text(textwrap.dedent("""\
        ---
        name: Preferences
        ---
        ## Communication
        - Start concise, expand on request
        - Bullet points over paragraphs
    """))

    (core_dir / "rules.md").write_text(textwrap.dedent("""\
        ---
        name: Rules
        ---
        ## Rules
        - NEVER commit without asking
        - ALWAYS run tests before pushing
        - NEVER use echo $VAR to check secrets
    """))

    (core_dir / "projects.md").write_text(textwrap.dedent("""\
        ---
        name: Projects
        ---
        ## Active Projects

        | Project | Description | Location | Status |
        |---------|-------------|----------|--------|
        | Project Alpha | Main product | ~/projects/alpha | Active |
        | Project Beta | Side project | ~/projects/beta | Active |
    """))

    (core_dir / "triggers.md").write_text(textwrap.dedent("""\
        ---
        name: Triggers
        ---
        ## Upcoming

        | Date | Event | Action |
        |------|-------|--------|
        | 2026-03-10 | Client demo | Prepare slides |
        | 2026-04-01 | Tax deadline | File taxes |
        | 2025-12-25 | Past event | Should be ignored |
    """))

    (core_dir / "session.md").write_text(textwrap.dedent("""\
        ---
        name: Session
        ---
        ## Current Focus
        Working on v2 migration
    """))

    (core_dir / "improvements.md").write_text(textwrap.dedent("""\
        ---
        name: Improvements
        ---
        ## Friction Log
        ## Active Proposals
        ## Applied & Verified
    """))

    (context_dir / "CLAUDE.md").write_text("# Imli's Context System\nInstructions here.")
    (context_dir / "context-update.md").write_text("# Context Update Instructions\nUpdate here.")

    return context_dir


@pytest.fixture
def tmp_rules_dir(tmp_path):
    """Create a mock ~/.claude/rules/ directory."""
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir(parents=True)
    return rules_dir


@pytest.fixture
def hook_input_startup():
    return json.dumps({"hookEventName": "SessionStart", "sessionType": "startup"})


@pytest.fixture
def hook_input_compact():
    return json.dumps({"hookEventName": "SessionStart", "sessionType": "compact"})
