"""Tests for scheduler.py lifecycle operations: pause, resume, repair, and error status.

Uses a temporary directory as SCHEDULER_DIR and SCHEDULER_PLIST_DIR,
and skips launchctl calls via SCHEDULER_SKIP_LAUNCHCTL=1.
"""

import json
import os
import subprocess
import tempfile
from pathlib import Path

SCRIPT = (
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
        ["uv", "run", str(SCRIPT)] + args,
        capture_output=True,
        text=True,
        env=env,
    )


def add_default_task(
    tmpdir: str,
    *,
    task_id: str = "lifecycle-task",
    name: str = "Lifecycle Task",
    task_type: str = "skill",
    target: str = "generate-report",
    cron: str = "0 8 * * 1",
    workdir: str | None = None,
) -> subprocess.CompletedProcess:
    """Add a task with sensible defaults."""
    if workdir is None:
        workdir = tmpdir
    return run_scheduler(
        tmpdir,
        [
            "add",
            "--id",
            task_id,
            "--name",
            name,
            "--type",
            task_type,
            "--target",
            target,
            "--cron",
            cron,
            "--working-directory",
            workdir,
        ],
    )


# ---------- tests ----------


class TestSchedulerLifecycle:
    """Test scheduler.py pause, resume, repair, and error status operations."""

    def test_pause_changes_status(self):
        """Pausing a task sets status to 'paused'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            add_result = add_default_task(tmpdir)
            assert add_result.returncode == 0, add_result.stderr

            pause_result = run_scheduler(tmpdir, ["pause", "--id", "lifecycle-task"])
            assert pause_result.returncode == 0, pause_result.stderr
            data = json.loads(pause_result.stdout)
            assert data["status"] == "paused"

            # Verify via get that status persisted
            get_result = run_scheduler(tmpdir, ["get", "--id", "lifecycle-task"])
            assert get_result.returncode == 0
            get_data = json.loads(get_result.stdout)
            assert get_data["status"] == "paused"

    def test_resume_changes_status(self):
        """Resuming a paused task sets status back to 'active'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            add_result = add_default_task(tmpdir)
            assert add_result.returncode == 0, add_result.stderr

            # First pause
            pause_result = run_scheduler(tmpdir, ["pause", "--id", "lifecycle-task"])
            assert pause_result.returncode == 0, pause_result.stderr

            # Then resume
            resume_result = run_scheduler(tmpdir, ["resume", "--id", "lifecycle-task"])
            assert resume_result.returncode == 0, resume_result.stderr
            data = json.loads(resume_result.stdout)
            assert data["status"] == "active"

            # Verify via get that status persisted
            get_result = run_scheduler(tmpdir, ["get", "--id", "lifecycle-task"])
            assert get_result.returncode == 0
            get_data = json.loads(get_result.stdout)
            assert get_data["status"] == "active"

    def test_pause_already_paused_fails(self):
        """Pausing an already-paused task returns error with 'already paused' message."""
        with tempfile.TemporaryDirectory() as tmpdir:
            add_default_task(tmpdir)
            run_scheduler(tmpdir, ["pause", "--id", "lifecycle-task"])

            # Pause again should fail
            result = run_scheduler(tmpdir, ["pause", "--id", "lifecycle-task"])
            assert result.returncode != 0
            assert "already paused" in result.stderr.lower()

    def test_resume_already_active_fails(self):
        """Resuming an already-active task returns error with 'already active' message."""
        with tempfile.TemporaryDirectory() as tmpdir:
            add_default_task(tmpdir)

            # Resume without pausing first should fail
            result = run_scheduler(tmpdir, ["resume", "--id", "lifecycle-task"])
            assert result.returncode != 0
            assert "already active" in result.stderr.lower()

    def test_repair_regenerates_missing_wrapper(self):
        """Deleting a wrapper file and running repair regenerates it."""
        with tempfile.TemporaryDirectory() as tmpdir:
            add_result = add_default_task(tmpdir)
            assert add_result.returncode == 0, add_result.stderr

            # Delete the wrapper
            wrapper_path = Path(tmpdir) / "wrappers" / "lifecycle-task.sh"
            assert wrapper_path.exists(), "Wrapper should exist after add"
            wrapper_path.unlink()
            assert not wrapper_path.exists(), "Wrapper should be deleted"

            # Run repair
            repair_result = run_scheduler(tmpdir, ["repair"])
            assert repair_result.returncode == 0, repair_result.stderr
            assert "regenerated wrapper" in repair_result.stdout.lower()

            # Verify wrapper was regenerated
            assert wrapper_path.exists(), "Wrapper should be regenerated after repair"

    def test_update_last_run_error_sets_status(self):
        """Running update-last-run with non-zero exit code sets status to 'error'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            add_result = add_default_task(tmpdir)
            assert add_result.returncode == 0, add_result.stderr

            # Update last run with non-zero exit code
            update_result = run_scheduler(
                tmpdir,
                [
                    "update-last-run",
                    "--id",
                    "lifecycle-task",
                    "--exit-code",
                    "1",
                    "--duration",
                    "30",
                    "--result-file",
                    "/tmp/result.md",
                ],
            )
            assert update_result.returncode == 0, update_result.stderr
            data = json.loads(update_result.stdout)
            assert data["status"] == "error"
            assert data["last_run"]["exit_code"] == 1

            # Verify via get that error status persisted
            get_result = run_scheduler(tmpdir, ["get", "--id", "lifecycle-task"])
            assert get_result.returncode == 0
            get_data = json.loads(get_result.stdout)
            assert get_data["status"] == "error"
