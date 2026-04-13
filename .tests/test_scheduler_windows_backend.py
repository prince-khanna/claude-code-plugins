"""Tests for the Windows Task Scheduler backend.

Tests cron-to-trigger conversion and Task Scheduler XML generation.
Runs on any platform — uses mocked platform detection and SCHEDULER_SKIP_PLATFORM=1.
"""

import os
import sys
import tempfile
import xml.etree.ElementTree as ET
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

from backends.windows import (
    WindowsBackend,
    cron_to_schtask_triggers,
    generate_task_xml,
)


# ---------------------------------------------------------------------------
# cron_to_schtask_triggers conversion tests
# ---------------------------------------------------------------------------


class TestCronToSchtaskTriggers:
    """Test cron expression to Task Scheduler trigger conversion."""

    def test_daily_at_9am(self):
        triggers = cron_to_schtask_triggers("0 9 * * *")
        assert len(triggers) == 1
        assert triggers[0]["type"] == "daily"
        assert triggers[0]["start_time"] == "09:00:00"

    def test_daily_at_230pm(self):
        triggers = cron_to_schtask_triggers("30 14 * * *")
        assert len(triggers) == 1
        assert triggers[0]["type"] == "daily"
        assert triggers[0]["start_time"] == "14:30:00"

    def test_monday_at_8am(self):
        triggers = cron_to_schtask_triggers("0 8 * * 1")
        assert len(triggers) == 1
        assert triggers[0]["type"] == "weekly"
        assert triggers[0]["start_time"] == "08:00:00"
        assert triggers[0]["days_of_week"] == ["Monday"]

    def test_weekdays_at_730am(self):
        triggers = cron_to_schtask_triggers("30 7 * * 1-5")
        assert len(triggers) == 1
        assert triggers[0]["type"] == "weekly"
        assert triggers[0]["start_time"] == "07:30:00"
        assert triggers[0]["days_of_week"] == [
            "Monday", "Tuesday", "Wednesday", "Thursday", "Friday"
        ]

    def test_every_5_minutes(self):
        triggers = cron_to_schtask_triggers("*/5 * * * *")
        assert len(triggers) == 1
        assert triggers[0]["type"] == "time"
        assert triggers[0]["repetition_interval"] == "PT5M"

    def test_first_of_month_at_9am(self):
        triggers = cron_to_schtask_triggers("0 9 1 * *")
        assert len(triggers) == 1
        assert triggers[0]["type"] == "monthly"
        assert triggers[0]["start_time"] == "09:00:00"
        assert triggers[0]["days_of_month"] == [1]

    def test_specific_month_and_day(self):
        triggers = cron_to_schtask_triggers("0 6 15 3 *")
        assert len(triggers) == 1
        assert triggers[0]["type"] == "monthly"
        assert triggers[0]["days_of_month"] == [15]
        assert triggers[0]["months"] == ["March"]

    def test_every_2_hours(self):
        triggers = cron_to_schtask_triggers("0 */2 * * *")
        assert len(triggers) == 1
        assert triggers[0]["type"] == "time"
        assert triggers[0]["repetition_interval"] == "PT2H"


# ---------------------------------------------------------------------------
# XML generation tests
# ---------------------------------------------------------------------------


