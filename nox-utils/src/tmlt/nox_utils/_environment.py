"""Utilities for inspecting the environment where nox is running."""

import os
import platform
import subprocess

from nox import Session


def in_ci() -> bool:
    """Return whether nox is running in a CI pipeline."""
    return bool(os.environ.get("CI"))


def num_cpus(sess: Session) -> int:
    """Return the number of CPU cores on the current machine."""
    try:
        if platform.system() == "Darwin":
            command = "sysctl -n hw.physicalcpu"
        elif platform.system() == "Linux":
            command = "nproc --all"
        else:
            sess.log(
                f"Unable to detect CPU count on {platform.system()}, defaulting to 1"
            )
            return 1
        cores = int(subprocess.check_output(command, shell=True).strip())
    except (subprocess.CalledProcessError, ValueError) as e:
        sess.warn(f"Error getting CPU count, defaulting to 1: {e}")
        cores = 1
    return cores
