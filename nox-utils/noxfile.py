from pathlib import Path

from tmlt.nox_utils import SessionManager

PACKAGE_NAME = "tmlt.nox_utils"
"""Name of the package."""
PACKAGE_GITHUB = "opendp/tumult-tools"
"""GitHub organization/project."""
CWD = Path(".").resolve()

sm = SessionManager(
    PACKAGE_NAME, PACKAGE_GITHUB, CWD
)
sm.black()
sm.isort()
sm.mypy()
sm.pylint()
sm.pydocstyle()
