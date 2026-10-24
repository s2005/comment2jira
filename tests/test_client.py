"""Tests for the comment2jira httpx client (core + write methods)."""

from collections.abc import Callable

import httpx
import pytest

from comment2jira.client import (
    AttachmentUploadResult,
    AuthError,
    HttpxJiraClient,
    JiraError,
    NotFoundError,
)
from comment2jira.config import Credentials

Handler = Callable[[httpx.Request], httpx.Response]


def make_client(
    handler: Handler,
    *,
    credentials: Credentials | None = None,
    max_retries: int = 5,
) -> HttpxJiraClient:
    creds = credentials or Credentials(
        url="https://jira.example.com",
        email="user@example.com",
        token="dummy-token",
    )
    return HttpxJiraClient(
        creds,
        transport=httpx.MockTransport(handler),
        retry_delay_base=0.0,
        max_retries=max_retries,
    )


class TestMockTransportInjection:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_mock_transport_serves_response(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"displayName": "Alice"})

        async with make_client(handler) as client:
            result = await client.check_auth()
        assert result["displayName"] == "Alice"


class TestRetryPolicy:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_429_then_success(self) -> None:
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.path)
            if len(calls) == 1:
                return httpx.Response(429, headers={"Retry-After": "0"}, json={})
            return httpx.Response(200, json={"key": "ABC-1"})

        async with make_client(handler) as client:
            payload = await client.get_server_info()
        assert payload["key"] == "ABC-1"
        assert len(calls) == 2

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_500_exhausts_retries(self) -> None:
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.path)
            return httpx.Response(500, json={})

        async with make_client(handler, max_retries=2) as client:
            with pytest.raises(JiraError, match="failed after 2 retries"):
                await client.get_server_info()
        assert len(calls) == 3


class TestErrorMapping:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_401_raises_auth_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"errorMessages": ["Bad credentials"]})

        async with make_client(handler) as client:
            with pytest.raises(AuthError, match="Bad credentials"):
                await client.check_auth()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_404_raises_not_found(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"errorMessages": ["Issue does not exist"]})

        async with make_client(handler) as client:
            with pytest.raises(NotFoundError, match="Issue does not exist"):
                await client.get_server_info()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_403_raises_not_found(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, json={})

        async with make_client(handler) as client:
            with pytest.raises(NotFoundError):
                await client.get_server_info()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_invalid_json_body(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"<html>not json</html>", headers={})

        async with make_client(handler, max_retries=0) as client:
            with pytest.raises(JiraError, match="Invalid JSON"):
                await client.check_auth()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_non_dict_payload_returns_empty(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[])

        async with make_client(handler) as client:
            assert await client.get_server_info() == {}


class TestHeaders:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_basic_auth_header(self) -> None:
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["authorization"] = request.headers["Authorization"]
            return httpx.Response(200, json={})

        async with make_client(handler) as client:
            await client.check_auth()
        import base64

        expected = base64.b64encode(b"user@example.com:dummy-token").decode("ascii")
        assert seen["authorization"] == f"Basic {expected}"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_bearer_auth_header(self) -> None:
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["authorization"] = request.headers["Authorization"]
            return httpx.Response(200, json={})

        credentials = Credentials(url="https://jira.example.com", token="pat-token")
        async with make_client(handler, credentials=credentials) as client:
            await client.check_auth()
        assert seen["authorization"] == "Bearer pat-token"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_user_agent(self) -> None:
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["user-agent"] = request.headers["User-Agent"]
            return httpx.Response(200, json={})

        async with make_client(handler) as client:
            await client.check_auth()
        assert seen["user-agent"].startswith("comment2jira-api/")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_accept_json(self) -> None:
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["accept"] = request.headers["Accept"]
            return httpx.Response(200, json={})

        async with make_client(handler) as client:
            await client.check_auth()
        assert seen["accept"] == "application/json"


class TestHostProperty:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_host_property(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={})

        async with make_client(handler) as client:
            assert client.host == "jira.example.com"


