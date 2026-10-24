"""Fixtures for the live-Jira integration suite.

Credentials come from the env file named by the ``--jira-env-file`` pytest
option; the suite is skipped when the option is not given. Keep that file
out of version control (``*.env`` is gitignored). Nothing in this module
ever logs or asserts on a credential value: the fixtures only report
whether a key is present.

The suite additionally needs ``JIRA_TEST_ISSUE`` - the key of a scratch
issue that the tests are allowed to comment on and attach files to. See
``test.env.example`` for every recognised key.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from dotenv import dotenv_values

# Keys copied from the env file into the process environment for the CLI to read.
CREDENTIAL_KEYS = ("JIRA_URL", "JIRA_EMAIL", "JIRA_TOKEN", "JIRA_AUTH")
REQUIRED_KEYS = ("JIRA_URL", "JIRA_TOKEN", "JIRA_TEST_ISSUE")


def _load_test_env(path: Path) -> dict[str, str]:
    """Read the env file into a mapping, dropping keys with empty values."""
    values = dotenv_values(path)
    return {key: value for key, value in values.items() if value}


@pytest.fixture(scope="session")
def test_env(pytestconfig: pytest.Config) -> dict[str, str]:
    """Return the parsed --jira-env-file, skipping the suite when unusable."""
    option = pytestconfig.getoption("--jira-env-file")
    if not option:
        pytest.skip("live-Jira test; pass --jira-env-file PATH to run it")
    path = Path(option)
    if not path.is_file():
        pytest.skip(f"--jira-env-file does not name an existing file: {path}")
    values = _load_test_env(path)
    missing = [key for key in REQUIRED_KEYS if key not in values]
    if missing:
        pytest.skip(f"--jira-env-file is missing required keys: {', '.join(missing)}")
    return values


@pytest.fixture(autouse=True)
def live_credentials(
    test_env: dict[str, str],
    isolate_user_credentials: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Put the test.env credentials back after the isolation fixture cleared them.

    Depends on ``isolate_user_credentials`` so it always runs after it; the
    package-wide fixture deletes every ``JIRA_*`` variable, which would
    otherwise leave the CLI with no way to reach the live instance.
    """
    for key in CREDENTIAL_KEYS:
        if key in test_env:
            monkeypatch.setenv(key, test_env[key])


@pytest.fixture
def issue_key(test_env: dict[str, str]) -> str:
    """Key of the scratch issue the suite is allowed to write to."""
    return test_env["JIRA_TEST_ISSUE"]


@pytest.fixture
def jira_read(test_env: dict[str, str]) -> Iterator[Any]:
    """Return a callable performing an authenticated GET against Jira.

    Read-back helper only: the CLI is the thing under test, so assertions
    fetch issue state through this instead of trusting an exit code.
    """
    url = test_env["JIRA_URL"].rstrip("/")
    email = test_env.get("JIRA_EMAIL")
    token = test_env["JIRA_TOKEN"]
    auth: httpx.Auth | None = httpx.BasicAuth(email, token) if email else None
    headers = {"Accept": "application/json"}
    if auth is None:
        headers["Authorization"] = f"Bearer {token}"

    with httpx.Client(base_url=url, headers=headers, auth=auth, timeout=30.0) as client:

        def get(path: str, **params: Any) -> dict[str, Any]:
            response = client.get(path, params=params or None)
            response.raise_for_status()
            payload: dict[str, Any] = response.json()
            return payload

        yield get


@pytest.fixture
def latest_comment(jira_read: Any, issue_key: str) -> Any:
    """Return a callable fetching the most recent comment on the scratch issue."""

    def fetch() -> dict[str, Any]:
        payload = jira_read(
            f"/rest/api/2/issue/{issue_key}/comment",
            orderBy="-created",
            maxResults=1,
        )
        comments = payload.get("comments") or []
        assert comments, f"no comments found on {issue_key}"
        first: dict[str, Any] = comments[0]
        return first

    return fetch


@pytest.fixture
def attachment_filenames(jira_read: Any, issue_key: str) -> Any:
    """Return a callable listing the attachment filenames on the scratch issue."""

    def fetch() -> list[str]:
        payload = jira_read(f"/rest/api/2/issue/{issue_key}", fields="attachment")
        attachments = payload.get("fields", {}).get("attachment") or []
        return [str(entry.get("filename", "")) for entry in attachments]

    return fetch
