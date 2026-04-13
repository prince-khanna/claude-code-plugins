"""Linux backend — systemd user timers for task scheduling."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from backends.base import PlatformBackend
from cron_utils import parse_cron_field


# ---------------------------------------------------------------------------
# Cron-to-OnCalendar conversion
# ---------------------------------------------------------------------------

# systemd weekday names indexed by cron dow (0=Sunday)
_SYSTEMD_DOW = {0: "Sun", 1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat"}


def _fmt_range(values: list[int]) -> str:
    """Format a list of ints as a compact range string.

    e.g. [1,2,3,5] -> '1..3,5'
    """
    if not values:
        return "*"
    if len(values) == 1:
        return str(values[0])

    # Detect consecutive runs
    runs: list[list[int]] = []
    current_run = [values[0]]
    for v in values[1:]:
        if v == current_run[-1] + 1:
            current_run.append(v)
        else:
            runs.append(current_run)
            current_run = [v]
    runs.append(current_run)

    parts = []
    for run in runs:
        if len(run) >= 3:
            parts.append(f"{run[0]}..{run[-1]}")
        elif len(run) == 2:
            parts.append(f"{run[0]},{run[1]}")
        else:
            parts.append(str(run[0]))
    return ",".join(parts)


def cron_to_oncalendar(expr: str) -> str:
    """Convert a 5-field cron expression to a systemd OnCalendar specification.

    Examples:
        '0 9 * * *'   -> '*-*-* 09:00:00'
        '0 8 * * 1'   -> 'Mon *-*-* 08:00:00'
        '30 7 * * 1-5' -> 'Mon..Fri *-*-* 07:30:00'
        '*/5 * * * *' -> '*-*-* *:00/5:00'
        '0 9 1 * *'   -> '*-*-01 09:00:00'
    """
    parts = expr.split()
    minute, hour, dom, month, dow = parts

    minute_vals = parse_cron_field(minute, 0, 59)
    hour_vals = parse_cron_field(hour, 0, 23)
    dom_vals = parse_cron_field(dom, 1, 31)
    month_vals = parse_cron_field(month, 1, 12)
    dow_vals = parse_cron_field(dow, 0, 6)

    # Build day-of-week prefix
    dow_prefix = ""
    if dow_vals is not None:
        dow_names = [_SYSTEMD_DOW[d] for d in dow_vals]
        # Detect contiguous range for .. notation
        if len(dow_vals) >= 2 and dow_vals == list(range(dow_vals[0], dow_vals[-1] + 1)):
            dow_prefix = f"{dow_names[0]}..{dow_names[-1]} "
        elif len(dow_vals) == 1:
            dow_prefix = f"{dow_names[0]} "
        else:
            dow_prefix = f"{','.join(dow_names)} "

    # Build date part: YYYY-MM-DD
    month_str = f"{_fmt_range(month_vals):0>2}" if month_vals else "*"
    dom_str = f"{_fmt_range(dom_vals):0>2}" if dom_vals else "*"

    # For multi-value month/dom, zero-pad each individual value
    if month_vals:
        month_str = ",".join(f"{v:02d}" for v in month_vals)
    if dom_vals:
        dom_str = ",".join(f"{v:02d}" for v in dom_vals)

    date_part = f"*-{month_str}-{dom_str}"

    # Build time part: HH:MM:SS
    # Handle step syntax specially for minute field
    if minute.startswith("*/"):
        step = minute[2:]
        minute_time = f"00/{step}"
    elif minute_vals is not None:
        minute_time = ",".join(f"{v:02d}" for v in minute_vals)
    else:
        minute_time = "*"

    if hour.startswith("*/"):
        step = hour[2:]
        hour_time = f"00/{step}"
    elif hour_vals is not None:
        hour_time = ",".join(f"{v:02d}" for v in hour_vals)
    else:
        hour_time = "*"

    time_part = f"{hour_time}:{minute_time}:00"

    return f"{dow_prefix}{date_part} {time_part}"


# ---------------------------------------------------------------------------
# systemd unit templates
# ---------------------------------------------------------------------------

_SERVICE_UNIT_TEMPLATE = """\
[Unit]
Description=Prince Plugins Scheduler: {task_id}

[Service]
Type=oneshot
ExecStart=/bin/bash {wrapper_path}
"""

_TIMER_UNIT_TEMPLATE = """\
[Unit]
Description=Timer for Prince Plugins Scheduler: {task_id}

[Timer]
OnCalendar={oncalendar}
Persistent=true

