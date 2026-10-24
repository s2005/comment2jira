"""Deployment-type detection for comment2jira.

Copied verbatim from jira2md with logger name adjusted to comment2jira.

``GET /rest/api/2/serverInfo`` reports ``deploymentType``; the result
is cached per host for the session.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

logger = logging.getLogger("comment2jira")

DEPLOYMENT_CLOUD = "cloud"
DEPLOYMENT_DC = "dc"

_session_cache: dict[str, str] = {}


class ServerInfoSource(Protocol):
    """Minimal client surface needed for deployment detection."""

    async def get_server_info(self) -> dict[str, Any]:
        """Fetch /rest/api/2/serverInfo."""
        ...


def clear_deployment_cache() -> None:
    """Drop the per-session deployment cache (used by tests)."""
    _session_cache.clear()


def deployment_from_server_info(info: dict[str, Any]) -> str:
    """Map a serverInfo payload to a deployment type."""
    deployment_type = str(info.get("deploymentType") or "").lower()
    return DEPLOYMENT_CLOUD if deployment_type == "cloud" else DEPLOYMENT_DC


async def detect_deployment(
    client: ServerInfoSource,
    *,
    override: str | None = None,
    host: str = "",
) -> str:
    """Detect whether the target is Cloud or Server/Data Center.

    Args:
        client: Client able to fetch serverInfo.
        override: Explicit deployment selection, bypassing detection.
        host: Host key for the per-session cache.

    Returns:
        ``cloud`` or ``dc``.
    """
    if override:
        return override
    if host and host in _session_cache:
        return _session_cache[host]
    info = await client.get_server_info()
    deployment = deployment_from_server_info(info)
    if host:
        _session_cache[host] = deployment
    logger.debug("Detected deployment %s for host %s", deployment, host)
    return deployment
