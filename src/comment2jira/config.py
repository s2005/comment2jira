"""Credential and option resolution for comment2jira.

Copied from jira2md with renames: ``JIRA2MD_ENV_FILE`` ->
``COMMENT2JIRA_ENV_FILE`` and per-user env dir ``jira2md`` -> ``comment2jira``.

Resolution order, first hit wins: CLI flags, ``JIRA_URL`` / ``JIRA_EMAIL``
/ ``JIRA_TOKEN`` environment variables, then a ``.env`` file. The env file
is ``--env-file`` / ``COMMENT2JIRA_ENV_FILE`` when given, otherwise
``./.env``, otherwise ``~/.config/comment2jira/.env``
(``%APPDATA%/comment2jira/.env`` on Windows). The first env file that exists
wins; they are not merged.
"""

from __future__ import annotations

import base64
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from dotenv import dotenv_values

logger = logging.getLogger("comment2jira")

AUTH_AUTO = "auto"
AUTH_BASIC = "basic"
AUTH_BEARER = "bearer"

ENV_URL = "JIRA_URL"
ENV_EMAIL = "JIRA_EMAIL"
ENV_TOKEN = "JIRA_TOKEN"
ENV_AUTH = "JIRA_AUTH"
ENV_FILE = "COMMENT2JIRA_ENV_FILE"


class ConfigError(Exception):
    """Raised when credential resolution fails."""


def local_env_file_path() -> Path:
    """Locate the working-directory ``.env`` file."""
    return Path(".env")


def user_env_file_path() -> Path:
    """Locate the per-user ``.env`` file."""
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "comment2jira" / ".env"
    return Path.home() / ".config" / "comment2jira" / ".env"


def _read_env_file(path: Path) -> dict[str, str]:
    """Parse one ``.env`` file, dropping blank and valueless keys."""
    try:
        raw = dotenv_values(path, encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not read env file %s: %s", path, exc)
        return {}
    return {key: value for key, value in raw.items() if value}


def _load_env_file(env_file: Path | None, environment: Mapping[str, str]) -> dict[str, str]:
    """Load the first applicable ``.env`` file.

    Args:
        env_file: Explicit path from ``--env-file`` (highest priority).
        environment: Environment mapping, consulted for ``COMMENT2JIRA_ENV_FILE``.

    Returns:
        Mapping of ``JIRA_*`` names to values; empty when no file applies.

    Raises:
        ConfigError: When an explicitly requested env file does not exist.
    """
    explicit = env_file
    if explicit is None and environment.get(ENV_FILE):
        explicit = Path(environment[ENV_FILE])
    if explicit is not None:
        if not explicit.is_file():
            msg = f"Env file not found: {explicit}"
            raise ConfigError(msg)
        logger.debug("Loading credentials from %s", explicit)
        return _read_env_file(explicit)

    for candidate in (local_env_file_path(), user_env_file_path()):
        if candidate.is_file():
            logger.debug("Loading credentials from %s", candidate)
            return _read_env_file(candidate)
    return {}


@dataclass(frozen=True)
class Credentials:
    """Resolved Jira credentials.

    The token is never rendered by ``repr`` so it cannot leak into
    logs or tracebacks.
    """

    url: str
    email: str | None = None
    token: str | None = None
    auth: str = AUTH_AUTO

    @property
    def scheme(self) -> str:
        """Effective auth scheme: basic (email + token) or bearer (PAT)."""
        if self.auth == AUTH_BASIC:
            return AUTH_BASIC
        if self.auth == AUTH_BEARER:
            return AUTH_BEARER
        return AUTH_BEARER if not self.email else AUTH_BASIC

    @property
    def host(self) -> str:
        """Hostname of the Jira base URL."""
        return urlparse(self.url).hostname or self.url

    def auth_header(self) -> str:
        """Build the Authorization header value."""
        if self.scheme == AUTH_BEARER:
            return f"Bearer {self.token or ''}"
        raw = f"{self.email or ''}:{self.token or ''}".encode()
        return f"Basic {base64.b64encode(raw).decode('ascii')}"

    def __repr__(self) -> str:
        """Mask the token in any textual representation."""
        token = "***" if self.token else None
        return (
            f"Credentials(url={self.url!r}, email={self.email!r}, "
            f"token={token!r}, auth={self.auth!r})"
        )


def _normalize_auth(value: str | None) -> str:
    """Normalise an explicit auth selection to a known scheme."""
    if value and value.lower() in (AUTH_BASIC, AUTH_BEARER):
        return value.lower()
    if value:
        logger.debug("Ignoring unknown auth scheme %r, using auto", value)
    return AUTH_AUTO


def resolve_credentials(
    *,
    url: str | None = None,
    email: str | None = None,
    token: str | None = None,
    auth: str | None = None,
    env_file: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> Credentials:
    """Resolve credentials from flags, env vars, and a ``.env`` file.

    Args:
        url: Jira base URL from the CLI flag.
        email: Account email from the CLI flag.
        token: API token or PAT from the CLI flag.
        auth: Explicit auth scheme (``basic`` or ``bearer``).
        env_file: Explicit ``.env`` path; defaults to ``./.env`` then the
            per-user location.
        env: Environment mapping override (defaults to ``os.environ``).

    Returns:
        Fully resolved Credentials.

    Raises:
        ConfigError: When no Jira URL can be resolved, or when an
            explicitly requested env file does not exist.
    """
    environment = dict(os.environ if env is None else env)
    file_data = _load_env_file(env_file, environment)

    def pick(flag: str | None, key: str) -> str | None:
        if flag:
            return flag
        if environment.get(key):
            return environment[key]
        if file_data.get(key):
            return file_data[key]
        return None

    resolved_url = pick(url, ENV_URL)
    resolved_email = pick(email, ENV_EMAIL)
    resolved_token = pick(token, ENV_TOKEN)
    resolved_auth = _normalize_auth(pick(auth, ENV_AUTH))

    if not resolved_url:
        msg = "No Jira URL provided (use --url, JIRA_URL, or a .env file)."
        raise ConfigError(msg)

    return Credentials(
        url=resolved_url.rstrip("/"),
        email=resolved_email,
        token=resolved_token,
        auth=resolved_auth,
    )
