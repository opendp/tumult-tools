"""A central, largely package-agnostic collection of nox utilities.

This module defines SessionManager, which takes in a collection of configuration
options and exposes methods that can be called to generate nox sessions.
"""

from functools import wraps
from pathlib import Path
from typing import Any, Callable, Optional, Union

import nox
from nox import Session, session

from ._dependencies import install_group, show_installed, with_uv_env
from ._environment import in_ci, num_cpus, package_version

# Use uv for managing virtualenvs. This significantly reduces the overhead
# associated with using nox sessions in their own virtualenvs versus running
# with --no-venv.
nox.options.default_venv_backend = "uv"


class SessionManager:
    """Class for creating common Nox sessions based on project-specific configuration.

    To add a session to a particular noxfile, create an instance of this class
    using your desired options, then call the methods corresponding to the
    sessions you want.

    This class leverages the fact that *any* function that is defined with the
    ``@session`` decorator is picked up as a Nox session, no matter where it is
    defined. By wrapping these definitions inside of class methods, we can
    access the class attributes to do project-specific things while still
    maintaining a common collection of sessions that can be reused across
    projects, and can avoid needing boilerplate in the noxfile itself.
    """

    def __init__(
        self,
        package: str,
        directory: Path,
        *,
        default_python_version: str = "3.9",
        custom_build: Optional[Callable[[Session], None]] = None,
        smoketest_script: Optional[str] = None,
        parallel_tests: bool = True,
        min_coverage: int = 80,
        audit_versions: Optional[list[str]] = None,
        audit_suppressions: Optional[list[str]] = None,
    ) -> None:
        """Configure options for generating nox sessions.

        Args:
            package: The name of the package, e.g. ``tmlt.core``.
            directory: The root directory of the package.
            default_python_version: The Python minor version that will be used by
                default for most generated sessions. In general, this should be the
                oldest supported Python version.
            custom_build: A function that overrides the standard build
                process. This function should take a nox Session as its only
                argument, and have no return value. When the function returns,
                wheel and a source distribution for the current version of the
                package should exist in the ``dist/`` subdirectory of the
                package directory.
            smoketest_script: A Python program to execute as a smoke-test for an
                installation of the package -- this should be the script
                content, not the path to an external script. It is considered to
                pass as long as executing the script with `python -c` doesn't
                produce an error. If unset, defaults to just importing the package.
            parallel_tests: Controls whether tests should be run in parallel.
            min_coverage: The minimum coverage needed for the test/test-fast sessions
                to pass.
            audit_versions: A list of Python minor versions on which to audit package
                dependencies for vulnerabilities. If unset, defaults to only
                ``default_python_version``.
            audit_suppressions: A list of vulnerability IDs to ignore.
        """
        self._package = package
        self._package_version = package_version(directory)
        self._directory = directory
        self._default_python_version = default_python_version
        if custom_build is not None and not callable(custom_build):
            raise ValueError(
                f"Provided custom_build must be callable, but '{custom_build}' is not"
            )
        self._custom_build = custom_build
        self._smoketest_script = smoketest_script or f"import {self._package}"
        self._parallel_tests = parallel_tests
        self._min_coverage = min_coverage
        self._audit_versions = audit_versions or [default_python_version]
        self._audit_suppressions = audit_suppressions or []

    @property
    def _test_dirs(self) -> list[Path]:
        return [
            p
            for p in [
                self._directory / "test",
            ]
            if p.exists()
        ]

    @property
    def _source_dirs(self) -> list[Path]:
        return [
            p
            for p in [
                self._directory / "src",
            ]
            if p.exists()
        ]

    @property
    def _code_dirs(self) -> list[Path]:
        return self._source_dirs + self._test_dirs

    def _build(self, sess: Session) -> None:
        """Build sdists and wheels for the package.

        If the build process for a package requires custom logic, pass the
        "build" option to SessionBuilder, with the value being function that
        builds the package taking one argument (a nox Session) . If this option
        is not passed, the package is just built with ``uv build``.
        """
        if self._custom_build is not None:
            sess.log("Using custom build function")
            self._custom_build(sess)
        else:
            sess.run("uv", "build", external=True)

    def _current_wheel_available(self, sess: Session) -> bool:
        package = f"{self._package}=={self._package_version}"
        out = sess.run(
            "uv",
            "pip",
            "install",
            "--dry-run",
            package,
            "--no-deps",
            "--no-index",
            "--find-links",
            f"{self._directory}/dist/",
            "--only-binary",
            self._package,
            silent=True,
            success_codes=[0, 1],
            external=True,
        )
        assert out is not None, "sess.run should not return None when silent=True"
        return "No solution found when resolving dependencies" not in out

    def _install_package(self, f: Callable[[Session], Any]) -> Callable[[Session], Any]:
        """Install the main package and its dependencies from uv lock."""

        @wraps(f)
        @with_uv_env
        def inner(sess: Session) -> Any:
            if not sess.virtualenv.is_sandboxed:
                sess.log(
                    "Not in a sandboxed environment, skipping package installation"
                )
                return f(sess)

            # In the CI we want to use the wheel from the pipeline, but locally
            # it's easier to let uv handle figuring out what to install and
            # how to build it if needed.
            if not in_ci():
                sess.run_install(
                    "uv", "sync", "--no-default-groups", "--inexact", external=True
                )
                return f(sess)

            package = f"{self._package}=={self._package_version}"

            if not self._current_wheel_available(sess):
                sess.error(
                    f"No wheel found for '{package}'; "
                    "wheel must exist when running in CI"
                )

            sess.run_install(
                "uv",
                "sync",
                "--no-install-project",
                "--no-default-groups",
                "--inexact",
                external=True,
            )
            sess.install(
                package,
                "--no-deps",
                "--no-index",
                "--find-links",
                f"{self._directory}/dist/",
                "--only-binary",
                self._package,
            )
            return f(sess)

        return inner

    def _install_package_with_unlocked_deps(
        self, f: Callable[[Session], Any]
    ) -> Callable[[Session], Any]:
        """Install the main package and its dependencies as resolved by pip.

        Unlike _install_package, this method ignores the uv lock and relies on
        pip to install whatever versions of dependencies it likes, simulating
        how the package might be installed on a user's machine. Also unlike
        _install_package, this method will only install from a built wheel in
        ``dist/``. Locally, it will try to build a new wheel if it can't find
        one, and it will refuse to run with ``--no-venv``.
        """

        @wraps(f)
        def inner(sess: Session) -> Any:
            if not sess.virtualenv.is_sandboxed:
                sess.error("Release checks cannot be run with --no-venv")

            package = f"{self._package}=={self._package_version}"

            if not self._current_wheel_available(sess):
                if in_ci():
                    sess.error(
                        f"No wheel found for '{package}'; "
                        "wheel must exist when running in CI"
                    )
                else:
                    sess.log("No wheel found, building one")
                    self._build(sess)

            sess.install(
                package,
                "--find-links",
                f"{self._directory}/dist/",
                "--only-binary",
                self._package,
            )
            return f(sess)

        return inner

    def build(self) -> None:
        @session(name="build", python=self._default_python_version)
        def build(sess: Session) -> None:
            """Build source distributions and wheels for this package."""
            self._build(sess)

    def black(self) -> None:
        @session(name="black", tags=["lint"], python=self._default_python_version)
        @install_group("black")
        def black(sess: Session) -> None:
            """Run black."""
            check_flags = ["--check", "--diff"] if "--check" in sess.posargs else []
            sess.run("black", *check_flags, *self._code_dirs)

    def isort(self) -> None:
        @session(name="isort", tags=["lint"], python=self._default_python_version)
        @install_group("isort")
        def isort(sess: Session) -> None:
            """Run isort."""
            check_flags = ["--check", "--diff"] if "--check" in sess.posargs else []
            sess.run("isort", *check_flags, *self._code_dirs)

    def mypy(self) -> None:
        @session(name="mypy", tags=["lint"], python=self._default_python_version)
        @self._install_package
        @install_group("mypy")
        def mypy(sess: Session) -> None:
            """Run mypy."""
            sess.run("mypy", *self._code_dirs)

    def pylint(self) -> None:
        @session(name="pylint", tags=["lint"], python=self._default_python_version)
        @self._install_package
        @install_group("pylint")
        def pylint(sess: Session) -> None:
            """Run pylint."""
            sess.run("pylint", "--score=no", "--recursive=y", *self._code_dirs)

    def pydocstyle(self) -> None:
        @session(name="pydocstyle", tags=["lint"], python=self._default_python_version)
        @install_group("pydocstyle")
        def pydocstyle(sess: Session) -> None:
            """Run pydocstyle."""
            sess.run("pydocstyle", *self._code_dirs)

    def smoketest(self) -> None:
        @session(name="smoketest", tags=["test"], python=self._default_python_version)
        @self._install_package
        def smoketest(sess: Session) -> None:
            """Run a simple smoke-test of the package."""
            sess.run("python", "-c", self._smoketest_script)

    def release_smoketest(self) -> None:
        @session(
            name="release-smoketest",
            tags=["release"],
            python=self._default_python_version,
        )
        @self._install_package_with_unlocked_deps
        @show_installed
        def release_smoketest(sess: Session) -> None:
            """Run a simple smoke-test of the package."""
            sess.run("python", "-c", self._smoketest_script)

    def _test(
        self,
        sess: Session,
        markers: str = "",
        *,
        min_coverage: Optional[int] = None,
        extra_args: Optional[list[str]] = None,
        test_paths: Optional[list[Path]] = None,
    ) -> None:
        test_paths = self._code_dirs if test_paths is None else test_paths
        extra_args = extra_args or []
        if sess.posargs:
            test_paths = []
            extra_args.extend(sess.posargs)
        args: list[Union[str, Path]] = [
            "-r fEs",
            "--verbose",
            "--disable-warnings",
            f"--junitxml={self._directory}/junit.xml",
            "--durations=10",
            f"--cov={self._package}",
            "--cov-fail-under={}".format(
                self._min_coverage if min_coverage is None else min_coverage
            ),
            "--cov-report=term",
            f"--cov-report=html:{self._directory}/coverage/",
            f"--cov-report=xml:{self._directory}/coverage.xml",
            *extra_args,
            *test_paths,
        ]
        cpus = num_cpus(sess)
        if self._parallel_tests and cpus > 3:
            args.append(f"--numprocesses={cpus//2}")
        if markers:
            args.extend(["-m", markers])

        sess.run("pytest", *args)

    def test(self) -> None:
        @session(name="test", python=self._default_python_version)
        @self._install_package
        @install_group("test")
        def test(sess: Session) -> None:
            """Run all tests."""
            self._test(sess)

    def test_fast(self) -> None:
        @session(name="test-fast", python=self._default_python_version)
        @self._install_package
        @install_group("test")
        def test_fast(sess: Session) -> None:
            """Run fast tests."""
            self._test(sess, "not slow")

    def test_slow(self) -> None:
        @session(name="test-slow", python=self._default_python_version)
        @self._install_package
        @install_group("test")
        def test_slow(sess: Session) -> None:
            """Run slow tests."""
            self._test(sess, "slow", min_coverage=0)

    def test_doctest(self) -> None:
        @session(
            name="test-doctest", tags=["test"], python=self._default_python_version
        )
        @self._install_package
        @install_group("test")
        def test_doctest(sess: Session) -> None:
            """Run tests on code examples in docstrings."""
            self._test(
                sess,
                min_coverage=0,
                extra_args=["--doctest-modules"],
                test_paths=self._source_dirs,
            )

    def _run_sphinx(self, sess: Session, builder: str) -> None:
        sphinx_options = ["-n", "-W", "--keep-going"]
        sess.run("sphinx-build", "doc/", "public/", f"-b={builder}", *sphinx_options)

    def docs_linkcheck(self) -> None:
        @session(
            name="docs-linkcheck", tags=["docs"], python=self._default_python_version
        )
        @self._install_package
        @install_group("docs")
        def docs_linkcheck(sess: Session) -> None:
            """Check links in documentation."""
            self._run_sphinx(sess, "linkcheck")

    def docs_doctest(self) -> None:
        @session(
            name="docs-doctest", tags=["docs"], python=self._default_python_version
        )
        @self._install_package
        @install_group("docs")
        @install_group("docs-examples")
        def docs_linkcheck(sess: Session) -> None:
            """Check code examples in documentation."""
            self._run_sphinx(sess, "doctest")

    def docs(self) -> None:
        @session(name="docs", tags=["docs"], python=self._default_python_version)
        @self._install_package
        @install_group("docs")
        def docs(sess: Session) -> None:
            """Build HTML documentation."""
            self._run_sphinx(sess, "html")

    def audit(self) -> None:
        """Generate the audit parameterized Nox session.

        To be useful, this function needs the `audit_versions` option to be
        set. It should contain a list of Python versions to be audited.
        """
        # Should produce --ignore-vuln [vuln_id] for each vulnerability ID
        ignore_options = [
            i for vuln in self._audit_suppressions for i in ("--ignore-vuln", vuln)
        ]

        @session(name="audit")
        @self._install_package
        @install_group("audit")
        @show_installed
        @nox.parametrize("python", self._audit_versions)
        def audit(sess: Session) -> None:
            """Check for vulnerable dependencies."""
            sess.run("pip-audit", "-v", "--progress-spinner", "off", *ignore_options)

    def benchmark(self, script: Path, timeout: int) -> None:
        """Generate a Nox session running the given benchmark.

        The stem of the script file name will be used as the benchmark name, so
        passing ``benchmarks/foo.py`` would produce a session named
        ``benchmark-foo``.

        Args:
            script: The path to the benchmark script.
            timeout: The time before the benchmark will be considered failed and
                killed, in seconds.
        """
        name = script.stem.replace("_", "-")

        @session(name=f"benchmark-{name}", tags=["benchmark"])
        @self._install_package
        def benchmark(sess: Session) -> None:
            (self._directory / "benchmark_output").mkdir(exist_ok=True)
            sess.log("Exit code 124 indicates a timeout, others are script errors")
            # If we want to run benchmarks on non-Linux platforms this will probably
            # have to be reworked, but it's fine for now.
            sess.run(
                "timeout",
                f"{timeout}s",
                "bash",
                "-c",
                f'time python "{script}"',
                external=True,
            )

        # You can't use f-strings as ordinary docstrings, but by assigning
        # directly to __doc__ we can.
        benchmark.__doc__ = f"Run {name} benchmark."
