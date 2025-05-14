"""Utilities for managing and inspecting dependencies in nox environments."""

from functools import wraps
from typing import Any, Callable

from nox import Session


def install_group(
    group: str,
) -> Callable[[Callable[[Session], Any]], Callable[[Session], Any]]:
    """Install the given Poetry dependency group.

    Note that this does not install the root package and its dependencies, just
    the contents of the given dependency group.
    """

    def decorator(f: Callable[[Session], Any]) -> Callable[[Session], Any]:
        @wraps(f)
        def inner(sess: Session) -> Any:
            if not sess.virtualenv.is_sandboxed:
                sess.log(
                    "Not in a sandboxed environment, skipping package installation"
                )
                return f(sess)

            sess.run_install(
                "poetry", "install", "--only", group, "--no-root", external=True
            )
            return f(sess)

        return inner

    return decorator


def show_installed(f: Callable[[Session], Any]) -> Callable[[Session], Any]:
    """Print all installed packages in the current environment."""

    @wraps(f)
    def inner(sess: Session) -> Any:
        sess.run("pip", "freeze", external=True)
        return f(sess)

    return inner
