"""A central, largely package-agnostic collection of nox utilities."""

from ._dependencies import (
    DependencyConfiguration,
    install_group,
    show_installed,
    with_uv_env,
)
from ._session_manager import SessionManager
