# Changelog

All notable changes to the Scheduler plugin.

## [1.2.1] - 2026-03-23

### Fixed

- **Pause/resume silently failed on all platforms** -- `unload_schedule` and `load_schedule` in macOS, Linux, and Windows backends never verified the OS-level operation succeeded. Registry would show "paused" while the job kept running. All three backends now verify state after load/unload and raise `RuntimeError` on failure.
- **`cmd_pause` and `cmd_resume` updated registry unconditionally** -- now wrapped in try/except so the registry is only updated if the backend operation actually succeeds. Prints clear error and exits with code 1 on failure.
- **Base backend missing error contract** -- `load_schedule` and `unload_schedule` docstrings now specify `RuntimeError` is raised on failure.

### Changed

- **SKILL.md Pause operation** -- added post-pause OS-level verification step with platform-specific commands (launchctl, systemctl, schtasks)
- **SKILL.md Error Recovery** -- added "Task still runs after pausing" entry with diagnosis and manual fix steps for all platforms
- **SKILL.md List operation** -- added health-check hint to verify paused tasks are actually unloaded at the OS level

## [1.2.0] - 2026-03-06

### Fixed

- **Linux wrapper missing `unset CLAUDECODE`** -- scheduled tasks on Linux could detect a nested Claude Code session and auto-create worktrees
- **Windows wrapper missing `Remove-Item Env:CLAUDECODE`** -- same nested session bug on Windows
- **Permission presets missing `bun`** -- added `Bash(bun *)` and `Bash(bunx *)` to the full-edit preset

### Changed

- **Improved skill description** -- trigger-optimized per skill-creator guidance with `user-invocable: true` frontmatter
- **Complete operation menu** -- added Cleanup (#9) and Repair (#10) to the numbered menu in SKILL.md
- **Extracted shared `_parse_cron_field`** to `cron_utils.py` -- eliminates duplication across linux, windows, and macos backends
- **Extracted shared wrapper rendering** to `base.py._render_wrapper()` -- backends now delegate common string substitution to the base class

## [1.1.2] - 2026-03-05

### Fixed

- Updated old plugin references after creator-stack consolidation

### Changed

- Improved skill tone consistency and structural fixes

## [1.1.0] - 2026-03-02

### Added

- **Session log capture** for macOS, Linux, and Windows wrappers
- **Date-organized logs** with task-first, then date directory structure
- `cmd_logs` and `cmd_cleanup` commands for log management

### Changed

- Documented session log capture, log organization, and repair workflow in README

## [1.0.3] - 2026-03-01

### Fixed

- Replaced "Run Now" with deferred scheduling for Claude Code compatibility
- Unset `CLAUDECODE` env var to prevent worktree creation in scheduled tasks

## [1.0.2] - 2026-02-27

### Fixed

- Added `~/.local/bin` to macOS wrapper PATH for `uv` discovery
- Fixed skill invocation command in docs and added example prompt

### Changed

- Updated marketplace and plugin documentation

## [1.0.1] - 2026-02-26

### Added

- **Per-task permission handling** for non-interactive runs
- **Use cases reference** document for automation ideas
- **Cross-platform support** -- macOS (launchd), Linux (systemd), Windows (Task Scheduler)

### Fixed

- Reliability improvements: registry feedback, timestamped results, atomic writes, cleanup

## [1.0.0] - 2026-02-25

### Added

- **`manage` skill** -- Conversational orchestrator for scheduling Claude Code tasks
- **`scheduler.py` engine** -- Core registry CRUD with add, list, pause, resume, remove, view results
- **One-off and recurring tasks** with cron expression support
- **Project-level storage** and per-task output directories
- **Lock file** and structured logging
- **Platform detection** via `platform_detect.py`
- **macOS backend** with launchd/plist wrapper template

### Fixed

- Replaced GNU `timeout` with macOS-compatible timeout function
- Plist isolation, idempotency guards, repair output, ID validation