class TestTransportErrors:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_transport_error_exhausts_retries(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom")

        async with make_client(handler, max_retries=1) as client:
            with pytest.raises(JiraError, match="failed after 1 retries"):
                await client.check_auth()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_unparsable_retry_after_is_ignored(self) -> None:
        calls: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            if len(calls) == 1:
                return httpx.Response(503, headers={"Retry-After": "not-a-number"}, json={})
            return httpx.Response(200, json={"key": "ABC-1"})

        async with make_client(handler, max_retries=1) as client:
            payload = await client.get_server_info()
        assert payload["key"] == "ABC-1"
        assert len(calls) == 2


class TestPostComment:
    """post_comment payload shapes and endpoint routing."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_dc_posts_wiki_body_to_api2(self) -> None:
        recorded: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            recorded["method"] = request.method
            recorded["path"] = request.url.path
            recorded["body"] = request.content
            # Return a minimal comment response.
            return httpx.Response(
                201,
                json={
                    "id": "10001",
                    "body": "wiki text",
                    "self": "https://jira/rest/api/2/issue/PROJ-1/comment/10001",
                },
            )

        async with make_client(handler) as client:
            result = await client.post_comment("PROJ-1", "**bold** text", deployment="dc")

        assert recorded["method"] == "POST"
        assert recorded["path"] == "/rest/api/2/issue/PROJ-1/comment"
        import json

        parsed = json.loads(recorded["body"])  # type: ignore[arg-type]
        assert parsed == {"body": "**bold** text"}
        assert result["id"] == "10001"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_cloud_posts_adf_to_api3(self) -> None:
        recorded: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            recorded["method"] = request.method
            recorded["path"] = request.url.path
            recorded["body"] = request.content
            return httpx.Response(
                201,
                json={
                    "id": "10002",
                    "body": {"version": 1, "type": "doc", "content": []},
                    "self": "https://jira/rest/api/3/issue/PROJ-2/comment/10002",
                },
            )

        adf_body: dict[str, object] = {
            "version": 1,
            "type": "doc",
            "content": [{"type": "paragraph", "content": []}],
        }
        async with make_client(handler) as client:
            result = await client.post_comment("PROJ-2", adf_body, deployment="cloud")

        assert recorded["method"] == "POST"
        assert recorded["path"] == "/rest/api/3/issue/PROJ-2/comment"
        import json

        parsed = json.loads(recorded["body"])  # type: ignore[arg-type]
        assert parsed["body"] == adf_body
        assert result["id"] == "10002"


class TestUploadAttachment:
    """upload_attachment multipart construction and response parsing."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_upload_method_and_endpoint(self, tmp_path: pytest.TempPathFactory) -> None:
        recorded: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            recorded["method"] = request.method
            recorded["path"] = request.url.path
            recorded["headers"] = dict(request.headers)
            # Return standard Jira attachment response (list).
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "20001",
                        "filename": "report.pdf",
                        "self": "https://jira/rest/api/2/attachment/20001",
                        "content": "https://jira/secure/attachment/20001/report.pdf",
                    }
                ],
            )

        f = tmp_path / "report.pdf"
        f.write_bytes(b"%PDF-1.4 dummy")
        async with make_client(handler) as client:
            await client.upload_attachment("PROJ-3", str(f), "report.pdf")

        assert recorded["method"] == "POST"
        assert recorded["path"] == "/rest/api/2/issue/PROJ-3/attachments"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_multipart_content_type(self, tmp_path: pytest.TempPathFactory) -> None:
        content_type_value: str | None = None

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal content_type_value
            content_type_value = request.headers.get("Content-Type")
            return httpx.Response(
                200,
                json=[{"id": "1", "filename": "f.png", "content": "https://jira/c/1/f.png"}],
            )

        f = tmp_path / "f.png"
        f.write_bytes(b"\x89PNG\r\n\x1a\n")
        async with make_client(handler) as client:
            await client.upload_attachment("PROJ-1", str(f), "f.png")

        assert content_type_value is not None
        assert "multipart/form-data" in content_type_value

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_x_atlassian_token_header(self, tmp_path: pytest.TempPathFactory) -> None:
        token_value: str | None = None

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal token_value
            token_value = request.headers.get("X-Atlassian-Token")
            return httpx.Response(
                200,
                json=[{"id": "1", "filename": "f.txt", "content": "https://jira/c/1/f.txt"}],
            )

        f = tmp_path / "f.txt"
        f.write_bytes(b"hello")
        async with make_client(handler) as client:
            await client.upload_attachment("PROJ-1", str(f), "f.txt")

        assert token_value == "no-check"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_stored_filename_in_multipart(self, tmp_path: pytest.TempPathFactory) -> None:
        body_bytes: bytes = b""

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal body_bytes
            body_bytes = request.content
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "1",
                        "filename=": "renamed.pdf",
                        "content": "https://jira/c/1/renamed.pdf",
                    }
                ],
            )

        f = tmp_path / "original.pdf"
        f.write_bytes(b"%PDF")
        async with make_client(handler) as client:
            await client.upload_attachment("PROJ-1", str(f), "renamed.pdf")

        # The stored filename should appear in the multipart body.
        assert b"renamed.pdf" in body_bytes

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_response_parsing(self, tmp_path: pytest.TempPathFactory) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "99999",
                        "filename": "uploaded-name.png",
                        "content": "https://jira.example.com/secure/attachment/99999/uploaded-name.png",
                    }
                ],
            )

        f = tmp_path / "local.png"
        f.write_bytes(b"\x89PNG")
        async with make_client(handler) as client:
            result = await client.upload_attachment("PROJ-10", str(f), "uploaded-name.png")

        assert isinstance(result, AttachmentUploadResult)
        assert result.id == "99999"
        assert result.filename == "uploaded-name.png"
        assert (
            result.content_url
            == "https://jira.example.com/secure/attachment/99999/uploaded-name.png"
        )

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_file_closed_after_upload(self, tmp_path: pytest.TempPathFactory) -> None:
        """The file should be read and closed within the method."""
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(
                200,
                json=[{"id": "1", "filename": "f.bin", "content": "https://jira/c/1/f.bin"}],
            )

        f = tmp_path / "f.bin"
        f.write_bytes(b"\x00\x01\x02")
        async with make_client(handler) as client:
            result = await client.upload_attachment("PROJ-1", str(f), "f.bin")

        assert call_count == 1
        assert result.filename == "f.bin"
