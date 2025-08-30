"""Utilities for managing and inspecting dependencies in nox environments."""

from functools import wraps
from typing import Any, Callable, Dict, NamedTuple

from nox import Session


class DependencyConfiguration(NamedTuple):
    """A named set of dependencies under which to run a session.

    Args:
        id: A name that can be used to identify this set of dependencies.
        python: The python version to run under. E.g. '3.9'
        packages: A dictionary containing any packages that should be pinned for
            this configuration. Keys should be package names, and values should be
            versions, in PEP440 format. E.g. `{"tmlt.core": ">=0.11.2,<0.12.0"}`.
            Packages in this dictionary will be installed after the full set of
            dependencies, and will override versions specified in the lockfile.
    """

    id: str
    python: str
    packages: Dict[str, str]


def with_uv_env(f: Callable[[Session], Any]) -> Callable[[Session], Any]:
    """Configure given session to allow managing packages with uv."""

    @wraps(f)
    def inner(sess: Session, *args, **kwargs) -> Any:
        if sess.virtualenv.is_sandboxed:
            sess.env["UV_PROJECT_ENVIRONMENT"] = sess.virtualenv.location
        return f(sess, *args, **kwargs)

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
        def inner(sess: Session, *args, **kwargs) -> Any:
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
                f"--python={sess.virtualenv.location}",
                external=True,
                env={"UV_PROJECT_ENVIRONMENT": sess.virtualenv.location},
            )
            return f(sess, *args, **kwargs)

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
