"""Tests for scheduler.py wrapper script and plist generation.

Uses a temporary directory as SCHEDULER_DIR and SCHEDULER_PLIST_DIR,
and skips launchctl calls via SCHEDULER_SKIP_LAUNCHCTL=1.
"""

import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = str(
    Path(__file__).resolve().parents[1]
    / "scheduler"
    / "skills"
    / "manage"
    / "scripts"
    / "scheduler.py"
)

PLIST_PREFIX = "com.launchpad.scheduler"


class TestSchedulerGeneration(unittest.TestCase):
    """Test wrapper script and plist generation from scheduler.py add/remove."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.plist_dir = os.path.join(self.tmpdir, "plists")
        os.makedirs(self.plist_dir, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def run_scheduler(self, *args):
        env = os.environ.copy()
        env["SCHEDULER_DIR"] = self.tmpdir
        env["SCHEDULER_PLIST_DIR"] = self.plist_dir
        env["SCHEDULER_SKIP_LAUNCHCTL"] = "1"
        result = subprocess.run(
            ["uv", "run", SCRIPT] + list(args),
            capture_output=True,
            text=True,
            env=env,
        )
        return result.stdout, result.stderr, result.returncode

    def add_task(
        self,
        task_id="test-task",
        name="Test Task",
        task_type="skill",
        target="generate-report",
        cron="0 9 * * 1",
        max_turns=20,
        timeout_minutes=15,
    ):
        """Add a task with sensible defaults and return (stdout, stderr, rc)."""
        return self.run_scheduler(
            "add",
            "--id", task_id,
            "--name", name,
            "--type", task_type,
            "--target", target,
            "--cron", cron,
            "--working-directory", self.tmpdir,
            "--max-turns", str(max_turns),
            "--timeout-minutes", str(timeout_minutes),
        )

    # ------------------------------------------------------------------
    # Wrapper tests
    # ------------------------------------------------------------------

    def test_wrapper_generated_on_add(self):
        """Adding a task creates a wrapper script with correct content."""
        stdout, stderr, rc = self.add_task(
            task_id="gen-wrapper",
            task_type="prompt",
            target="Summarize my inbox",
            max_turns=10,
            timeout_minutes=5,
        )
        self.assertEqual(rc, 0, f"add failed: {stderr}")

        wrapper_path = Path(self.tmpdir) / "wrappers" / "gen-wrapper.sh"
        self.assertTrue(wrapper_path.exists(), "Wrapper script was not created")

        content = wrapper_path.read_text()
        self.assertIn('TASK_ID="gen-wrapper"', content)
        self.assertIn('TASK_TYPE="prompt"', content)
        self.assertIn("TASK_TARGET='Summarize my inbox'", content)
        self.assertIn("MAX_TURNS=10", content)
        self.assertIn("TIMEOUT_MINUTES=5", content)

    def test_wrapper_is_executable(self):
        """Wrapper script has execute permission (0o755)."""
        stdout, stderr, rc = self.add_task(task_id="exec-check")
        self.assertEqual(rc, 0, f"add failed: {stderr}")

        wrapper_path = Path(self.tmpdir) / "wrappers" / "exec-check.sh"
        self.assertTrue(wrapper_path.exists(), "Wrapper script was not created")

        mode = wrapper_path.stat().st_mode
        self.assertTrue(
            mode & stat.S_IXUSR,
            "Wrapper is not executable by owner",
        )
        self.assertTrue(
            mode & stat.S_IXGRP,
            "Wrapper is not executable by group",
        )
        self.assertTrue(
            mode & stat.S_IXOTH,
            "Wrapper is not executable by others",
        )

    def test_wrapper_escapes_single_quotes_in_target(self):
        """Prompt targets with single quotes are properly escaped."""
        stdout, stderr, rc = self.add_task(
            task_id="quote-test",
            task_type="prompt",
            target="What's today's agenda?",
        )
        self.assertEqual(rc, 0, f"add failed: {stderr}")

        wrapper_path = Path(self.tmpdir) / "wrappers" / "quote-test.sh"
        content = wrapper_path.read_text()
        # The escape sequence for a single quote inside single-quoted bash:
        #   'What'\''s today'\''s agenda?'
        self.assertIn("What'\\''s today'\\''s agenda?", content)
        # The raw unescaped version should NOT appear
        self.assertNotIn("What's today's agenda?", content)

    # ------------------------------------------------------------------
    # Plist tests
    # ------------------------------------------------------------------

    def test_plist_generated_on_add(self):
        """Adding a task creates a plist with correct label and schedule."""
        stdout, stderr, rc = self.add_task(
            task_id="plist-gen",
            cron="30 14 * * *",  # daily at 14:30
        )
        self.assertEqual(rc, 0, f"add failed: {stderr}")

        plist_path = Path(self.plist_dir) / f"{PLIST_PREFIX}.plist-gen.plist"
        self.assertTrue(plist_path.exists(), "Plist was not created")

        content = plist_path.read_text()
        # Correct label
        self.assertIn(f"<string>{PLIST_PREFIX}.plist-gen</string>", content)
        # Schedule should have Minute=30, Hour=14
        self.assertIn("<key>Minute</key>", content)
        self.assertIn("<integer>30</integer>", content)
        self.assertIn("<key>Hour</key>", content)
        self.assertIn("<integer>14</integer>", content)

    def test_plist_weekday_schedule(self):
        """Plist correctly handles weekday cron (Weekday key present)."""
        stdout, stderr, rc = self.add_task(
            task_id="weekday-test",
            cron="0 8 * * 1-5",  # weekdays at 08:00
        )
        self.assertEqual(rc, 0, f"add failed: {stderr}")

        plist_path = Path(self.plist_dir) / f"{PLIST_PREFIX}.weekday-test.plist"
        self.assertTrue(plist_path.exists(), "Plist was not created")

        content = plist_path.read_text()
        self.assertIn("<key>Weekday</key>", content)
        # Should fan out to weekdays 1 through 5
        for day in range(1, 6):
            self.assertIn(f"<integer>{day}</integer>", content)

    # ------------------------------------------------------------------
    # Wrapper path injection tests
    # ------------------------------------------------------------------

    def test_wrapper_contains_baked_scheduler_dir(self):
        """Wrapper script has SCHEDULER_DIR set to the resolved path, not $HOME."""
        stdout, stderr, rc = self.add_task(task_id="path-test")
        self.assertEqual(rc, 0, f"add failed: {stderr}")

        wrapper_path = Path(self.tmpdir) / "wrappers" / "path-test.sh"
        content = wrapper_path.read_text()
        # Should contain the baked-in SCHEDULER_DIR (the resolved tmpdir)
        resolved_tmpdir = str(Path(self.tmpdir).resolve())
        self.assertIn(f'SCHEDULER_DIR="{resolved_tmpdir}', content)
        # Should NOT contain the old hardcoded $HOME path
        self.assertNotIn('$HOME/.claude/scheduler', content)

    def test_wrapper_contains_empty_output_dir_by_default(self):
        """Wrapper has OUTPUT_DIR="" when no output directory is specified."""
        stdout, stderr, rc = self.add_task(task_id="no-outdir")
        self.assertEqual(rc, 0, f"add failed: {stderr}")

        wrapper_path = Path(self.tmpdir) / "wrappers" / "no-outdir.sh"
        content = wrapper_path.read_text()
        self.assertIn('OUTPUT_DIR=""', content)

    def test_wrapper_contains_custom_output_dir(self):
        """Wrapper has OUTPUT_DIR set when --output-directory is provided."""
        # Use a path inside tmpdir to avoid macOS symlink resolution issues
        custom_output = os.path.join(self.tmpdir, "my-output")
        stdout, stderr, rc = self.run_scheduler(
            "add",
            "--id", "custom-outdir",
            "--name", "Custom Output",
            "--type", "prompt",
            "--target", "test",
            "--cron", "0 9 * * *",
            "--working-directory", self.tmpdir,
            "--output-directory", custom_output,
        )
        self.assertEqual(rc, 0, f"add failed: {stderr}")

        wrapper_path = Path(self.tmpdir) / "wrappers" / "custom-outdir.sh"
        content = wrapper_path.read_text()
        resolved_output = str(Path(custom_output).resolve())
        self.assertIn(f'OUTPUT_DIR="{resolved_output}"', content)

    def test_task_json_includes_output_directory(self):
        """Task JSON includes output_directory field when provided."""
        custom_output = os.path.join(self.tmpdir, "test-output")
        stdout, stderr, rc = self.run_scheduler(
            "add",
            "--id", "json-outdir",
            "--name", "JSON Output Dir",
            "--type", "prompt",
            "--target", "test",
            "--cron", "0 9 * * *",
            "--working-directory", self.tmpdir,
            "--output-directory", custom_output,
        )
        self.assertEqual(rc, 0, f"add failed: {stderr}")

        import json
        task = json.loads(stdout)
        resolved_output = str(Path(custom_output).resolve())
        self.assertEqual(task["output_directory"], resolved_output)

    def test_task_json_output_directory_none_when_not_provided(self):
        """Task JSON has output_directory=None when not provided."""
        stdout, stderr, rc = self.add_task(task_id="no-outdir-json")
        self.assertEqual(rc, 0, f"add failed: {stderr}")

        import json
        task = json.loads(stdout)
        self.assertIsNone(task["output_directory"])

    # ------------------------------------------------------------------
    # Fix 1: update-last-run in wrapper
    # ------------------------------------------------------------------

    def test_wrapper_contains_update_last_run_call(self):
        """Generated wrapper contains update-last-run call with required args."""
        stdout, stderr, rc = self.add_task(task_id="ulr-test")
        self.assertEqual(rc, 0, f"add failed: {stderr}")

        wrapper_path = Path(self.tmpdir) / "wrappers" / "ulr-test.sh"
        content = wrapper_path.read_text()
        self.assertIn("update-last-run", content)
        self.assertIn("--id", content)
        self.assertIn("--exit-code", content)
        self.assertIn("--duration", content)
        self.assertIn("--result-file", content)
        self.assertIn("|| true", content)

    def test_wrapper_update_last_run_before_complete(self):
        """For run-once tasks, update-last-run appears before complete --id."""
        stdout, stderr, rc = self.run_scheduler(
            "add",
            "--id", "once-test",
            "--name", "Once Test",
            "--type", "prompt",
            "--target", "test",
            "--cron", "0 9 * * *",
            "--working-directory", self.tmpdir,
            "--run-once",
        )
        self.assertEqual(rc, 0, f"add failed: {stderr}")

        wrapper_path = Path(self.tmpdir) / "wrappers" / "once-test.sh"
        content = wrapper_path.read_text()
        ulr_pos = content.index("update-last-run")
        complete_pos = content.index('complete --id')
        self.assertLess(ulr_pos, complete_pos,
                        "update-last-run should appear before complete --id")

    # ------------------------------------------------------------------
    # Fix 2: timestamped result files in wrapper
    # ------------------------------------------------------------------

    def test_wrapper_uses_timestamped_result_file_default_dir(self):
        """Default dir wrappers contain TIMESTAMP and use timestamped filenames."""
        stdout, stderr, rc = self.add_task(task_id="ts-default")
        self.assertEqual(rc, 0, f"add failed: {stderr}")

        wrapper_path = Path(self.tmpdir) / "wrappers" / "ts-default.sh"
        content = wrapper_path.read_text()
        self.assertIn("TIMESTAMP=", content)
        self.assertIn("$TASK_ID-$TIMESTAMP.md", content)

    def test_wrapper_uses_stable_filename_custom_dir(self):
        """Custom dir wrappers still use stable {id}.md filenames."""
        custom_output = os.path.join(self.tmpdir, "custom-out")
        stdout, stderr, rc = self.run_scheduler(
            "add",
            "--id", "ts-custom",
            "--name", "TS Custom",
            "--type", "prompt",
            "--target", "test",
            "--cron", "0 9 * * *",
            "--working-directory", self.tmpdir,
            "--output-directory", custom_output,
        )
        self.assertEqual(rc, 0, f"add failed: {stderr}")

        wrapper_path = Path(self.tmpdir) / "wrappers" / "ts-custom.sh"
        content = wrapper_path.read_text()
        # Custom dir branch should use $TASK_ID.md (no timestamp)
        self.assertIn('RESULT_FILE="$RESULT_DIR/$TASK_ID.md"', content)

    # ------------------------------------------------------------------
    # Remove cleanup
    # ------------------------------------------------------------------

    def test_remove_deletes_wrapper_and_plist(self):
        """Remove cleans up both wrapper and plist files."""
        stdout, stderr, rc = self.add_task(task_id="cleanup-test")
        self.assertEqual(rc, 0, f"add failed: {stderr}")

        wrapper_path = Path(self.tmpdir) / "wrappers" / "cleanup-test.sh"
        plist_path = Path(self.plist_dir) / f"{PLIST_PREFIX}.cleanup-test.plist"

        # Verify they exist before removal
        self.assertTrue(wrapper_path.exists(), "Wrapper should exist before remove")
        self.assertTrue(plist_path.exists(), "Plist should exist before remove")

        # Remove
        stdout, stderr, rc = self.run_scheduler("remove", "--id", "cleanup-test")
        self.assertEqual(rc, 0, f"remove failed: {stderr}")

        # Verify both are gone
        self.assertFalse(wrapper_path.exists(), "Wrapper was not deleted on remove")
        self.assertFalse(plist_path.exists(), "Plist was not deleted on remove")


if __name__ == "__main__":
    unittest.main()
