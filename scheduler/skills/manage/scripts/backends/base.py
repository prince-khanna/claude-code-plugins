"""Abstract base class for platform-specific scheduler backends."""

from __future__ import annotations

import abc
from pathlib import Path


class PlatformBackend(abc.ABC):
    """Interface for platform-specific scheduling operations.

    Each platform (macOS, Linux, Windows) implements this interface to
    handle schedule installation, wrapper generation, and scheduler
    interaction using native OS facilities.
    """

    # --- Required methods ---

    @abc.abstractmethod
    def install_schedule(
        self,
        task_id: str,
        task: dict,
        wrapper_path: Path,
        scheduler_dir: Path,
        logs_dir: Path,
    ) -> None:
        """Create schedule artifacts and register with the platform scheduler.

        For macOS: generates a plist and loads it via launchctl.
        For Linux: generates systemd .service + .timer units and enables them.
        For Windows: generates XML and imports via schtasks.
        """

    @abc.abstractmethod
    def uninstall_schedule(self, task_id: str) -> None:
        """Remove a scheduled task entirely (unload + delete artifacts)."""

    @abc.abstractmethod
    def load_schedule(self, task_id: str) -> None:
        """Resume/load a previously installed schedule.

        Raises RuntimeError if the load fails and the job is not active
        after the attempt.
        """

    @abc.abstractmethod
    def unload_schedule(self, task_id: str) -> None:
        """Pause/unload a schedule without removing artifacts.

        Raises RuntimeError if the unload fails and the job is still active
        after the attempt.
        """

    @abc.abstractmethod
    def schedule_artifact_exists(self, task_id: str) -> bool:
        """Check whether schedule artifacts exist (for repair detection)."""

    @abc.abstractmethod
    def generate_wrapper(
        self,
        task: dict,
        scheduler_dir: Path,
        scheduler_py_path: Path,
        wrappers_dir: Path,
    ) -> Path:
        """Generate a wrapper script for the task. Returns the wrapper path."""

    @abc.abstractmethod
    def wrapper_extension(self) -> str:
        """Return the file extension for wrapper scripts (e.g. '.sh', '.ps1')."""

    @abc.abstractmethod
    def run_wrapper(self, wrapper_path: Path) -> int:
        """Execute a wrapper script directly. Returns the process exit code."""

    @abc.abstractmethod
    def skip_scheduling(self) -> bool:
        """Whether to skip platform scheduler interactions (for testing)."""

    @abc.abstractmethod
    def default_schedule_dir(self) -> Path:
        """Return the default directory for schedule artifacts."""

    # --- Shared wrapper generation ---

    def _escape_single_quoted(self, value: str) -> str:
        """Escape a value for embedding in single quotes in wrapper templates.

        Override in subclasses for platform-specific quoting rules.
        Default: bash-style single-quote escaping.
        """
        return value.replace("'", "'\\''")

    def _render_wrapper(
        self,
        task: dict,
        scheduler_dir: Path,
        scheduler_py_path: Path,
        wrappers_dir: Path,
        make_executable: bool = True,
    ) -> Path:
        """Render a wrapper script from the platform template.

        Handles all field substitution and permission flag injection.
        Subclasses typically call this from generate_wrapper().
        """
        template = self.template_path.read_text()
        escaped_target = self._escape_single_quoted(task["target"])

        wrapper = template.replace("{id}", task["id"])
        wrapper = wrapper.replace("{type}", task["type"])
        wrapper = wrapper.replace("{target}", escaped_target)
        wrapper = wrapper.replace("{max_turns}", str(task["safety"]["max_turns"]))
        wrapper = wrapper.replace(
            "{timeout_minutes}", str(task["safety"]["timeout_minutes"])
        )
        wrapper = wrapper.replace("{working_directory}", task["working_directory"])
        wrapper = wrapper.replace(
            "{run_once}", "true" if task.get("run_once") else "false"
        )
        wrapper = wrapper.replace("{scheduler_py}", str(scheduler_py_path))
        wrapper = wrapper.replace("{scheduler_dir}", str(scheduler_dir.resolve()))
        wrapper = wrapper.replace(
            "{output_directory}", task.get("output_directory") or ""
        )

        # Permission flags
        permissions = task.get("permissions") or {}
        allowed_tools = ",".join(permissions.get("allowed_tools") or [])
        permission_mode = permissions.get("permission_mode") or ""
        skip_perms = "true" if permission_mode == "bypassPermissions" else "false"
        if skip_perms == "true":
            permission_mode = ""  # The flag is standalone

        wrapper = wrapper.replace("{allowed_tools}", self._escape_single_quoted(allowed_tools))
        wrapper = wrapper.replace("{permission_mode}", permission_mode)
        wrapper = wrapper.replace("{skip_permissions}", skip_perms)

        wrappers_dir.mkdir(parents=True, exist_ok=True)
        wrapper_path = wrappers_dir / f"{task['id']}{self.wrapper_extension()}"
        wrapper_path.write_text(wrapper)
        if make_executable:
            wrapper_path.chmod(0o755)
        return wrapper_path

    # --- Optional methods (default no-ops) ---

    def get_api_key(self, service_name: str) -> str | None:
        """Retrieve an API key from the platform's secret store."""
        return None

    def send_notification(
        self, title: str, message: str, is_error: bool = False
    ) -> None:
        """Send a desktop notification."""
