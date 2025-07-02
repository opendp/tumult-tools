from pathlib import Path

from tmlt.nox_utils import SessionManager

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
