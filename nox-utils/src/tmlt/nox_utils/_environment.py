"""Utilities for inspecting the environment where nox is running."""

import os
import platform
import subprocess
import tempfile
from functools import wraps
from pathlib import Path

import uv_dynamic_versioning.main as uvdv
from nox import Session

from .utils import get_session


def in_ci() -> bool:
    """Return whether nox is running in a CI pipeline."""
    return bool(os.environ.get("CI"))


def package_version(directory: Path) -> str:
    """Determine the package version for the package in the given directory."""
    # This method is needed because uv does not currently support using the
    # `uv version` command to determine the version number of a package that
    # has a dynamically-computed version. To get around this, we're reaching
    # into the uv_dynamic_versioning internals to compute the version number
    # the way it does. This may be slightly fragile, as these functions may
    # not be intended to be called directly.
    uvdv_config = uvdv.validate(
        uvdv.parse(
            uvdv.read(directory),
        )
    ).tool.uv_dynamic_versioning
    return uvdv.get_version(uvdv_config)[0]


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


def with_clean_workdir(f):
    """If in a sandboxed virtualenv, execute session from an empty tempdir.

    This decorator works around an issue with the tests where they will try to
    use the code (and thus the shared libraries) from the repository rather than
    the wheel that should be used. By moving to a temporary directory before
    running the tests, the repository is not in the Python load path, so the
    problem is resolved.
    """

    @wraps(f)
    def inner(*args, **kwargs):
        print("with_clean_workdir")
        print(args)
        print(kwargs)
        session = get_session(args)
        if session.virtualenv.is_sandboxed:
            with tempfile.TemporaryDirectory() as workdir, session.cd(workdir):
                return f(*args, **kwargs)
        else:
            return f(*args, **kwargs)

    return inner
