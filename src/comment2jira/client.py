"""HTTP client for comment2jira.

Copied from jira2md with fetch-only endpoints removed; Phase 3 added
post_comment and upload_attachment. Retains the exception hierarchy,
retry loop, backoff logic, and serverInfo endpoint used by detect.py.

Direct ``httpx`` client against Jira REST API v2, isolated behind the
``JiraClient`` protocol so tests inject a fake transport. Retries 429
and 5xx with exponential backoff plus jitter and honours Retry-After.
"""

from __future__ import annotations

import asyncio
import logging
import mimetypes
import random
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from types import TracebackType
from typing import Any, Literal, Protocol

import httpx

from comment2jira.config import Credentials

logger = logging.getLogger("comment2jira")

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

_JITTER = random.SystemRandom()


class JiraError(Exception):
    """Base error for comment2jira operations."""


class AuthError(JiraError):
    """Authentication failed (HTTP 401)."""


class NotFoundError(JiraError):
    """Issue not found or no permission (HTTP 403/404)."""


class DeprecatedEndpointError(JiraError):
    """Endpoint removed upstream (HTTP 410 Gone)."""


def package_version() -> str:
    """Version string used in the User-Agent header."""
    try:
        return version("comment2jira")
    except PackageNotFoundError:
        return "0.0.0"


@dataclass(frozen=True)
class AttachmentUploadResult:
    """Metadata returned by Jira after an attachment upload.

    Attributes:
        id: Attachment ID from Jira.
        filename: The filename under which Jira stored the attachment.
        content_url: Direct download URL for the attachment content.
    """

    id: str
    filename: str
    content_url: str


class JiraClient(Protocol):
    """Network boundary so tests can inject a fake."""

    async def check_auth(self) -> dict[str, Any]:
        """Hit /rest/api/2/myself to verify credentials."""
        ...

    async def get_server_info(self) -> dict[str, Any]:
        """Hit /rest/api/2/serverInfo for deployment detection."""
        ...

    async def post_comment(
        self,
        issue_key: str,
        body: str | dict[str, Any],
        *,
        deployment: Literal["dc", "cloud"] = "cloud",
    ) -> dict[str, Any]:
        """Post a comment to a Jira issue.

        Args:
            issue_key: Jira issue key (e.g. ``PROJ-123``).
            body: Wiki markup string (dc) or ADF dict (cloud).
            deployment: Target API version (``dc`` for api/2, ``cloud``
                for api/3).

        Returns:
            Decoded JSON response from the comment creation endpoint.
        """
        ...

    async def upload_attachment(
        self,
        issue_key: str,
        path: str,
        stored_name: str,
    ) -> AttachmentUploadResult:
        """Upload a local file as a Jira issue attachment.

        Args:
            issue_key: Jira issue key (e.g. ``PROJ-123``).
            path: Filesystem path to the file to upload.
            stored_name: Filename to send in the multipart field.

        Returns:
            Parsed metadata from the upload response.
        """
        ...

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        ...


