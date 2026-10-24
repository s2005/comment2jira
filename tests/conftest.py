"""Shared pytest fixtures for comment2jira.

``resolve_credentials`` falls back to a ``.env`` file (working directory,
then the per-user location) and to ambient ``JIRA_*`` environment
variables. On a developer machine that has either of those, the values
leak into tests asserting on unconfigured behaviour, so every test in
this package runs against empty env-file locations with the ambient
variables removed.
"""

from __future__ import annotations

import pytest

from comment2jira import config as comment2jira_config
from comment2jira.detect import clear_deployment_cache

JIRA_ENV_VARS = (
    "JIRA_URL",
    "JIRA_EMAIL",
    "JIRA_TOKEN",
    "JIRA_AUTH",
    "COMMENT2JIRA_ENV_FILE",
)


@pytest.fixture(autouse=True)
def isolate_user_credentials(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Isolate credential resolution from the developer's own config."""
    empty = tmp_path_factory.mktemp("comment2jira-config")
    monkeypatch.setattr(comment2jira_config, "local_env_file_path", lambda: empty / "local.env")
    monkeypatch.setattr(comment2jira_config, "user_env_file_path", lambda: empty / "user.env")
    for env_var in JIRA_ENV_VARS:
        monkeypatch.delenv(env_var, raising=False)
    # Clear deployment detection cache so each test gets a fresh detection.
    clear_deployment_cache()


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the --jira-env-file option that unlocks the live-Jira suite."""
    parser.addoption(
        "--jira-env-file",
        action="store",
        default=None,
        metavar="PATH",
        help=(
            "run integration tests against the Jira instance whose credentials "
            "are in the env file at PATH (see test.env.example for its keys)"
        ),
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip every integration-marked test unless --jira-env-file was passed."""
    if config.getoption("--jira-env-file"):
        return
    skip_integration = pytest.mark.skip(
        reason="live-Jira test; pass --jira-env-file PATH to run it"
    )
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)
