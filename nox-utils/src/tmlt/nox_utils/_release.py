"""Tools for creating releases."""

import datetime
import re
import textwrap
from pathlib import Path

from git import Repo
from git.refs.remote import RemoteReference
from git.refs.tag import Tag
from git.remote import Remote
from nox import Session


def push_release_commits(
    sess: Session, directory: Path, package_github: str, version: str
) -> None:
    """Create and push a release branch/tag for the current commit."""
    version_match = re.fullmatch(
        (
            r"(?P<base>(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*))"
            r"(?P<prerelease>-(dev|alpha|beta|rc)\.(0|[1-9][0-9]*))?"
        ),
        version,
    )
    if version_match is None:
        sess.error(
            "Provided version number does not match expected semantic version format. "
            "Versions should look like e.g. 0.1.2 or 1.2.1-alpha.2 -- other acceptable "
            "pre-release types are dev, beta, and rc."
        )

    is_prerelease = version_match.group("prerelease") is not None

    repo = Repo(directory)
    origin = Remote(repo, "origin")
    current_branch = repo.head.reference

    if repo.is_dirty():
        sess.error(
            "Git repo is dirty, stash or commit your changes before making a release"
        )
    if repo.untracked_files:
        sess.error(
            "Git repo contains untracked files, stash or commit your changes before "
            "making a release"
        )

    if current_branch.path != "refs/heads/main" and not is_prerelease:
        sess.error("Releases may only be made from the main branch")

    if not origin.exists():
        sess.error("No remote 'origin' exists, unsure where to push changes")

    sess.debug("Fetching latest state from origin...")
    repo.git.fetch("origin", "--tags")

    if RemoteReference(repo, f"refs/remotes/origin/release/{version}") in origin.refs:
        sess.error(f"Branch release/{version} already exists")
    if Tag(repo, f"refs/tags/{version}") in Tag.list_items(repo):
        sess.error(f"Release tag {version} already exists")

    if not is_prerelease:
        sess.debug('Updating changelog "Unreleased" header...')
        try:
            _update_changelog_unreleased(version)
        except RuntimeError as e:
            sess.error(str(e))
    else:
        sess.debug("This is a prerelease, skipping changelog update")

    sess.debug("Creating release branch...")
    release_branch = repo.create_head(f"release/{version}")
    repo.head.reference = release_branch  # type: ignore[misc]
    sess.debug("Creating release commit...")
    repo.index.add(["CHANGELOG.rst"])
    repo.index.commit(f"[auto] Release {version}")
    sess.debug("Creating release tag...")
    release_tag = repo.create_tag(version)

    if not is_prerelease:
        _add_changelog_unreleased()

    sess.debug("Creating post-release commit...")
    repo.index.add(["CHANGELOG.rst"])
    repo.index.commit(f"[auto] Post-release {version}")

    sess.debug("Pushing release tag and branch...")
    origin.push(release_branch)
    origin.push(release_tag)

    sess.debug("Switching back to original branch...")
    repo.head.reference = current_branch  # type: ignore[misc]
    repo.head.reset(index=True, working_tree=True)

    sess.debug(
        "Release push completed, tag is at: "
        f"https://github.com/{package_github}/releases/tag/{release_tag}"
    )

    sess.debug(
        "For non-dev releases, please merge release branch to main by creating a PR "
        "(even if there are no changes):"
    )
    sess.debug(f"https://github.com/{package_github}/compare/{release_branch}?expand=1")


def _update_changelog_unreleased(version: str) -> None:
    """Replace the "Unreleased" changelog header with one for the given version.

    Also adds an anchor for the version number so we can reference it elsewhere.
    The automatic anchor for the header doesn't work because Sphinx doesn't
    support anchors that start with digits.
    """
    with Path("CHANGELOG.rst").open("r", encoding="utf-8") as fp:
        changelog_content = fp.readlines()
    for i, line_content in enumerate(changelog_content):
        if re.match("^Unreleased$", line_content):
            if (
                len(changelog_content) <= i + 1
                or changelog_content[i + 1] != "----------\n"
            ):
                raise RuntimeError(
                    "Renaming unreleased section in changelog failed, section header "
                    "appears to be malformed"
                )

            # BEFORE
            # Unreleased
            # ----------

            # AFTER
            # .. _v1.2.3:
            #
            # 1.2.3 - 2020-01-01
            # ------------------
            version_header_title = f"{version} - {datetime.date.today()}"
            version_header = textwrap.dedent(
                f"""
                .. _v{version}:

                {version_header_title}
                {'-' * len(version_header_title)}
                """
            )

            changelog_content = (
                changelog_content[:i]
                + version_header.splitlines(keepends=True)
                + changelog_content[i + 2 :]
            )
            break
    else:
        raise RuntimeError(
            "Renaming unreleased section in changelog failed, "
            "unable to find matching line"
        )
    with Path("CHANGELOG.rst").open("w", encoding="utf-8") as fp:
        fp.writelines(changelog_content)


def _add_changelog_unreleased() -> None:
    """Add a new "Unreleased" section above the most recent release section."""
    unreleased_header = ["Unreleased\n", "----------\n", "\n"]

    anchor_regex = (
        r"^\.\. _v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
        r"(-(alpha|beta|rc)\.(0|[1-9]\d*))?:$"
    )

    with Path("CHANGELOG.rst").open("r", encoding="utf-8") as fp:
        changelog_content = fp.readlines()
        for i, line_content in enumerate(changelog_content):
            # If there's already an unreleased header, something has gone wrong.
            if line_content == unreleased_header[0]:
                raise RuntimeError(
                    f"Changelog already contains an unreleased section on line {i+1}"
                )
            if re.match(anchor_regex, line_content):
                for new_line in reversed(unreleased_header):
                    changelog_content.insert(i, new_line)
                break
        else:
            raise RuntimeError(
                "Adding unreleased section in changelog failed, "
                "unable to find release section to place it before"
            )

        with Path("CHANGELOG.rst").open("w", encoding="utf-8") as fp:
            fp.writelines(changelog_content)
