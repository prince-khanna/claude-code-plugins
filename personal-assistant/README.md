# Personal Assistant (Imli)

Meet **Imli** -- your AI personal assistant who actually remembers you.

Imli transforms Claude Code from a stateless AI into a personal assistant with persistent memory. She learns your preferences, tracks your projects, remembers key people in your life, and gets better at helping you over time.

## v2.0 Highlights

- **Native context delivery** -- core context loaded via `~/.claude/rules/imli-core.md` (zero per-message overhead)
- **Proactive triggers** -- upcoming events surfaced automatically at session start
- **Compaction resilience** -- context survives long conversations
- **Self-auditing** -- `/context-health` and `/evolve` skills for maintenance

## Prerequisites

- Prince Plugins marketplace added -- see [main README](../README.md)

## Installation

```
/plugin install personal-assistant@prince--plugins
```

When prompted, select **"Install for you (user scope)"** — the first and recommended option.

Restart Claude Code, then run first-time setup:

```
/personal-assistant:setup
```

This initializes the context system at `~/.claude/.context/`, generates `~/.claude/rules/imli-core.md`, and optionally walks you through onboarding.

### Upgrading from v1

```
/personal-assistant:migrate
```

Preserves 100% of your personal data. Only the delivery mechanism changes.

## Commands

| Command                              | Description                                                               |
| ------------------------------------ | ------------------------------------------------------------------------- |
| `/personal-assistant:setup`          | First-time setup -- initializes context system and generates imli-core.md |
| `/personal-assistant:onboard`        | Guided conversation to populate your context                              |
| `/personal-assistant:migrate`        | Migrate between versions (preserves all data)                             |
| `/personal-assistant:update-context` | Capture new info from current conversation                                |

## Skills

| Skill             | Description                                                |
| ----------------- | ---------------------------------------------------------- |
| `/sync-context`   | Regenerate imli-core.md from context source files          |
| `/context-health` | Audit context for staleness, bloat, and contradictions     |
| `/retrospective`  | Capture friction, corrections, and improvements            |
| `/evolve`         | Check Imli's architecture against Claude Code capabilities |

## How It Works

### Context Delivery (v2)

```
Session Start
  |
  +-- Claude Code loads ~/.claude/rules/imli-core.md (native, zero overhead)
  |   (identity summary, preferences, ALL rules, active projects)
  |
  +-- SessionStart hook fires
  |   +-- Checks triggers.md for events within 7 days
  |   +-- Bootstraps imli-core.md if missing
  |
  +-- Imli reads full context files on-demand for substantive tasks
      (~/.claude/.context/core/)
```

### Context Updates

- `/update-context` -- scan conversation for new information
- `/retrospective` -- end-of-session friction capture
- `/sync-context` -- regenerate imli-core.md after changes

### Self-Improvement

- `/context-health` -- audit data quality
- `/evolve` -- check for new Claude Code capabilities
- `improvements.md` -- cross-project friction tracking