class TestGenerateTaskXml:
    """Test Task Scheduler XML generation."""

    def _parse_xml(self, xml_str: str) -> ET.Element:
        """Parse generated XML, handling the namespace."""
        return ET.fromstring(xml_str)

    def test_xml_is_valid(self):
        """Generated XML is well-formed."""
        triggers = cron_to_schtask_triggers("0 9 * * *")
        xml_str = generate_task_xml(
            "test-task",
            Path("C:/scripts/test.ps1"),
            triggers,
        )
        # Should not raise
        root = self._parse_xml(xml_str)
        assert root is not None

    def test_xml_contains_description(self):
        """XML contains the task description."""
        triggers = cron_to_schtask_triggers("0 9 * * *")
        xml_str = generate_task_xml("my-task", Path("C:/test.ps1"), triggers)
        assert "Prince Plugins Scheduler: my-task" in xml_str

    def test_xml_contains_powershell_command(self):
        """XML action uses powershell.exe with -ExecutionPolicy Bypass."""
        triggers = cron_to_schtask_triggers("0 9 * * *")
        xml_str = generate_task_xml("ps-test", Path("C:/test.ps1"), triggers)
        assert "powershell.exe" in xml_str
        assert "-ExecutionPolicy Bypass" in xml_str

    def test_xml_daily_trigger(self):
        """Daily trigger has DaysInterval element."""
        triggers = cron_to_schtask_triggers("0 9 * * *")
        xml_str = generate_task_xml("daily-test", Path("C:/test.ps1"), triggers)
        assert "DaysInterval" in xml_str

    def test_xml_weekly_trigger(self):
        """Weekly trigger has DaysOfWeek element."""
        triggers = cron_to_schtask_triggers("0 8 * * 1")
        xml_str = generate_task_xml("weekly-test", Path("C:/test.ps1"), triggers)
        assert "DaysOfWeek" in xml_str
        assert "Monday" in xml_str

    def test_xml_monthly_trigger(self):
        """Monthly trigger has DaysOfMonth element."""
        triggers = cron_to_schtask_triggers("0 9 1 * *")
        xml_str = generate_task_xml("monthly-test", Path("C:/test.ps1"), triggers)
        assert "DaysOfMonth" in xml_str

    def test_xml_repetition_trigger(self):
        """Repetition trigger has Interval element."""
        triggers = cron_to_schtask_triggers("*/5 * * * *")
        xml_str = generate_task_xml("rep-test", Path("C:/test.ps1"), triggers)
        assert "PT5M" in xml_str

    def test_xml_execution_time_limit(self):
        """ExecutionTimeLimit reflects timeout_minutes."""
        triggers = cron_to_schtask_triggers("0 9 * * *")
        xml_str = generate_task_xml(
            "timeout-test", Path("C:/test.ps1"), triggers,
            timeout_minutes=30,
        )
        assert "PT30M" in xml_str

    def test_xml_settings(self):
        """XML has expected settings (IgnoreNew, StartWhenAvailable)."""
        triggers = cron_to_schtask_triggers("0 9 * * *")
        xml_str = generate_task_xml("settings-test", Path("C:/test.ps1"), triggers)
        assert "IgnoreNew" in xml_str
        assert "StartWhenAvailable" in xml_str


# ---------------------------------------------------------------------------
# Windows Backend unit tests
# ---------------------------------------------------------------------------


class TestWindowsBackend:
    """Test WindowsBackend methods using mocked platform."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.tmpdir)

    def _make_backend(self):
        with patch.dict(os.environ, {
            "SCHEDULER_SKIP_PLATFORM": "1",
        }):
            backend = WindowsBackend()
            backend.xml_dir = Path(self.tmpdir) / "schtasks_xml"
            backend.xml_dir.mkdir(parents=True, exist_ok=True)
            return backend

    def test_wrapper_extension(self):
        backend = self._make_backend()
        assert backend.wrapper_extension() == ".ps1"

    def test_install_creates_xml(self):
        """install_schedule creates an XML file."""
        backend = self._make_backend()
        task = {
            "id": "xml-test",
            "schedule": {"cron": "0 9 * * *"},
            "safety": {"timeout_minutes": 15},
        }
        wrapper_path = Path(self.tmpdir) / "xml-test.ps1"
        wrapper_path.write_text("echo hello")

        backend.install_schedule(
            "xml-test", task, wrapper_path,
            Path(self.tmpdir), Path(self.tmpdir) / "logs",
        )

        xml_path = Path(self.tmpdir) / "schtasks_xml" / "xml-test.xml"
        assert xml_path.exists(), "XML file should be created"

    def test_uninstall_removes_xml(self):
        """uninstall_schedule removes the XML file."""
        backend = self._make_backend()
        task = {
            "id": "rm-xml-test",
            "schedule": {"cron": "0 9 * * *"},
            "safety": {"timeout_minutes": 15},
        }
        wrapper_path = Path(self.tmpdir) / "rm-xml-test.ps1"
        wrapper_path.write_text("echo hello")

        backend.install_schedule(
            "rm-xml-test", task, wrapper_path,
            Path(self.tmpdir), Path(self.tmpdir) / "logs",
        )

        xml_path = backend.xml_dir / "rm-xml-test.xml"
        assert xml_path.exists()

        backend.uninstall_schedule("rm-xml-test")
        assert not xml_path.exists()

    def test_schedule_artifact_exists(self):
        """schedule_artifact_exists checks XML file."""
        backend = self._make_backend()
        assert not backend.schedule_artifact_exists("nonexistent")

        task = {
            "id": "exist-test",
            "schedule": {"cron": "0 9 * * *"},
            "safety": {"timeout_minutes": 15},
        }
        wrapper_path = Path(self.tmpdir) / "exist-test.ps1"
        wrapper_path.write_text("echo hello")

        backend.install_schedule(
            "exist-test", task, wrapper_path,
            Path(self.tmpdir), Path(self.tmpdir) / "logs",
        )
        assert backend.schedule_artifact_exists("exist-test")

    def test_skip_scheduling(self):
        backend = self._make_backend()
        assert backend.skip_scheduling() is True
