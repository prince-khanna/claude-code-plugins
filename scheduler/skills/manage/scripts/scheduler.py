#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["croniter>=2.0.0"]
# ///
"""Scheduler engine — registry CRUD, wrapper generation, platform scheduler interaction.

Manages scheduled tasks for Prince Plugins across macOS (launchd), Linux (systemd),
and Windows (Task Scheduler). All CRUD commands output JSON to stdout; errors go
to stderr.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow imports from the backends/ package co-located with this script
sys.path.insert(0, str(Path(__file__).resolve().parent))

from croniter import croniter
from permission_presets import expand_preset, is_bypass_preset
from platform_detect import detect_platform, get_backend

# ---------------------------------------------------------------------------
# Constants / paths
# ---------------------------------------------------------------------------


def _find_project_root() -> Path | None:
    """Walk up from CWD looking for .git or CLAUDE.md to find a project root."""
    current = Path.cwd()
    for directory in [current, *current.parents]:
        if (directory / ".git").exists() or (directory / "CLAUDE.md").exists():
            return directory
    return None


def _resolve_scheduler_dir() -> Path:
    """Resolve the scheduler directory with priority:

    1. SCHEDULER_DIR env var (explicit override)
    2. <project_root>/.claude/scheduler/ if a project root is found
    3. ~/.claude/scheduler/ fallback
    """
    env_dir = os.environ.get("SCHEDULER_DIR")
    if env_dir:
        return Path(env_dir)

    project_root = _find_project_root()
    if project_root:
        return project_root / ".claude" / "scheduler"

    return Path.home() / ".claude" / "scheduler"


SCHEDULER_DIR = _resolve_scheduler_dir()
REGISTRY_FILE = SCHEDULER_DIR / "registry.json"
WRAPPERS_DIR = SCHEDULER_DIR / "wrappers"
LOGS_DIR = SCHEDULER_DIR / "logs"
RESULTS_DIR = SCHEDULER_DIR / "results"
SCHEDULER_PY = Path(__file__).resolve()

# Platform backend (auto-detected from current OS)
backend = get_backend()

# ---------------------------------------------------------------------------
# Registry helpers
# ---------------------------------------------------------------------------


def _ensure_dirs() -> None:
    """Create scheduler directories if they don't exist."""
    for d in (SCHEDULER_DIR, WRAPPERS_DIR, LOGS_DIR, RESULTS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def _load_registry() -> dict:
    """Load the registry from disk, creating a fresh one if needed.

    Automatically migrates v1 registries to v2 (adds platform field to tasks).
    """
    _ensure_dirs()
    if REGISTRY_FILE.exists():
        with open(REGISTRY_FILE, "r") as f:
            registry = json.load(f)

        # Migrate v1 -> v2: add platform field to tasks that lack it
        if registry.get("version", 1) < 2:
            current_platform = detect_platform()
            for task in registry.get("tasks", {}).values():
                if "platform" not in task:
                    task["platform"] = current_platform
            registry["version"] = 2
            _save_registry(registry)

        return registry
    return {"version": 2, "tasks": {}}


def _save_registry(registry: dict) -> None:
    """Persist the registry to disk atomically.

    Writes to a temp file first, then uses os.replace() for an atomic
    rename, preventing corrupt/partial writes on interruption.
    """
    _ensure_dirs()
    tmp_file = REGISTRY_FILE.with_suffix(".tmp")
    with open(tmp_file, "w") as f:
        json.dump(registry, f, indent=2)
    os.replace(str(tmp_file), str(REGISTRY_FILE))


def _error(msg: str) -> None:
    """Print error to stderr and exit with code 1."""
    print(msg, file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Cron helpers
# ---------------------------------------------------------------------------

WEEKDAY_NAMES = {0: "Sunday", 1: "Monday", 2: "Tuesday", 3: "Wednesday",
                 4: "Thursday", 5: "Friday", 6: "Saturday"}


def _validate_cron(expr: str) -> None:
    """Raise if *expr* is not a valid 5-field cron expression."""
    if not croniter.is_valid(expr):
        _error(f"Invalid cron expression: {expr}")


def _humanize_cron(expr: str) -> str:
    """Best-effort conversion of a cron expression to a human-readable string."""
    parts = expr.split()
    if len(parts) != 5:
        return expr
    minute, hour, dom, month, dow = parts

    time_str = ""
    if minute != "*" and hour != "*":
        h = int(hour)
        m = int(minute)
        ampm = "AM" if h < 12 else "PM"
        display_h = h % 12 or 12
        time_str = f"{display_h}:{m:02d} {ampm}"

    # Every minute
    if all(p == "*" for p in parts):
        return "Every minute"

    # Every N minutes
    if minute.startswith("*/") and hour == "*" and dom == "*" and month == "*" and dow == "*":
        return f"Every {minute[2:]} minutes"

    # Every hour
    if hour == "*" and dom == "*" and month == "*" and dow == "*":
        if minute != "*":
            return f"Every hour at minute {minute}"
        return "Every hour"

    # Daily
    if dom == "*" and month == "*" and dow == "*" and time_str:
        return f"Every day at {time_str}"

    # Specific weekday(s)
    if dom == "*" and month == "*" and dow != "*" and time_str:
        # parse dow — could be single, comma-separated, or range
        day_strs = _expand_dow(dow)
        if day_strs:
            return f"Every {', '.join(day_strs)} at {time_str}"

    # Specific day of month
    if dom != "*" and month == "*" and dow == "*" and time_str:
        return f"Day {dom} of every month at {time_str}"

    return expr


def _expand_dow(dow_field: str) -> list[str]:
    """Expand a dow field like '1', '1,3,5', or '1-5' into weekday names."""
    nums: list[int] = []
    for part in dow_field.split(","):
        if "-" in part:
            lo, hi = part.split("-", 1)
            nums.extend(range(int(lo), int(hi) + 1))
        else:
            nums.append(int(part))
    return [WEEKDAY_NAMES.get(n, str(n)) for n in nums]


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def _resolve_permissions(args: argparse.Namespace) -> dict | None:
    """Build the permissions dict from CLI args, resolving presets.

    Returns None if no permission configuration was requested.
    """
    preset = getattr(args, "permission_preset", None)
    allowed_tools = getattr(args, "allowed_tools", None)
    permission_mode = getattr(args, "permission_mode", None)

    if not preset and not allowed_tools and not permission_mode:
        return None

    result: dict = {
        "allowed_tools": None,
        "permission_mode": None,
        "preset": None,
    }

    if preset:
        result["preset"] = preset
        if is_bypass_preset(preset):
            # bypass preset → use --dangerously-skip-permissions
            result["permission_mode"] = "bypassPermissions"
            if allowed_tools:
                print("Warning: --allowed-tools ignored when using bypass preset",
                      file=sys.stderr)
                allowed_tools = None
        else:
            # Expand preset to tool list, merge with any explicit --allowed-tools
            preset_tools = expand_preset(preset)
            if allowed_tools:
                # Merge: preset tools + explicit tools, deduplicated preserving order
                seen = set()
                merged = []
                for tool in preset_tools + allowed_tools:
                    if tool not in seen:
                        seen.add(tool)
                        merged.append(tool)
                result["allowed_tools"] = merged
            else:
                result["allowed_tools"] = preset_tools

    elif allowed_tools:
        result["allowed_tools"] = allowed_tools

    if permission_mode:
        result["permission_mode"] = permission_mode

    return result


def cmd_add(args: argparse.Namespace) -> None:
    """Add a new scheduled task."""
    if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9_-]*$', args.id):
        _error(f"Invalid task ID '{args.id}'. Use only letters, numbers, hyphens, and underscores.")

    _validate_cron(args.cron)

    if args.type not in ("skill", "prompt", "script"):
        _error(f"Invalid type '{args.type}'. Must be one of: skill, prompt, script")

    registry = _load_registry()

    if args.id in registry["tasks"]:
        _error(f"Task '{args.id}' already exists. Use a different ID.")

    now = datetime.now(timezone.utc).isoformat()

    # Resolve output_directory to absolute path if provided
    output_directory = None
    if args.output_directory:
        output_directory = str(Path(args.output_directory).expanduser().resolve())

    # Resolve permission configuration
    permissions = _resolve_permissions(args)

    task = {
        "id": args.id,
        "name": args.name,
        "type": args.type,
        "target": args.target,
        "working_directory": args.working_directory,
        "schedule": {
            "cron": args.cron,
            "human": _humanize_cron(args.cron),
        },
        "safety": {
            "max_turns": args.max_turns,
            "timeout_minutes": args.timeout_minutes,
        },
        "run_once": args.run_once,
        "output_directory": output_directory,
        "permissions": permissions,
        "platform": detect_platform(),
        "status": "active",
        "created_at": now,
        "last_run": None,
    }

    registry["tasks"][args.id] = task
    _save_registry(registry)

    # Generate wrapper and install platform schedule
    wrapper_path = backend.generate_wrapper(task, SCHEDULER_DIR, SCHEDULER_PY, WRAPPERS_DIR)
    backend.install_schedule(args.id, task, wrapper_path, SCHEDULER_DIR, LOGS_DIR)

    print(json.dumps(task, indent=2))


def cmd_list(args: argparse.Namespace) -> None:
    """List all tasks."""
    registry = _load_registry()
    tasks = list(registry["tasks"].values())
    print(json.dumps(tasks, indent=2))


def cmd_get(args: argparse.Namespace) -> None:
    """Get details of a specific task."""
    registry = _load_registry()
    task = registry["tasks"].get(args.id)
    if task is None:
        _error(f"Task '{args.id}' not found.")
    print(json.dumps(task, indent=2))


def cmd_remove(args: argparse.Namespace) -> None:
    """Remove a task from the registry."""
    registry = _load_registry()
    if args.id not in registry["tasks"]:
        _error(f"Task '{args.id}' not found.")

    # Uninstall platform schedule (unload + delete artifacts)
    backend.uninstall_schedule(args.id)

    # Remove wrapper
    wrapper = WRAPPERS_DIR / f"{args.id}{backend.wrapper_extension()}"
    if wrapper.exists():
        wrapper.unlink()

    task = registry["tasks"].pop(args.id)
    _save_registry(registry)

    print(json.dumps({"removed": args.id}, indent=2))


def cmd_pause(args: argparse.Namespace) -> None:
    """Pause a task (unload from platform scheduler)."""
    registry = _load_registry()
    if args.id not in registry["tasks"]:
        _error(f"Task '{args.id}' not found.")

    if registry["tasks"][args.id]["status"] == "paused":
        _error(f"Task '{args.id}' is already paused.")

    try:
        backend.unload_schedule(args.id)
    except RuntimeError as exc:
        print(f"Error pausing task '{args.id}': {exc}", file=sys.stderr)
        sys.exit(1)

    registry["tasks"][args.id]["status"] = "paused"
    _save_registry(registry)
    print(json.dumps(registry["tasks"][args.id], indent=2))


def cmd_resume(args: argparse.Namespace) -> None:
    """Resume a paused task (load into platform scheduler)."""
    registry = _load_registry()
    if args.id not in registry["tasks"]:
        _error(f"Task '{args.id}' not found.")

    if registry["tasks"][args.id]["status"] == "active":
        _error(f"Task '{args.id}' is already active.")

    try:
        backend.load_schedule(args.id)
    except RuntimeError as exc:
        print(f"Error resuming task '{args.id}': {exc}", file=sys.stderr)
        sys.exit(1)

    registry["tasks"][args.id]["status"] = "active"
    _save_registry(registry)
    print(json.dumps(registry["tasks"][args.id], indent=2))


def cmd_complete(args: argparse.Namespace) -> None:
    """Mark a task as completed and unload from platform scheduler.

    Used by run-once wrappers to self-deactivate after successful execution.
    Unlike 'pause', this sets status to 'completed' to indicate the task
    finished naturally rather than being manually paused.
    """
    registry = _load_registry()
    if args.id not in registry["tasks"]:
        _error(f"Task '{args.id}' not found.")

    try:
        backend.unload_schedule(args.id)
    except RuntimeError as exc:
        print(f"Error completing task '{args.id}': {exc}", file=sys.stderr)
        sys.exit(1)

    registry["tasks"][args.id]["status"] = "completed"
    _save_registry(registry)
    print(json.dumps(registry["tasks"][args.id], indent=2))


def cmd_run(args: argparse.Namespace) -> None:
    """Execute a task's wrapper script directly."""
    registry = _load_registry()
    if args.id not in registry["tasks"]:
        _error(f"Task '{args.id}' not found.")

    wrapper = WRAPPERS_DIR / f"{args.id}{backend.wrapper_extension()}"
    if not wrapper.exists():
        _error(f"Wrapper script not found for task '{args.id}'. Run 'repair' first.")

    exit_code = backend.run_wrapper(wrapper)
    sys.exit(exit_code)


def cmd_logs(args: argparse.Namespace) -> None:
    """Show recent log files for a task."""
    registry = _load_registry()
    if args.id not in registry["tasks"]:
        _error(f"Task '{args.id}' not found.")

    # Search task-first logs: logs/{id}/YYYY-MM-DD.log
    task_dir_logs = sorted(
        (LOGS_DIR / args.id).glob("*.log"), reverse=True
    ) if (LOGS_DIR / args.id).is_dir() else []
    # Backward compat: date-first logs: logs/YYYY-MM-DD/{id}.log
    date_dir_logs = list(LOGS_DIR.glob(f"*/{args.id}.log"))
    # Backward compat: flat logs: logs/YYYY-MM-DD-{id}.log
    flat_logs = list(LOGS_DIR.glob(f"*-{args.id}.log"))
    # Combine, deduplicate by resolved path, sort by name/date descending
    seen = set()
    all_logs = []
    for log_file in task_dir_logs + sorted(date_dir_logs + flat_logs, reverse=True):
        resolved = log_file.resolve()
        if resolved not in seen:
            seen.add(resolved)
            all_logs.append(log_file)
    all_logs = all_logs[:3]

    if not all_logs:
        print(f"No log files found for task '{args.id}'.", file=sys.stderr)
        return

    for log_file in all_logs:
        # Show relative path from logs dir for clarity
        try:
            label = str(log_file.relative_to(LOGS_DIR))
        except ValueError:
            label = log_file.name
        print(f"\n=== {label} ===")
        print(log_file.read_text())

    # Show session log path if available in last_run
    task = registry["tasks"][args.id]
    session_log = task.get("last_run", {}).get("session_log")
    if session_log:
        exists_note = "" if Path(session_log).exists() else " (file not found)"
        print(f"\n=== Session log (latest run){exists_note} ===")
        print(session_log)


def cmd_results(args: argparse.Namespace) -> None:
    """Show result files for a task."""
    registry = _load_registry()
    task = registry["tasks"].get(args.id)
    if task is None:
        _error(f"Task '{args.id}' not found.")

    # If task has a custom output_directory, look there (flat, no date subdirs)
    custom_dir = task.get("output_directory")
    if custom_dir:
        custom_result = Path(custom_dir) / f"{args.id}.md"
        if custom_result.exists():
            print(f"=== {custom_result} ===")
            print(custom_result.read_text())
            return
        else:
            print(f"No result files found for task '{args.id}'.", file=sys.stderr)
            return

    # Search task-first results: results/{id}/YYYY-MM-DD/{id}-HHMMSS.md
    task_results = sorted(
        (RESULTS_DIR / args.id).glob(f"*/{args.id}-[0-9]*.md"),
        key=lambda p: (p.parent.name, p.name), reverse=True,
    ) if (RESULTS_DIR / args.id).is_dir() else []
    # Backward compat: date-first results: results/YYYY-MM-DD/{id}.md or {id}-HHMMSS.md
    legacy = list(RESULTS_DIR.glob(f"*/{args.id}.md"))
    timestamped = list(RESULTS_DIR.glob(f"*/{args.id}-[0-9]*.md"))
    # Combine, deduplicate by resolved path
    seen = set()
    result_files = []
    for rf in task_results + sorted(set(legacy + timestamped),
                                     key=lambda p: (p.parent.name, p.name), reverse=True):
        resolved = rf.resolve()
        if resolved not in seen:
            seen.add(resolved)
            result_files.append(rf)

    if not result_files:
        print(f"No result files found for task '{args.id}'.", file=sys.stderr)
        return

    if args.all:
        for rf in result_files:
            try:
                label = str(rf.relative_to(RESULTS_DIR))
            except ValueError:
                label = rf.name
            print(f"\n=== {label} ===")
            print(rf.read_text())
    else:
        latest = result_files[0]
        try:
            label = str(latest.relative_to(RESULTS_DIR))
        except ValueError:
            label = latest.name
        print(f"=== {label} ===")
        print(latest.read_text())


def cmd_update_last_run(args: argparse.Namespace) -> None:
    """Update the last_run field of a task."""
    registry = _load_registry()
    if args.id not in registry["tasks"]:
        _error(f"Task '{args.id}' not found.")

    now = datetime.now(timezone.utc).isoformat()

    last_run = {
        "timestamp": now,
        "exit_code": args.exit_code,
        "duration_seconds": args.duration,
        "result_file": args.result_file,
    }

    if args.session_log:
        last_run["session_log"] = args.session_log

    registry["tasks"][args.id]["last_run"] = last_run

    # Set status to error if exit code is non-zero
    if args.exit_code != 0:
        registry["tasks"][args.id]["status"] = "error"

    _save_registry(registry)
    print(json.dumps(registry["tasks"][args.id], indent=2))


def cmd_repair(args: argparse.Namespace) -> None:
    """Regenerate missing wrapper scripts and schedule artifacts for active tasks.

    With --force, regenerates ALL wrappers regardless of whether they already
    exist.  Useful after adding permissions to existing tasks or after a
    template update.
    """
    registry = _load_registry()
    force = getattr(args, "force", False)
    issues_fixed = 0

    for task_id, task in registry["tasks"].items():
        if task["status"] != "active":
            continue

        wrapper_path = WRAPPERS_DIR / f"{task_id}{backend.wrapper_extension()}"

        if force or not wrapper_path.exists():
            backend.generate_wrapper(task, SCHEDULER_DIR, SCHEDULER_PY, WRAPPERS_DIR)
            label = "Force-regenerated" if wrapper_path.exists() and force else "Regenerated"
            print(f"{label} wrapper for '{task_id}'")
            issues_fixed += 1

        if not backend.schedule_artifact_exists(task_id):
            backend.install_schedule(task_id, task, wrapper_path, SCHEDULER_DIR, LOGS_DIR)
            print(f"Regenerated schedule for '{task_id}'")
            issues_fixed += 1

    if issues_fixed > 0:
        print(f"Repair complete: {issues_fixed} issue(s) fixed.")
    else:
        print("Repair complete: no issues found.")


def cmd_cleanup(args: argparse.Namespace) -> None:
    """Delete log and result files older than --max-days."""
    import shutil
    import time

    max_days = args.max_days
    cutoff = time.time() - (max_days * 86400)
    deleted_logs = 0
    deleted_results = 0

    def _cleanup_date_entries(base_dir: Path, extension: str) -> int:
        """Clean up date-named files/dirs older than cutoff within a directory.

        Handles both task-first layout ({id}/YYYY-MM-DD.log or {id}/YYYY-MM-DD/)
        and legacy date-first layout (YYYY-MM-DD/ or YYYY-MM-DD-{id}.ext).
        """
        count = 0
        if not base_dir.exists():
            return count

        for entry in base_dir.iterdir():
            if entry.is_dir():
                # Could be a task-first dir ({id}/) or a legacy date dir (YYYY-MM-DD/)
                try:
                    # Legacy: date-first directory
                    dir_date = datetime.strptime(entry.name, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    if dir_date.timestamp() < cutoff:
                        count += sum(1 for _ in entry.rglob(f"*{extension}"))
                        shutil.rmtree(entry)
                except ValueError:
                    # Task-first directory — recurse into it to clean date entries
                    for sub in entry.iterdir():
                        if sub.is_dir():
                            try:
                                sub_date = datetime.strptime(sub.name, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                                if sub_date.timestamp() < cutoff:
                                    count += sum(1 for _ in sub.rglob(f"*{extension}"))
                                    shutil.rmtree(sub)
                            except ValueError:
                                continue
                        elif sub.is_file() and sub.suffix == extension:
                            # Task-first: logs/{id}/YYYY-MM-DD.log
                            try:
                                file_date = datetime.strptime(sub.stem, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                                if file_date.timestamp() < cutoff:
                                    sub.unlink()
                                    count += 1
                            except ValueError:
                                continue
                    # Remove task dir if now empty
                    if entry.is_dir() and not any(entry.iterdir()):
                        entry.rmdir()
            elif entry.is_file() and entry.suffix == extension:
                # Legacy: flat files (logs/YYYY-MM-DD-{id}.log)
                if entry.stat().st_mtime < cutoff:
                    entry.unlink()
                    count += 1
        return count

    deleted_logs = _cleanup_date_entries(LOGS_DIR, ".log")
    deleted_results = _cleanup_date_entries(RESULTS_DIR, ".md")

    print(json.dumps({
        "deleted_logs": deleted_logs,
        "deleted_results": deleted_results,
        "max_days": max_days,
    }, indent=2))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description=" Prince Plugins Scheduler Engine",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- add ---
    p_add = subparsers.add_parser("add", help="Add a new scheduled task")
    p_add.add_argument("--id", required=True, help="Unique task identifier")
    p_add.add_argument("--name", required=True, help="Human-readable task name")
    p_add.add_argument("--type", required=True, choices=["skill", "prompt", "script"],
                       help="Task type")
    p_add.add_argument("--target", required=True, help="Skill name, prompt text, or script path")
    p_add.add_argument("--cron", required=True, help="Cron schedule expression (5 fields)")
    p_add.add_argument("--working-directory", required=True, help="Working directory for task")
    p_add.add_argument("--max-turns", type=int, default=20, help="Max Claude turns (default: 20)")
    p_add.add_argument("--timeout-minutes", type=int, default=15,
                       help="Timeout in minutes (default: 15)")
    p_add.add_argument("--run-once", action="store_true", default=False,
                       help="Run once then auto-complete (one-off task)")
    p_add.add_argument("--output-directory", default=None,
                       help="Custom directory for task result files")
    p_add.add_argument("--allowed-tools", nargs="*", default=None,
                       help="Individual tool specs for --allowedTools (e.g. Read Write 'Bash(git *)')")
    p_add.add_argument("--permission-mode", default=None,
                       choices=["default", "acceptEdits", "plan", "dontAsk", "bypassPermissions"],
                       help="Claude Code permission mode for non-interactive execution")
    p_add.add_argument("--permission-preset", default=None,
                       choices=["readonly", "full-edit", "research", "bypass"],
                       help="Named permission preset (expands to a set of --allowedTools)")
    p_add.set_defaults(func=cmd_add)

    # --- list ---
    p_list = subparsers.add_parser("list", help="List all tasks")
    p_list.set_defaults(func=cmd_list)

    # --- get ---
    p_get = subparsers.add_parser("get", help="Get task details")
    p_get.add_argument("--id", required=True, help="Task ID")
    p_get.set_defaults(func=cmd_get)

    # --- remove ---
    p_remove = subparsers.add_parser("remove", help="Remove a task")
    p_remove.add_argument("--id", required=True, help="Task ID")
    p_remove.set_defaults(func=cmd_remove)

    # --- pause ---
    p_pause = subparsers.add_parser("pause", help="Pause a task")
    p_pause.add_argument("--id", required=True, help="Task ID")
    p_pause.set_defaults(func=cmd_pause)

    # --- resume ---
    p_resume = subparsers.add_parser("resume", help="Resume a paused task")
    p_resume.add_argument("--id", required=True, help="Task ID")
    p_resume.set_defaults(func=cmd_resume)

    # --- complete ---
    p_complete = subparsers.add_parser("complete", help="Mark a task as completed and unload")
    p_complete.add_argument("--id", required=True, help="Task ID")
    p_complete.set_defaults(func=cmd_complete)

    # --- run ---
    p_run = subparsers.add_parser("run", help="Execute a task immediately")
    p_run.add_argument("--id", required=True, help="Task ID")
    p_run.set_defaults(func=cmd_run)

    # --- logs ---
    p_logs = subparsers.add_parser("logs", help="Show recent logs for a task")
    p_logs.add_argument("--id", required=True, help="Task ID")
    p_logs.set_defaults(func=cmd_logs)

    # --- results ---
    p_results = subparsers.add_parser("results", help="Show results for a task")
    p_results.add_argument("--id", required=True, help="Task ID")
    p_results.add_argument("--all", action="store_true", help="Show all results")
    p_results.set_defaults(func=cmd_results)

    # --- update-last-run ---
    p_ulr = subparsers.add_parser("update-last-run", help="Update last run info")
    p_ulr.add_argument("--id", required=True, help="Task ID")
    p_ulr.add_argument("--exit-code", type=int, required=True, help="Exit code")
    p_ulr.add_argument("--duration", type=int, required=True, help="Duration in seconds")
    p_ulr.add_argument("--result-file", required=True, help="Path to result file")
    p_ulr.add_argument("--session-log", default=None, help="Path to Claude Code JSONL session log")
    p_ulr.set_defaults(func=cmd_update_last_run)

    # --- repair ---
    p_repair = subparsers.add_parser("repair", help="Regenerate missing wrappers and schedules")
    p_repair.add_argument("--force", action="store_true", default=False,
                          help="Regenerate ALL wrappers, not just missing ones")
    p_repair.set_defaults(func=cmd_repair)

    # --- cleanup ---
    p_cleanup = subparsers.add_parser("cleanup", help="Delete old logs and results")
    p_cleanup.add_argument("--max-days", type=int, default=30,
                           help="Delete files older than N days (default: 30)")
    p_cleanup.set_defaults(func=cmd_cleanup)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
