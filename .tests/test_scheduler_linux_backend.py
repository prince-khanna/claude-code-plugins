"""Tests for the Linux systemd backend.

Tests cron-to-OnCalendar conversion and systemd unit file generation.
Runs on any platform — uses mocked platform detection and SCHEDULER_SKIP_PLATFORM=1.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# Add scripts dir to path for direct backend imports
SCRIPTS_DIR = str(
    Path(__file__).resolve().parents[1]
    / "scheduler"
    / "skills"
    / "manage"
    / "scripts"
)
sys.path.insert(0, SCRIPTS_DIR)

from backends.linux import LinuxBackend, cron_to_oncalendar

SCRIPT = str(Path(SCRIPTS_DIR) / "scheduler.py")


# ---------------------------------------------------------------------------
# cron_to_oncalendar conversion tests
# ---------------------------------------------------------------------------


class TestCronToOnCalendar:
    """Test cron expression to systemd OnCalendar conversion."""

    def test_daily_at_9am(self):
        assert cron_to_oncalendar("0 9 * * *") == "*-*-* 09:00:00"

    def test_daily_at_230pm(self):
        assert cron_to_oncalendar("30 14 * * *") == "*-*-* 14:30:00"

    def test_monday_at_8am(self):
        result = cron_to_oncalendar("0 8 * * 1")
        assert result == "Mon *-*-* 08:00:00"

    def test_weekdays_at_730am(self):
        result = cron_to_oncalendar("30 7 * * 1-5")
        assert result == "Mon..Fri *-*-* 07:30:00"

    def test_every_5_minutes(self):
        result = cron_to_oncalendar("*/5 * * * *")
        assert result == "*-*-* *:00/5:00"

    def test_first_of_month_at_9am(self):
        result = cron_to_oncalendar("0 9 1 * *")
        assert result == "*-*-01 09:00:00"

    def test_every_minute(self):
        result = cron_to_oncalendar("* * * * *")
        assert result == "*-*-* *:*:00"

    def test_specific_month_and_day(self):
        result = cron_to_oncalendar("0 6 15 3 *")
        assert result == "*-03-15 06:00:00"

    def test_sunday(self):
        result = cron_to_oncalendar("0 0 * * 0")
        assert result == "Sun *-*-* 00:00:00"

    def test_weekend(self):
        result = cron_to_oncalendar("0 10 * * 0,6")
        assert result == "Sun,Sat *-*-* 10:00:00"

    def test_every_2_hours(self):
        result = cron_to_oncalendar("0 */2 * * *")
        assert result == "*-*-* 00/2:00:00"


# ---------------------------------------------------------------------------
# systemd unit file generation tests
# ---------------------------------------------------------------------------


class TestLinuxBackendUnitGeneration:
    """Test systemd service and timer unit file generation."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.systemd_dir = os.path.join(self.tmpdir, "systemd")
        os.makedirs(self.systemd_dir, exist_ok=True)

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.tmpdir)

    def _make_backend(self):
        """Create a LinuxBackend with test directories and skip flag."""
        with patch.dict(os.environ, {
            "SCHEDULER_SYSTEMD_DIR": self.systemd_dir,
            "SCHEDULER_SKIP_PLATFORM": "1",
        }):
            return LinuxBackend()

    def test_install_creates_service_and_timer(self):
        """install_schedule creates both .service and .timer files."""
        backend = self._make_backend()
        task = {
            "id": "test-task",
            "schedule": {"cron": "0 9 * * *"},
        }
        wrapper_path = Path(self.tmpdir) / "wrapper.sh"
        wrapper_path.write_text("#!/bin/bash\necho hello")

        backend.install_schedule(
            "test-task", task, wrapper_path,
            Path(self.tmpdir), Path(self.tmpdir) / "logs",
        )

        service_path = Path(self.systemd_dir) / "launchpad-scheduler-test-task.service"
        timer_path = Path(self.systemd_dir) / "launchpad-scheduler-test-task.timer"

        assert service_path.exists(), "Service file should be created"
        assert timer_path.exists(), "Timer file should be created"

    def test_service_contains_wrapper_path(self):
        """Service unit ExecStart points to the wrapper script."""
        backend = self._make_backend()
        task = {"id": "exec-test", "schedule": {"cron": "0 8 * * 1"}}
        wrapper_path = Path(self.tmpdir) / "exec-test.sh"
        wrapper_path.write_text("#!/bin/bash\necho test")

        backend.install_schedule(
            "exec-test", task, wrapper_path,
            Path(self.tmpdir), Path(self.tmpdir) / "logs",
        )

        service_content = (
            Path(self.systemd_dir) / "launchpad-scheduler-exec-test.service"
        ).read_text()
        assert f"ExecStart=/bin/bash {wrapper_path}" in service_content

    def test_timer_contains_oncalendar(self):
        """Timer unit contains correct OnCalendar value."""
        backend = self._make_backend()
        task = {"id": "cal-test", "schedule": {"cron": "30 14 * * *"}}
        wrapper_path = Path(self.tmpdir) / "cal-test.sh"
        wrapper_path.write_text("#!/bin/bash")

        backend.install_schedule(
            "cal-test", task, wrapper_path,
            Path(self.tmpdir), Path(self.tmpdir) / "logs",
        )

        timer_content = (
            Path(self.systemd_dir) / "launchpad-scheduler-cal-test.timer"
        ).read_text()
        assert "OnCalendar=*-*-* 14:30:00" in timer_content
        assert "Persistent=true" in timer_content

    def test_timer_weekday_schedule(self):
        """Timer correctly handles weekday cron."""
        backend = self._make_backend()
        task = {"id": "weekday-test", "schedule": {"cron": "0 8 * * 1-5"}}
        wrapper_path = Path(self.tmpdir) / "weekday-test.sh"
        wrapper_path.write_text("#!/bin/bash")

        backend.install_schedule(
            "weekday-test", task, wrapper_path,
            Path(self.tmpdir), Path(self.tmpdir) / "logs",
        )

        timer_content = (
            Path(self.systemd_dir) / "launchpad-scheduler-weekday-test.timer"
        ).read_text()
        assert "OnCalendar=Mon..Fri *-*-* 08:00:00" in timer_content

    def test_uninstall_removes_files(self):
        """uninstall_schedule removes both unit files."""
        backend = self._make_backend()
        task = {"id": "rm-test", "schedule": {"cron": "0 9 * * *"}}
        wrapper_path = Path(self.tmpdir) / "rm-test.sh"
        wrapper_path.write_text("#!/bin/bash")

        backend.install_schedule(
            "rm-test", task, wrapper_path,
            Path(self.tmpdir), Path(self.tmpdir) / "logs",
        )

        service_path = Path(self.systemd_dir) / "launchpad-scheduler-rm-test.service"
        timer_path = Path(self.systemd_dir) / "launchpad-scheduler-rm-test.timer"
        assert service_path.exists()
        assert timer_path.exists()

        backend.uninstall_schedule("rm-test")
        assert not service_path.exists()
        assert not timer_path.exists()

    def test_schedule_artifact_exists(self):
        """schedule_artifact_exists returns True only when both files present."""
        backend = self._make_backend()
        assert not backend.schedule_artifact_exists("nonexistent")

        task = {"id": "exist-test", "schedule": {"cron": "0 9 * * *"}}
        wrapper_path = Path(self.tmpdir) / "exist-test.sh"
        wrapper_path.write_text("#!/bin/bash")
        backend.install_schedule(
            "exist-test", task, wrapper_path,
            Path(self.tmpdir), Path(self.tmpdir) / "logs",
        )
        assert backend.schedule_artifact_exists("exist-test")

    def test_wrapper_extension(self):
        backend = self._make_backend()
        assert backend.wrapper_extension() == ".sh"


