"""Utilities for managing and inspecting dependencies in nox environments."""

from functools import wraps
from typing import Any, Callable

from nox import Session


def with_uv_env(f: Callable[[Session], Any]) -> Callable[[Session], Any]:
    """Configure given session to allow managing packages with uv."""

    @wraps(f)
    def inner(sess: Session) -> Any:
        if sess.virtualenv.is_sandboxed:
            sess.env["UV_PROJECT_ENVIRONMENT"] = sess.virtualenv.location
        return f(sess)

    return inner


def install_group(
    group: str,
) -> Callable[[Callable[[Session], Any]], Callable[[Session], Any]]:
    """Install the given uv dependency group.

    Note that this does not install the root package and its dependencies, just
    the contents of the given dependency group.
    """

    def decorator(f: Callable[[Session], Any]) -> Callable[[Session], Any]:
        @wraps(f)
        @with_uv_env
        def inner(sess: Session) -> Any:
            if not sess.virtualenv.is_sandboxed:
                sess.log(
                    "Not in a sandboxed environment, skipping package installation"
                )
                return f(sess)

            sess.run_install(
                "uv",
                "sync",
                "--only-group",
                group,
                "--no-install-project",
                "--inexact",
                external=True,
            )
            return f(sess)

        return inner

    return decorator


def show_installed(f: Callable[[Session], Any]) -> Callable[[Session], Any]:
    """Print all installed packages in the current environment."""

    @wraps(f)
    @with_uv_env
    def inner(sess: Session) -> Any:
        sess.run("uv", "pip", "freeze", external=True)
        return f(sess)

    return inner
