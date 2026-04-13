"""Platform detection and backend factory."""

from __future__ import annotations

import platform

from backends.base import PlatformBackend


def detect_platform() -> str:
    """Detect the current platform.

    Returns one of: 'macos', 'linux', 'windows'.
    Raises RuntimeError for unsupported platforms.
    """
    system = platform.system()
    if system == "Darwin":
        return "macos"
    elif system == "Linux":
        return "linux"
    elif system == "Windows":
        return "windows"
    else:
        raise RuntimeError(f"Unsupported platform: {system}")


def get_backend(platform_name: str | None = None) -> PlatformBackend:
    """Get the appropriate backend for the given or detected platform.

    Args:
        platform_name: Override platform detection. One of 'macos', 'linux', 'windows'.
                       If None, auto-detects from the current OS.
    """
    if platform_name is None:
        platform_name = detect_platform()

    if platform_name == "macos":
        from backends.macos import MacOSBackend
        return MacOSBackend()
    elif platform_name == "linux":
        from backends.linux import LinuxBackend
        return LinuxBackend()
    elif platform_name == "windows":
        from backends.windows import WindowsBackend
        return WindowsBackend()
    else:
        raise RuntimeError(f"No backend for platform: {platform_name}")