# ---------------------------------------------------------------------------
# Full lifecycle test via scheduler.py with mocked platform
# ---------------------------------------------------------------------------


class TestLinuxFullLifecycle:
    """Test full scheduler lifecycle using Linux backend via mocked platform."""

    def _run_scheduler(self, tmpdir, args):
        """Run scheduler.py with Linux backend via mocked platform."""
        systemd_dir = os.path.join(tmpdir, "systemd")
        os.makedirs(systemd_dir, exist_ok=True)
        env = os.environ.copy()
        env["SCHEDULER_DIR"] = tmpdir
        env["SCHEDULER_SKIP_PLATFORM"] = "1"
        env["SCHEDULER_SYSTEMD_DIR"] = systemd_dir
        # Force Linux backend by setting SCHEDULER_PLATFORM
        # We patch platform.system() via a wrapper
        return subprocess.run(
            ["uv", "run", SCRIPT] + args,
            capture_output=True,
            text=True,
            env=env,
        )

    def test_add_list_remove_lifecycle(self):
        """Full lifecycle on the current platform (macOS in CI) with skip flags."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # ADD
            result = self._run_scheduler(tmpdir, [
                "add",
                "--id", "linux-test",
                "--name", "Linux Test",
                "--type", "prompt",
                "--target", "test prompt",
                "--cron", "0 9 * * *",
                "--working-directory", tmpdir,
            ])
            assert result.returncode == 0, f"add failed: {result.stderr}"
            task = json.loads(result.stdout)
            assert task["status"] == "active"

            # LIST
            result = self._run_scheduler(tmpdir, ["list"])
            assert result.returncode == 0
            tasks = json.loads(result.stdout)
            assert len(tasks) == 1

            # REMOVE
            result = self._run_scheduler(tmpdir, ["remove", "--id", "linux-test"])
            assert result.returncode == 0

            result = self._run_scheduler(tmpdir, ["list"])
            tasks = json.loads(result.stdout)
            assert len(tasks) == 0
