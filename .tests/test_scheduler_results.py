"""Tests for scheduler.py results command with default and custom output directories.

Verifies that cmd_results reads from the correct location based on
whether the task has an output_directory set.
"""

import json
import os
import subprocess
import tempfile
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


def add_task(tmpdir: str, task_id: str = "test-task", output_directory: str | None = None):
    """Add a task with optional output_directory."""
    args = [
        "add",
        "--id", task_id,
        "--name", "Test Task",
        "--type", "prompt",
        "--target", "test prompt",
        "--cron", "0 9 * * *",
        "--working-directory", tmpdir,
    ]
    if output_directory:
        args.extend(["--output-directory", output_directory])
    return run_scheduler(tmpdir, args)


class TestResultsDefaultLocation:
    """Test cmd_results reads from default date-subdir location."""

    def test_results_reads_from_date_subdir(self):
        """Results are found in results/YYYY-MM-DD/{id}.md."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = add_task(tmpdir, task_id="default-result")
            assert result.returncode == 0, f"add failed: {result.stderr}"

            # Create a fake result file in a date subdirectory
            date_dir = Path(tmpdir) / "results" / "2025-01-15"
            date_dir.mkdir(parents=True, exist_ok=True)
            result_file = date_dir / "default-result.md"
            result_file.write_text("# Default Result\nHello from default location.\n")

            result = run_scheduler(tmpdir, ["results", "--id", "default-result"])
            assert result.returncode == 0
            assert "Default Result" in result.stdout
            assert "Hello from default location" in result.stdout

    def test_results_no_files_shows_message(self):
        """When no result files exist, prints message to stderr."""
        with tempfile.TemporaryDirectory() as tmpdir:
            add_task(tmpdir, task_id="no-results")
            result = run_scheduler(tmpdir, ["results", "--id", "no-results"])
            assert "No result files found" in result.stderr


class TestResultsTimestampedFiles:
    """Test cmd_results finds timestamped {id}-HHMMSS.md files."""

    def test_results_finds_timestamped_files(self):
        """cmd_results finds {id}-HHMMSS.md files and shows latest."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = add_task(tmpdir, task_id="ts-task")
            assert result.returncode == 0, f"add failed: {result.stderr}"

            date_dir = Path(tmpdir) / "results" / "2025-01-15"
            date_dir.mkdir(parents=True, exist_ok=True)
            (date_dir / "ts-task-090000.md").write_text("# Morning Run\n")
            (date_dir / "ts-task-140000.md").write_text("# Afternoon Run\n")

            result = run_scheduler(tmpdir, ["results", "--id", "ts-task"])
            assert result.returncode == 0
            # Latest alphabetically is 140000 (afternoon)
            assert "Afternoon Run" in result.stdout

    def test_results_all_shows_all_timestamped(self):
        """--all flag shows all timestamped results."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = add_task(tmpdir, task_id="ts-all")
            assert result.returncode == 0, f"add failed: {result.stderr}"

            date_dir = Path(tmpdir) / "results" / "2025-01-15"
            date_dir.mkdir(parents=True, exist_ok=True)
            (date_dir / "ts-all-090000.md").write_text("# Morning\n")
            (date_dir / "ts-all-140000.md").write_text("# Afternoon\n")

            result = run_scheduler(tmpdir, ["results", "--id", "ts-all", "--all"])
            assert result.returncode == 0
            assert "Morning" in result.stdout
            assert "Afternoon" in result.stdout

    def test_results_backward_compatible_with_old_filenames(self):
        """cmd_results still finds legacy {id}.md files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = add_task(tmpdir, task_id="legacy-task")
            assert result.returncode == 0, f"add failed: {result.stderr}"

            date_dir = Path(tmpdir) / "results" / "2025-01-15"
            date_dir.mkdir(parents=True, exist_ok=True)
            (date_dir / "legacy-task.md").write_text("# Legacy Result\n")

            result = run_scheduler(tmpdir, ["results", "--id", "legacy-task"])
            assert result.returncode == 0
            assert "Legacy Result" in result.stdout


class TestResultsCustomOutputDirectory:
    """Test cmd_results reads from custom output_directory when set."""

    def test_results_reads_from_custom_dir(self):
        """When output_directory is set, results come from there."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = os.path.join(tmpdir, "custom-output")
            os.makedirs(output_dir)

            result = add_task(tmpdir, task_id="custom-result", output_directory=output_dir)
            assert result.returncode == 0, f"add failed: {result.stderr}"

            # Create result in the custom directory (flat, no date subdirs)
            result_file = Path(output_dir) / "custom-result.md"
            result_file.write_text("# Custom Result\nHello from custom dir.\n")

            result = run_scheduler(tmpdir, ["results", "--id", "custom-result"])
            assert result.returncode == 0
            assert "Custom Result" in result.stdout
            assert "Hello from custom dir" in result.stdout

    def test_results_custom_dir_missing_file(self):
        """When output_directory is set but file is missing, shows error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = os.path.join(tmpdir, "empty-output")
            os.makedirs(output_dir)

            result = add_task(tmpdir, task_id="missing-custom", output_directory=output_dir)
            assert result.returncode == 0, f"add failed: {result.stderr}"

            # Don't create any result file
            result = run_scheduler(tmpdir, ["results", "--id", "missing-custom"])
            assert "No result files found" in result.stderr

    def test_results_custom_dir_ignores_default_location(self):
        """When output_directory is set, default date-subdir results are ignored."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = os.path.join(tmpdir, "custom-only")
            os.makedirs(output_dir)

            result = add_task(tmpdir, task_id="custom-only-task", output_directory=output_dir)
            assert result.returncode == 0, f"add failed: {result.stderr}"

            # Create a result in the default location (should be ignored)
            date_dir = Path(tmpdir) / "results" / "2025-01-15"
            date_dir.mkdir(parents=True, exist_ok=True)
            (date_dir / "custom-only-task.md").write_text("# Default\nShould not appear.\n")

            # No file in custom dir
            result = run_scheduler(tmpdir, ["results", "--id", "custom-only-task"])
            assert "No result files found" in result.stderr
            assert "Default" not in result.stdout
