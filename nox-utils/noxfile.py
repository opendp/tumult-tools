from pathlib import Path

import nox
from nox import session as session
from tmlt.nox_utils import SessionManager, install_group

# Use uv for managing virtualenvs, if it's available. This significantly reduces
# the overhead associated with using nox sessions in their own virtualenvs
# versus running with --no-venv.
nox.options.default_venv_backend = "uv|virtualenv"

PACKAGE_NAME = "tmlt.nox_utils"
"""Name of the package."""
CWD = Path(".").resolve()

sm = SessionManager(
    PACKAGE_NAME, CWD,
)
sm.black()
sm.isort()
sm.mypy()
sm.pylint()
sm.pydocstyle()