class HttpxJiraClient:
    """Pooled httpx implementation of the JiraClient protocol."""

    def __init__(
        self,
        credentials: Credentials,
        *,
        timeout: float = 30.0,
        max_retries: int = 5,
        retry_delay_base: float = 0.5,
        verify: bool | str = True,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """Create the client.

        Args:
            credentials: Resolved credentials (URL, scheme, token).
            timeout: Per-request timeout in seconds.
            max_retries: Retry budget for 429/5xx responses.
            retry_delay_base: Base delay in seconds for backoff.
            verify: SSL verification flag or CA bundle path.
            transport: Injectable transport (tests use MockTransport).
        """
        self.credentials = credentials
        self.max_retries = max_retries
        self.retry_delay_base = retry_delay_base
        headers = {
            "Accept": "application/json",
            "User-Agent": f"comment2jira-api/{package_version()}",
            "Authorization": credentials.auth_header(),
        }
        self._client = httpx.AsyncClient(
            base_url=credentials.url,
            headers=headers,
            timeout=timeout,
            verify=verify,
            transport=transport,
        )

    @property
    def host(self) -> str:
        """Hostname of the Jira base URL."""
        return self.credentials.host

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        files: dict[str, tuple[str, bytes, str]] | None = None,
        headers: dict[str, str] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> Any:
        """Issue a request with retry and typed error mapping.

        Args:
            method: HTTP method (GET, POST, etc.).
            path: URL path relative to base_url.
            params: Query parameters.
            json_body: JSON body for application/json requests.
            files: Multipart file uploads as ``{field_name:
                (filename, data, content_type)}``.
            headers: Extra headers to merge (do not overwrite defaults).
            meta: Optional dict populated with response metadata.
        """
        transport_error: Exception | None = None
        req_headers = dict(self._client.headers)
        if headers:
            req_headers.update(headers)
        for attempt in range(self.max_retries + 1):
            try:
                if files is not None:
                    response = await self._client.request(
                        method,
                        path,
                        params=params,
                        files=files,
                        headers=req_headers,
                    )
                else:
                    response = await self._client.request(
                        method,
                        path,
                        params=params,
                        json=json_body,
                        headers=req_headers,
                    )
            except httpx.HTTPError as exc:
                transport_error = exc
                logger.debug("Transport error for %s %s: %s", method, path, exc)
                if attempt >= self.max_retries:
                    break
                await self._sleep_backoff(attempt, retry_after=None)
                continue
            if response.status_code in RETRYABLE_STATUS:
                if attempt >= self.max_retries:
                    msg = (
                        f"Jira request {method} {path} failed after "
                        f"{self.max_retries} retries "
                        f"(HTTP {response.status_code})"
                    )
                    raise JiraError(msg)
                logger.debug(
                    "Retryable HTTP %d for %s %s",
                    response.status_code,
                    method,
                    path,
                )
                await self._sleep_backoff(attempt, response.headers.get("Retry-After"))
                continue
            return self._finalise(response, method, path, meta=meta)
        msg = (
            f"Jira request {method} {path} failed after "
            f"{self.max_retries} retries: {transport_error}"
        )
        raise JiraError(msg)

    def _finalise(
        self,
        response: httpx.Response,
        method: str,
        path: str,
        *,
        meta: dict[str, Any] | None = None,
    ) -> Any:
        """Map status codes to typed errors and decode JSON."""
        status = response.status_code
        if status == 401:
            raise AuthError(
                self._error_message(response, f"Authentication failed for {method} {path}")
            )
        if status in (403, 404):
            raise NotFoundError(
                self._error_message(
                    response,
                    f"Not found or no permission for {method} {path}",
                )
            )
        if status == 410:
            raise DeprecatedEndpointError(
                self._error_message(response, f"Endpoint removed upstream: {method} {path}")
            )
        if status >= 400:
            raise JiraError(self._error_message(response, f"HTTP {status} for {method} {path}"))
        if meta is not None:
            meta["etag"] = response.headers.get("ETag")
        try:
            return response.json()
        except ValueError as exc:
            msg = f"Invalid JSON from {method} {path}"
            raise JiraError(msg) from exc

    @staticmethod
    def _error_message(response: httpx.Response, fallback: str) -> str:
        """Surface Jira errorMessages verbatim when present."""
        try:
            body = response.json()
        except ValueError:
            return fallback
        if not isinstance(body, dict):
            return fallback
        parts: list[str] = [fallback]
        messages = body.get("errorMessages")
        if isinstance(messages, list):
            parts.extend(str(message) for message in messages)
        errors = body.get("errors")
        if isinstance(errors, dict):
            parts.extend(f"{key}: {value}" for key, value in errors.items())
        if len(parts) == 1:
            return fallback
        return "; ".join(parts)

    async def _sleep_backoff(self, attempt: int, retry_after: str | None) -> None:
        """Sleep with exponential backoff, honouring Retry-After."""
        delay = self.retry_delay_base * (2**attempt) + _JITTER.uniform(0, 0.1)
        if retry_after is not None:
            try:
                delay = max(float(retry_after), 0.0)
            except ValueError:
                logger.debug("Ignoring unparsable Retry-After: %r", retry_after)
        logger.debug("Retrying in %.2fs (attempt %d)", delay, attempt + 1)
        await asyncio.sleep(delay)

    async def check_auth(self) -> dict[str, Any]:
        """Verify credentials via /rest/api/2/myself."""
        payload = await self._request("GET", "/rest/api/2/myself")
        return payload if isinstance(payload, dict) else {}

    async def get_server_info(self) -> dict[str, Any]:
        """Fetch /rest/api/2/serverInfo for deployment detection."""
        payload = await self._request("GET", "/rest/api/2/serverInfo")
        return payload if isinstance(payload, dict) else {}

    async def post_comment(
        self,
        issue_key: str,
        body: str | dict[str, Any],
        *,
        deployment: Literal["dc", "cloud"] = "cloud",
    ) -> dict[str, Any]:
        """Post a comment to a Jira issue.

        Args:
            issue_key: Jira issue key (e.g. ``PROJ-123``).
            body: Wiki markup string (dc) or ADF dict (cloud).
            deployment: Target API version (``dc`` for api/2, ``cloud``
                for api/3).

        Returns:
            Decoded JSON response from the comment creation endpoint.
        """
        if deployment == "dc":
            path = f"/rest/api/2/issue/{issue_key}/comment"
            json_body: dict[str, Any] = {"body": body}
        else:
            path = f"/rest/api/3/issue/{issue_key}/comment"
            json_body = {"body": body}
        payload = await self._request("POST", path, json_body=json_body)
        return payload if isinstance(payload, dict) else {}

    async def upload_attachment(
        self,
        issue_key: str,
        path: str,
        stored_name: str,
    ) -> AttachmentUploadResult:
        """Upload a local file as a Jira issue attachment.

        Sends ``POST /rest/api/2/issue/{key}/attachments`` as multipart
        form data with field name ``file`` and header
        ``X-Atlassian-Token: no-check``.  The file is read, uploaded, and
        closed within this method.

        Args:
            issue_key: Jira issue key (e.g. ``PROJ-123``).
            path: Filesystem path to the file to upload.
            stored_name: Filename to send in the multipart field.

        Returns:
            Parsed :class:`AttachmentUploadResult` with id, filename,
            and content URL from the first entry in Jira's response list.
        """
        content_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
        file_data = Path(path).read_bytes()
        files = {
            "file": (stored_name, file_data, content_type),
        }
        extra_headers = {"X-Atlassian-Token": "no-check"}
        resp_path = f"/rest/api/2/issue/{issue_key}/attachments"
        payload = await self._request(
            "POST",
            resp_path,
            files=files,
            headers=extra_headers,
        )
        # Jira returns a list of attachment entries; take the first.
        if isinstance(payload, list) and payload:
            entry = payload[0]
            return AttachmentUploadResult(
                id=str(entry.get("id", "")),
                filename=str(entry.get("filename", "")),
                content_url=str(entry.get("content", "")),
            )
        msg = f"Unexpected attachment upload response for {issue_key}: expected a non-empty list"
        raise JiraError(msg)

    async def aclose(self) -> None:
        """Close the pooled httpx client."""
        await self._client.aclose()

    async def __aenter__(self) -> HttpxJiraClient:
        """Enter the async context."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the client on context exit."""
        await self.aclose()