[Install]
WantedBy=timers.target
"""


# ---------------------------------------------------------------------------
# Linux Backend
# ---------------------------------------------------------------------------

_BACKEND_DIR = Path(__file__).resolve().parent
_SCRIPTS_DIR = _BACKEND_DIR.parent
_SKILL_DIR = _SCRIPTS_DIR.parent
_TEMPLATE_PATH = _SKILL_DIR / "references" / "wrapper-template-linux.sh"

_SERVICE_PREFIX = "launchpad-scheduler-"


class LinuxBackend(PlatformBackend):
    """Linux backend using systemd user timers."""

    def __init__(self) -> None:
        self.systemd_dir = Path(
            os.environ.get(
                "SCHEDULER_SYSTEMD_DIR",
                str(Path.home() / ".config" / "systemd" / "user"),
            )
        )
        self._skip = (
            os.environ.get("SCHEDULER_SKIP_SYSTEMD", "0") == "1"
            or os.environ.get("SCHEDULER_SKIP_PLATFORM", "0") == "1"
        )
        self.template_path = _TEMPLATE_PATH

    # --- Internal helpers ---

    def _unit_name(self, task_id: str) -> str:
        """Return the systemd unit base name (without extension)."""
        return f"{_SERVICE_PREFIX}{task_id}"

    def _service_path(self, task_id: str) -> Path:
        return self.systemd_dir / f"{self._unit_name(task_id)}.service"

    def _timer_path(self, task_id: str) -> Path:
        return self.systemd_dir / f"{self._unit_name(task_id)}.timer"

    def _systemctl(self, *args: str) -> subprocess.CompletedProcess:
        """Run systemctl --user with the given args."""
        return subprocess.run(
            ["systemctl", "--user", *args],
            capture_output=True,
            text=True,
        )

    def _daemon_reload(self) -> None:
        """Reload systemd user daemon to pick up unit changes."""
        if not self._skip:
            self._systemctl("daemon-reload")

    # --- PlatformBackend implementation ---

    def install_schedule(
        self,
        task_id: str,
        task: dict,
        wrapper_path: Path,
        scheduler_dir: Path,
        logs_dir: Path,
    ) -> None:
        """Generate systemd .service + .timer units and enable the timer."""
        cron_expr = task["schedule"]["cron"]
        oncalendar = cron_to_oncalendar(cron_expr)

        self.systemd_dir.mkdir(parents=True, exist_ok=True)

        # Write service unit
        service_content = _SERVICE_UNIT_TEMPLATE.format(
            task_id=task_id,
            wrapper_path=str(wrapper_path),
        )
        self._service_path(task_id).write_text(service_content)

        # Write timer unit
        timer_content = _TIMER_UNIT_TEMPLATE.format(
            task_id=task_id,
            oncalendar=oncalendar,
        )
        self._timer_path(task_id).write_text(timer_content)

        # Reload and enable
        self._daemon_reload()
        if not self._skip:
            timer_name = f"{self._unit_name(task_id)}.timer"
            self._systemctl("enable", "--now", timer_name)

    def uninstall_schedule(self, task_id: str) -> None:
        """Disable timer and remove both unit files."""
        timer_name = f"{self._unit_name(task_id)}.timer"
        if not self._skip:
            self._systemctl("disable", "--now", timer_name)

        for path in (self._timer_path(task_id), self._service_path(task_id)):
            if path.exists():
                path.unlink()

        self._daemon_reload()

    def load_schedule(self, task_id: str) -> None:
        """Re-enable and start the timer (for resume).

        Raises RuntimeError if the timer is not active after the attempt.
        """
        if not self._skip:
            timer_name = f"{self._unit_name(task_id)}.timer"
            self._systemctl("enable", "--now", timer_name)

            # Verify the timer is actually active
            check = self._systemctl("is-active", timer_name)
            if check.stdout.strip() != "active":
                raise RuntimeError(
                    f"Failed to load systemd timer '{timer_name}': "
                    f"timer is '{check.stdout.strip()}' after enable attempt"
                )

    def unload_schedule(self, task_id: str) -> None:
        """Disable the timer without removing unit files (for pause/complete).

        Raises RuntimeError if the timer is still active after the attempt.
        """
        if not self._skip:
            timer_name = f"{self._unit_name(task_id)}.timer"
            self._systemctl("disable", "--now", timer_name)

            # Verify the timer is actually stopped
            check = self._systemctl("is-active", timer_name)
            if check.stdout.strip() == "active":
                raise RuntimeError(
                    f"Failed to unload systemd timer '{timer_name}': "
                    f"timer is still active after disable attempt"
                )

    def schedule_artifact_exists(self, task_id: str) -> bool:
        """Check whether both .service and .timer files exist."""
        return self._service_path(task_id).exists() and self._timer_path(task_id).exists()

    def generate_wrapper(
        self,
        task: dict,
        scheduler_dir: Path,
        scheduler_py_path: Path,
        wrappers_dir: Path,
    ) -> Path:
        """Generate a bash wrapper script from the Linux template."""
        return self._render_wrapper(task, scheduler_dir, scheduler_py_path, wrappers_dir)

    def wrapper_extension(self) -> str:
        return ".sh"

    def run_wrapper(self, wrapper_path: Path) -> int:
        """Execute a wrapper script via /bin/bash."""
        result = subprocess.run(
            ["/bin/bash", str(wrapper_path)],
            capture_output=False,
        )
        return result.returncode

    def skip_scheduling(self) -> bool:
        return self._skip

    def default_schedule_dir(self) -> Path:
        return Path.home() / ".config" / "systemd" / "user"
