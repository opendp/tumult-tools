"""Utility functions."""

from nox import Session


def get_session(args) -> Session:
    """Given an argument list, get the Nox session from it.

    This is a hack to allow using decorators interchangeably on normal functions
    and class methods, as it effectively allows skipping the `self` argument to
    class methods.
    """
    if len(args) > 0 and isinstance(args[0], Session):
        return args[0]
    elif len(args) > 1 and isinstance(args[1], Session):
        return args[1]
    else:
        raise AssertionError("Couldn't find Nox session")
