"""Per-OS filesystem path resolution for the Rentablez agent.

All other modules that touch the filesystem import Paths.
The ``root`` parameter allows tests to redirect all paths under a tmp dir.
No third-party dependencies — stdlib only.
"""

from __future__ import annotations

import platform


class Paths:
    """Resolved filesystem paths for a specific OS.

    Attributes
    ----------
    config_file, baseline_file, current_file, queue_file, log_file,
    log_dir, state_dir
    """

    def __init__(self, root: str = "", os_name: str | None = None) -> None:
        """Build paths for *os_name* (defaults to the running OS).

        Parameters
        ----------
        root:
            Optional prefix prepended to every path segment.  Used in tests
            to redirect I/O under a temporary directory.  Has no effect on
            Windows — Windows paths are fixed at ``C:\\ProgramData\\Rentablez``.
        os_name:
            Override the OS detection.  Accepts ``"Darwin"`` or ``"Windows"``.
            If omitted, ``platform.system()`` is called.
        """
        detected = os_name if os_name is not None else platform.system()
        if detected == "Darwin":
            self._init_darwin(root)
        elif detected == "Windows":
            self._init_windows(root)
        else:
            raise RuntimeError(
                f"Unsupported OS: {detected!r}. "
                "Only 'Darwin' and 'Windows' are supported."
            )

    # ------------------------------------------------------------------
    # OS-specific initialisers
    # ------------------------------------------------------------------

    def _init_darwin(self, root: str) -> None:
        self.state_dir = f"{root}/var/lib/rentablez"
        self.log_dir = f"{root}/var/log/rentablez"
        self.config_file = f"{root}/etc/rentablez/config.json"
        self.baseline_file = f"{self.state_dir}/baseline.json"
        self.current_file = f"{self.state_dir}/current.json"
        self.queue_file = f"{self.state_dir}/queue.json"
        self.log_file = f"{self.log_dir}/agent.log"

    def _init_windows(self, root: str) -> None:
        # On Windows the base dir is fixed; ``root`` is ignored in production
        # (the setup script handles real install paths).  Tests that supply a
        # root still get sensible values via the Darwin path; Windows tests
        # exercise the production constants only.
        base = r"C:\ProgramData\Rentablez"
        self.state_dir = base
        self.log_dir = rf"{base}\logs"
        self.config_file = rf"{base}\config.json"
        self.baseline_file = rf"{base}\baseline.json"
        self.current_file = rf"{base}\current.json"
        self.queue_file = rf"{base}\queue.json"
        self.log_file = rf"{self.log_dir}\agent.log"

    # ------------------------------------------------------------------
    # Convenience factory
    # ------------------------------------------------------------------

    @classmethod
    def for_current_os(cls) -> Paths:
        """Detect the running OS and return a Paths instance for it."""
        return cls()
