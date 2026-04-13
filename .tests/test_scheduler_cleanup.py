"""Tests for scheduler.py cleanup command.

Verifies that cleanup deletes old log files and result date-directories
while preserving recent ones.
"""

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

SCRIPT = str(
    Path(__file__).resolve().parents[1]
    / "scheduler"
    / "skills"
    / "manage"
    / "scripts"
    / "scheduler.py"
)


def run_scheduler(tmpdir: str, args: list[str]) -> subprocess.CompletedProcess:
    """Run scheduler.py with the given args inside a temp SCHEDULER_DIR."""
    plist_dir = os.path.join(tmpdir, "plists")
    os.makedirs(plist_dir, exist_ok=True)
    env = os.environ.copy()
    env["SCHEDULER_DIR"] = tmpdir
    env["SCHEDULER_PLIST_DIR"] = plist_dir
    env["SCHEDULER_SKIP_LAUNCHCTL"] = "1"
    return subprocess.run(
        ["uv", "run", SCRIPT] + args,
        capture_output=True,
        text=True,
        env=env,
    )


class TestCleanup:
    """Test scheduler.py cleanup command."""

    def test_cleanup_removes_old_logs(self):
        """Old log files are deleted, recent ones preserved."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logs_dir = Path(tmpdir) / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)

            # Create an old log file (mtime set to 60 days ago)
            old_log = logs_dir / "2025-01-01-old-task.log"
            old_log.write_text("old log content")
            old_mtime = time.time() - (60 * 86400)
            os.utime(old_log, (old_mtime, old_mtime))

            # Create a recent log file
            recent_log = logs_dir / "2025-02-20-recent-task.log"
            recent_log.write_text("recent log content")

            result = run_scheduler(tmpdir, ["cleanup", "--max-days", "30"])
            assert result.returncode == 0
            data = json.loads(result.stdout)
            assert data["deleted_logs"] == 1

            assert not old_log.exists(), "Old log should be deleted"
            assert recent_log.exists(), "Recent log should be preserved"

    def test_cleanup_removes_old_result_dirs(self):
        """Old result date-directories are deleted, recent ones preserved."""
        with tempfile.TemporaryDirectory() as tmpdir:
            results_dir = Path(tmpdir) / "results"

            # Create an old result directory (date name well in the past)
            old_dir = results_dir / "2024-06-15"
            old_dir.mkdir(parents=True, exist_ok=True)
            (old_dir / "task-a.md").write_text("old result")

            # Create a recent result directory (today-ish)
            recent_dir = results_dir / "2026-02-25"
            recent_dir.mkdir(parents=True, exist_ok=True)
            (recent_dir / "task-b.md").write_text("recent result")

            result = run_scheduler(tmpdir, ["cleanup", "--max-days", "30"])
            assert result.returncode == 0
            data = json.loads(result.stdout)
            assert data["deleted_results"] == 1

            assert not old_dir.exists(), "Old result dir should be deleted"
            assert recent_dir.exists(), "Recent result dir should be preserved"

    def test_cleanup_default_max_days(self):
        """Defaults to 30 days when --max-days flag is omitted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Just ensure it runs and returns the default
            result = run_scheduler(tmpdir, ["cleanup"])
            assert result.returncode == 0
            data = json.loads(result.stdout)
            assert data["max_days"] == 30
