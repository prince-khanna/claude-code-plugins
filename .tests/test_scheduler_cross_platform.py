"""Cross-platform integration tests for the scheduler.

Tests platform detection, registry v2 migration, and full lifecycle
with mocked platform detection. Can run on any OS.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPTS_DIR = str(
    Path(__file__).resolve().parents[1]
    / "scheduler"
    / "skills"
    / "manage"
    / "scripts"
)
sys.path.insert(0, SCRIPTS_DIR)

SCRIPT = str(Path(SCRIPTS_DIR) / "scheduler.py")


# ---------------------------------------------------------------------------
# Platform detection tests
# ---------------------------------------------------------------------------


class TestPlatformDetect:
    """Test platform detection and backend factory."""

    def test_detect_platform_returns_string(self):
        from platform_detect import detect_platform
        result = detect_platform()
        assert result in ("macos", "linux", "windows")

    def test_get_backend_macos(self):
        from platform_detect import get_backend
        backend = get_backend("macos")
        from backends.macos import MacOSBackend
        assert isinstance(backend, MacOSBackend)

    def test_get_backend_linux(self):
        from platform_detect import get_backend
        backend = get_backend("linux")
        from backends.linux import LinuxBackend
        assert isinstance(backend, LinuxBackend)

    def test_get_backend_windows(self):
        from platform_detect import get_backend
        backend = get_backend("windows")
        from backends.windows import WindowsBackend
        assert isinstance(backend, WindowsBackend)

    def test_get_backend_invalid(self):
        from platform_detect import get_backend
        with pytest.raises(RuntimeError, match="No backend"):
            get_backend("beos")


# ---------------------------------------------------------------------------
# Registry v2 migration tests
# ---------------------------------------------------------------------------


def _run_scheduler(tmpdir, args):
    """Run scheduler.py in a temp dir with skip flags."""
    plist_dir = os.path.join(tmpdir, "plists")
    os.makedirs(plist_dir, exist_ok=True)
    env = os.environ.copy()
    env["SCHEDULER_DIR"] = tmpdir
    env["SCHEDULER_PLIST_DIR"] = plist_dir
    env["SCHEDULER_SKIP_LAUNCHCTL"] = "1"
    env["SCHEDULER_SKIP_PLATFORM"] = "1"
    return subprocess.run(
        ["uv", "run", SCRIPT] + args,
        capture_output=True,
        text=True,
        env=env,
    )


class TestRegistryMigration:
    """Test automatic v1 -> v2 registry migration."""

    def test_new_registry_is_v2(self):
        """A fresh registry starts at version 2."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = _run_scheduler(tmpdir, ["list"])
            assert result.returncode == 0

            registry_file = Path(tmpdir) / "registry.json"
            # Fresh registry isn't saved until a task is added
            # Let's add a task to trigger save
            result = _run_scheduler(tmpdir, [
                "add", "--id", "v2-test", "--name", "V2 Test",
                "--type", "prompt", "--target", "test",
                "--cron", "0 9 * * *", "--working-directory", tmpdir,
            ])
            assert result.returncode == 0

            with open(registry_file) as f:
                registry = json.load(f)
            assert registry["version"] == 2

    def test_v1_registry_migrated_on_load(self):
        """A v1 registry is automatically migrated to v2 with platform field."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Manually create a v1 registry
            registry_file = Path(tmpdir) / "registry.json"
            v1_registry = {
                "version": 1,
                "tasks": {
                    "old-task": {
                        "id": "old-task",
                        "name": "Old Task",
                        "type": "prompt",
                        "target": "test",
                        "working_directory": tmpdir,
                        "schedule": {"cron": "0 9 * * *", "human": "Every day at 9:00 AM"},
                        "safety": {"max_turns": 20, "timeout_minutes": 15},
                        "run_once": False,
                        "output_directory": None,
                        "status": "active",
                        "created_at": "2025-01-01T00:00:00+00:00",
                        "last_run": None,
                    }
                },
            }
            with open(registry_file, "w") as f:
                json.dump(v1_registry, f)

            # Ensure scheduler directories exist
            for d in ["wrappers", "logs", "results"]:
                (Path(tmpdir) / d).mkdir(exist_ok=True)

            # Running any command triggers migration
            result = _run_scheduler(tmpdir, ["list"])
            assert result.returncode == 0

            # Verify migration
            with open(registry_file) as f:
                migrated = json.load(f)

            assert migrated["version"] == 2
            assert "platform" in migrated["tasks"]["old-task"]
            # Platform should be the current OS
            from platform_detect import detect_platform
            assert migrated["tasks"]["old-task"]["platform"] == detect_platform()

    def test_new_tasks_have_platform_field(self):
        """Newly added tasks include a platform field."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = _run_scheduler(tmpdir, [
                "add", "--id", "platform-test", "--name", "Platform Test",
                "--type", "prompt", "--target", "test",
                "--cron", "0 9 * * *", "--working-directory", tmpdir,
            ])
            assert result.returncode == 0

            task = json.loads(result.stdout)
            assert "platform" in task
            from platform_detect import detect_platform
            assert task["platform"] == detect_platform()


# ---------------------------------------------------------------------------
# Backend interface compliance tests
# ---------------------------------------------------------------------------


class TestBackendInterface:
    """Verify all backends implement the required interface."""

    @pytest.mark.parametrize("platform_name", ["macos", "linux", "windows"])
    def test_backend_has_all_methods(self, platform_name):
        """Each backend implements all abstract methods from PlatformBackend."""
        from platform_detect import get_backend
        from backends.base import PlatformBackend
        import abc
        import inspect

        # Get all abstract methods
        abstract_methods = set()
        for name, method in inspect.getmembers(PlatformBackend):
            if getattr(method, "__isabstractmethod__", False):
                abstract_methods.add(name)

        # Instantiate backend (with skip flags to avoid side effects)
        with patch.dict(os.environ, {
            "SCHEDULER_SKIP_PLATFORM": "1",
            "SCHEDULER_SKIP_LAUNCHCTL": "1",
            "SCHEDULER_SKIP_SYSTEMD": "1",
            "SCHEDULER_SKIP_SCHTASKS": "1",
        }):
            backend = get_backend(platform_name)

        # Verify all abstract methods are implemented
        for method_name in abstract_methods:
            assert hasattr(backend, method_name), (
                f"{platform_name} backend missing method: {method_name}"
            )
            method = getattr(backend, method_name)
            assert callable(method), (
                f"{platform_name} backend {method_name} is not callable"
            )

    @pytest.mark.parametrize("platform_name,expected_ext", [
        ("macos", ".sh"),
        ("linux", ".sh"),
        ("windows", ".ps1"),
    ])
    def test_wrapper_extensions(self, platform_name, expected_ext):
        """Each platform returns the correct wrapper extension."""
        from platform_detect import get_backend
        with patch.dict(os.environ, {
            "SCHEDULER_SKIP_PLATFORM": "1",
            "SCHEDULER_SKIP_LAUNCHCTL": "1",
            "SCHEDULER_SKIP_SYSTEMD": "1",
            "SCHEDULER_SKIP_SCHTASKS": "1",
        }):
            backend = get_backend(platform_name)
        assert backend.wrapper_extension() == expected_ext
