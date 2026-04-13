# Implementation Notes

- **Permissions**: Scheduled tasks run non-interactively via `claude -p` — there's no user to approve tool use. Without pre-configured permissions, any tool needing approval fails silently. Use `--permission-preset` (readonly, research, full-edit, bypass) or `--allowed-tools` to pre-approve the tools a task needs. The `bypass` preset uses `--dangerously-skip-permissions` to skip all checks. After adding permissions to existing tasks, run `repair --force` to regenerate wrappers.
- **One-off tasks**: Tasks created with `--run-once` auto-complete after their first successful run. They remain in the registry with status `completed` so results and logs are preserved. They can be removed later with the Remove operation.
- **Lock file**: The wrapper uses a PID-based lock to prevent concurrent runs of the same task. If a previous run is still active, the new run is skipped. On Windows, the lock uses `Get-Process` instead of `kill -0`.
- **Sleep/missed run behavior**: All platforms catch up on missed runs. macOS launchd fires one missed run on wake. Linux systemd timers use `Persistent=true`. Windows Task Scheduler uses `StartWhenAvailable=true`.
- **Working directory**: Defaults to the current project. Tasks that use marketplace skills should point to the marketplace project directory.
- **Auth**: Works with Claude subscription login (default) or platform-specific API key storage (macOS Keychain, Linux GNOME Keyring or file, Windows Credential Manager or file).
- **Project-level storage**: By default, the scheduler stores state at `<project>/.claude/scheduler/` when run inside a project (detected via `.git` or `CLAUDE.md`). Override with the `SCHEDULER_DIR` env var or fall back to `~/.claude/scheduler/` when outside a project.
- **Results**: Saved as markdown at `<scheduler_dir>/results/YYYY-MM-DD/{id}-HHMMSS.md` (timestamped to prevent same-day overwrites). If `--output-directory` was specified, results go to `<output_dir>/{id}.md` (stable filenames, no date subdirectories). Legacy `{id}.md` files are still found by the results command.
- **Logs**: Saved at `<scheduler_dir>/logs/YYYY-MM-DD-{id}.log`.
- **Cleanup**: Use `cleanup --max-days N` to delete old logs and result directories. Defaults to 30 days.
- **Platform field**: Each task records which platform it was created on. The `repair` command can detect mismatches (e.g. a macOS task on Linux) and reinstall using the current platform's backend.
- **Upgrading from v1**: The registry auto-migrates from v1 to v2 on first load, adding a `platform` field to existing tasks. Wrapper templates differ per platform; to apply the correct template, run `repair` or remove and re-add tasks.
