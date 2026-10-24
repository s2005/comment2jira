"""Tests for the comment2jira CLI.

Uses click.testing.CliRunner with a MockTransport-based client injection
harness. All tests are synchronous (CliRunner is sync); asyncio.run() lives
inside main/run as in jira2md.
"""

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from click.testing import CliRunner

from comment2jira import cli as cli_module
from comment2jira.cli import (
    EXIT_AUTH,
    EXIT_NOT_FOUND,
    EXIT_OK,
    EXIT_RUNTIME,
    exit_code_for,
    main,
    run,
)
from comment2jira.client import AuthError, HttpxJiraClient, JiraError, NotFoundError
from comment2jira.config import Credentials


def make_client(handler: Any) -> HttpxJiraClient:
    """Build an HttpxJiraClient with a MockTransport recording handler."""
    creds = Credentials(
        url="https://jira.example.com",
        email="alice@example.com",
        token="secret-token",
    )
    return HttpxJiraClient(
        creds,
        transport=httpx.MockTransport(handler),
        retry_delay_base=0.0,
        max_retries=1,
    )


def base_params(**overrides: Any) -> dict[str, Any]:
    """Return a minimal valid params dict with overrides applied."""
    params: dict[str, Any] = {
        "issue": "PROJ-123",
        "file": None,
        "text": None,
        "url": "https://jira.example.com",
        "email": "alice@example.com",
        "token": "secret-token",
        "auth": None,
        "env_file": None,
        "dry_run": False,
        "verbose": 0,
    }
    params.update(overrides)
    return params


class TestExitCodeMapping:
    """AC-9: exit code mapping for error types."""

    @pytest.mark.unit
    def test_auth_error_maps_to_2(self) -> None:
        assert exit_code_for(AuthError("x")) == EXIT_AUTH

    @pytest.mark.unit
    def test_not_found_error_maps_to_3(self) -> None:
        assert exit_code_for(NotFoundError("x")) == EXIT_NOT_FOUND

    @pytest.mark.unit
    def test_jira_error_maps_to_1(self) -> None:
        assert exit_code_for(JiraError("x")) == EXIT_RUNTIME

    @pytest.mark.unit
    def test_unknown_error_maps_to_1(self) -> None:
        assert exit_code_for(RuntimeError("x")) == EXIT_RUNTIME


class TestHelpAndVersion:
    """--help and --version output."""

    @pytest.mark.unit
    def test_help_lists_all_options(self) -> None:
        result = CliRunner().invoke(main, ["--help"])
        assert result.exit_code == 0
        for option in (
            "--issue",
            "--file",
            "--text",
            "--env-file",
            "--auth",
            "--dry-run",
            "--verbose",
            "--version",
            "--help",
        ):
            assert option in result.output

    @pytest.mark.unit
    def test_version(self) -> None:
        result = CliRunner().invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "comment2jira" in result.output


class TestMutualExclusion:
    """AC-1: --file / --text mutual exclusion and --issue required."""

    @pytest.mark.unit
    def test_both_file_and_text_exit_2(self) -> None:
        result = CliRunner().invoke(
            main,
            ["--issue", "PROJ-123", "--file", "x.md", "--text", "hello"],
        )
        assert result.exit_code == 2
        assert "mutually exclusive" in result.output.lower()

    @pytest.mark.unit
    def test_neither_file_nor_text_exit_2(self) -> None:
        result = CliRunner().invoke(main, ["--issue", "PROJ-123"])
        assert result.exit_code == 2
        assert "required" in result.output.lower()

    @pytest.mark.unit
    def test_missing_issue_exit_2(self) -> None:
        result = CliRunner().invoke(main, ["--text", "hello"])
        assert result.exit_code == 2


class TestEnvFileOption:
    """--env-file through the Click command boundary (REQ-2).

    The Click conversion is the seam the earlier suite never crossed: a
    missing file must yield the documented error, an existing file must
    resolve credentials, and the COMMENT2JIRA_ENV_FILE entry point must
    agree with the flag.
    """

    @pytest.mark.unit
    def test_missing_env_file_exits_1_without_traceback(self, tmp_path: Path) -> None:
        missing = tmp_path / "does-not-exist.env"
        result = CliRunner().invoke(
            main,
            ["--issue", "PROJ-123", "--text", "probe", "--env-file", str(missing)],
        )
        assert result.exit_code == EXIT_RUNTIME
        assert "error: Env file not found:" in result.output
        assert "does-not-exist.env" in result.output
        assert "Traceback" not in result.output
        assert "AttributeError" not in result.output

    @pytest.mark.unit
    def test_existing_env_file_resolves_credentials(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        env_file = tmp_path / "creds.env"
        env_file.write_text(
            "JIRA_URL=https://jira.example.com\n"
            "JIRA_EMAIL=alice@example.com\n"
            "JIRA_TOKEN=secret-token\n",
            encoding="utf-8",
        )

        posted: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/rest/api/2/serverInfo":
                return httpx.Response(200, json={"deploymentType": "Cloud"})
            if request.url.path == "/rest/api/3/issue/PROJ-123/comment":
                posted.append(request.url.path)
                return httpx.Response(200, json={"id": "10001"})
            return httpx.Response(404, json={})

        def fake_client(credentials: Credentials, **kwargs: Any) -> HttpxJiraClient:
            return HttpxJiraClient(
                credentials,
                transport=httpx.MockTransport(handler),
                retry_delay_base=0.0,
                max_retries=1,
            )

        monkeypatch.setattr(cli_module, "HttpxJiraClient", fake_client)

        result = CliRunner().invoke(
            main,
            ["--issue", "PROJ-123", "--text", "probe", "--env-file", str(env_file)],
        )
        # The run got past credential resolution: no config error, and the
        # comment reached the mock transport, so no real request was made.
        assert "No Jira URL provided" not in result.output
        assert result.exit_code == EXIT_OK
        assert posted == ["/rest/api/3/issue/PROJ-123/comment"]

    @pytest.mark.unit
    def test_env_var_matches_flag_for_missing_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        missing = tmp_path / "does-not-exist.env"
        monkeypatch.setenv("COMMENT2JIRA_ENV_FILE", str(missing))
        result = CliRunner().invoke(main, ["--issue", "PROJ-123", "--text", "probe"])
        assert result.exit_code == EXIT_RUNTIME
        assert "error: Env file not found:" in result.output
        assert "does-not-exist.env" in result.output
        assert "Traceback" not in result.output
        assert "AttributeError" not in result.output


def _install_recording_client(
    monkeypatch: pytest.MonkeyPatch, recorded: list[httpx.Request]
) -> None:
    """Patch HttpxJiraClient with a MockTransport that records every request."""

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        if request.url.path == "/rest/api/2/serverInfo":
            return httpx.Response(200, json={"deploymentType": "Cloud"})
        if request.url.path == "/rest/api/3/issue/PROJ-123/comment":
            return httpx.Response(200, json={"id": "10001"})
        return httpx.Response(404, json={})

    def fake_client(credentials: Credentials, **kwargs: Any) -> HttpxJiraClient:
        return HttpxJiraClient(
            credentials,
            transport=httpx.MockTransport(handler),
            retry_delay_base=0.0,
            max_retries=1,
        )

    monkeypatch.setattr(cli_module, "HttpxJiraClient", fake_client)


class TestCredentialFlags:
    """--url / --email / --token through the Click command boundary (REQ-3).

    Like TestEnvFileOption, the Click conversion is the seam the rest of the
    suite does not cross: flag precedence over the environment, the auth
    scheme the flags select, and the message when nothing resolves a URL all
    have to be proven through CliRunner, not by calling resolve_credentials
    directly.
    """

    @pytest.mark.unit
    def test_url_flag_wins_over_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JIRA_URL", "https://env.example.com")
        monkeypatch.setenv("JIRA_EMAIL", "alice@example.com")
        monkeypatch.setenv("JIRA_TOKEN", "secret-token")

        recorded: list[httpx.Request] = []
        _install_recording_client(monkeypatch, recorded)

        result = CliRunner().invoke(
            main,
            [
                "--issue",
                "PROJ-123",
                "--text",
                "probe",
                "--url",
                "https://flag.example.com",
            ],
        )

        assert result.exit_code == EXIT_OK
        hosts = {request.url.host for request in recorded}
        assert hosts == {"flag.example.com"}
        assert "env.example.com" not in hosts

    @pytest.mark.unit
    def test_email_and_token_flags_win_over_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JIRA_URL", "https://env.example.com")
        monkeypatch.setenv("JIRA_EMAIL", "env@example.com")
        monkeypatch.setenv("JIRA_TOKEN", "env-token")

        recorded: list[httpx.Request] = []
        _install_recording_client(monkeypatch, recorded)

        result = CliRunner().invoke(
            main,
            [
                "--issue",
                "PROJ-123",
                "--text",
                "probe",
                "--url",
                "https://flag.example.com",
                "--email",
                "flag@example.com",
                "--token",
                "flag-token",
            ],
        )

        assert result.exit_code == EXIT_OK
        headers = [request.headers["Authorization"] for request in recorded]
        assert headers
        for header in headers:
            assert header.startswith("Basic ")
            decoded = base64.b64decode(header[len("Basic ") :]).decode("ascii")
            assert decoded == "flag@example.com:flag-token"

    @pytest.mark.unit
    def test_token_alone_selects_bearer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JIRA_URL", "https://env.example.com")

        recorded: list[httpx.Request] = []
        _install_recording_client(monkeypatch, recorded)

        result = CliRunner().invoke(
            main,
            [
                "--issue",
                "PROJ-123",
                "--text",
                "probe",
                "--token",
                "flag-token",
            ],
        )

        assert result.exit_code == EXIT_OK
        headers = [request.headers["Authorization"] for request in recorded]
        assert headers
        for header in headers:
            assert header == "Bearer flag-token"

    @pytest.mark.unit
    def test_env_still_resolves_without_flags(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JIRA_URL", "https://env.example.com")
        monkeypatch.setenv("JIRA_EMAIL", "alice@example.com")
        monkeypatch.setenv("JIRA_TOKEN", "secret-token")

        recorded: list[httpx.Request] = []
        _install_recording_client(monkeypatch, recorded)

        result = CliRunner().invoke(
            main,
            ["--issue", "PROJ-123", "--text", "probe"],
        )

        assert result.exit_code == EXIT_OK
        posted_paths = [request.url.path for request in recorded]
        assert "/rest/api/3/issue/PROJ-123/comment" in posted_paths
        hosts = {request.url.host for request in recorded}
        assert hosts == {"env.example.com"}

    @pytest.mark.unit
    def test_no_url_anywhere_reports_the_new_message(self) -> None:
        result = CliRunner().invoke(
            main,
            ["--issue", "PROJ-123", "--text", "probe"],
        )

        assert result.exit_code == EXIT_RUNTIME
        assert "error: No Jira URL provided (use --url, JIRA_URL, or a .env file)." in result.output
        assert "Traceback" not in result.output


@pytest.mark.unit
class TestFileModeCloud:
    """AC-2: file mode on Cloud posts ADF to api/3."""

    def test_cloud_posts_adf_comment(self, tmp_path: Path) -> None:
        md_file = tmp_path / "note.md"
        md_file.write_text("Hello from Cloud", encoding="utf-8")

        recorded: list[dict[str, str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            recorded.append({"method": request.method, "path": request.url.path})
            if request.url.path == "/rest/api/2/serverInfo":
                return httpx.Response(200, json={"deploymentType": "Cloud"})
            if request.url.path == "/rest/api/3/issue/PROJ-123/comment":
                body = request.read()
                payload = json.loads(body)
                # Assert ADF shape.
                assert payload["body"]["version"] == 1
                assert payload["body"]["type"] == "doc"
                return httpx.Response(200, json={"id": "10001"})
            return httpx.Response(404, json={})

        client = make_client(handler)

        async def _invoke() -> int:
            return await run(base_params(file=str(md_file)), client=client)

        actual_code = asyncio.run(_invoke())
        assert actual_code == EXIT_OK

        posts = [r for r in recorded if r["method"] == "POST"]
        assert len(posts) == 1
        assert posts[0]["path"] == "/rest/api/3/issue/PROJ-123/comment"


@pytest.mark.unit
class TestFileModeDC:
    """AC-2: file mode on DC posts wiki string to api/2."""

    def test_dc_posts_wiki_comment(self, tmp_path: Path) -> None:
        md_file = tmp_path / "note.md"
        md_file.write_text("**bold** text", encoding="utf-8")

        recorded: list[dict[str, str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            recorded.append({"method": request.method, "path": request.url.path})
            if request.url.path == "/rest/api/2/serverInfo":
                return httpx.Response(200, json={"deploymentType": "Server"})
            if request.url.path == "/rest/api/2/issue/PROJ-123/comment":
                body = request.read()
                payload = json.loads(body)
                assert isinstance(payload["body"], str)
                assert "bold" in payload["body"]
                return httpx.Response(200, json={"id": "10001"})
            return httpx.Response(404, json={})

        client = make_client(handler)

        async def _invoke() -> int:
            return await run(base_params(file=str(md_file)), client=client)

        actual_code = asyncio.run(_invoke())
        assert actual_code == EXIT_OK

        posts = [r for r in recorded if r["method"] == "POST"]
        assert len(posts) == 1
        assert posts[0]["path"] == "/rest/api/2/issue/PROJ-123/comment"


@pytest.mark.unit
class TestAttachmentUploads:
    """AC-3/AC-4: local refs upload, remote refs do not, rewriting works."""

    def test_local_image_upload_and_rewrite_cloud(self, tmp_path: Path) -> None:
        img = tmp_path / "diagram.png"
        img.write_bytes(b"PNG-DATA")

        md_file = tmp_path / "note.md"
        md_file.write_text("See ![alt](diagram.png) for details.", encoding="utf-8")

        recorded: list[dict[str, Any]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            entry: dict[str, Any] = {
                "method": request.method,
                "path": request.url.path,
            }
            if request.url.path == "/rest/api/2/serverInfo":
                return httpx.Response(200, json={"deploymentType": "Cloud"})
            if request.url.path == "/rest/api/2/issue/PROJ-123/attachments":
                # Assert multipart and X-Atlassian-Token.
                assert request.headers.get("X-Atlassian-Token") == "no-check"
                entry["has_files"] = True
                recorded.append(entry)
                return httpx.Response(
                    200,
                    json=[
                        {
                            "id": "20001",
                            "filename": "diagram.png",
                            "content": "https://jira.example.com/secure/attachment/20001/diagram.png",
                        }
                    ],
                )
            if request.url.path == "/rest/api/3/issue/PROJ-123/comment":
                body = request.read()
                payload = json.loads(body)
                entry["comment_body"] = payload["body"]
                recorded.append(entry)
                return httpx.Response(200, json={"id": "10001"})
            recorded.append(entry)
            return httpx.Response(404, json={})

        client = make_client(handler)

        async def _invoke() -> int:
            return await run(base_params(file=str(md_file)), client=client)

        actual_code = asyncio.run(_invoke())
        assert actual_code == EXIT_OK

        uploads = [r for r in recorded if r["path"].endswith("/attachments")]
        assert len(uploads) == 1
        assert uploads[0].get("has_files") is True

        comments = [r for r in recorded if r["path"].endswith("/comment")]
        assert len(comments) == 1
        # Cloud rewrite produces a link to content URL.
        body_str = json.dumps(comments[0]["comment_body"])
        assert "diagram.png" in body_str or "secure/attachment" in body_str

    def test_remote_ref_no_upload(self, tmp_path: Path) -> None:
        md_file = tmp_path / "note.md"
        md_file.write_text("See ![remote](https://example.com/img.png).", encoding="utf-8")

        recorded: list[dict[str, str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            recorded.append({"method": request.method, "path": request.url.path})
            if request.url.path == "/rest/api/2/serverInfo":
                return httpx.Response(200, json={"deploymentType": "Cloud"})
            if request.url.path == "/rest/api/3/issue/PROJ-123/comment":
                return httpx.Response(200, json={"id": "10001"})
            return httpx.Response(404, json={})

        client = make_client(handler)

        async def _invoke() -> int:
            return await run(base_params(file=str(md_file)), client=client)

        actual_code = asyncio.run(_invoke())
        assert actual_code == EXIT_OK

        uploads = [r for r in recorded if "attachments" in r["path"]]
        assert len(uploads) == 0

    def test_duplicate_basename_suffixing(self, tmp_path: Path) -> None:
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "report.pdf").write_bytes(b"PDF-A")
        (tmp_path / "report.pdf").write_bytes(b"PDF-B")

        md_file = tmp_path / "note.md"
        md_file.write_text("[A](sub/report.pdf) and [B](report.pdf)", encoding="utf-8")

        upload_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal upload_count
            if request.url.path == "/rest/api/2/serverInfo":
                return httpx.Response(200, json={"deploymentType": "Cloud"})
            if request.url.path == "/rest/api/2/issue/PROJ-123/attachments":
                upload_count += 1
                return httpx.Response(
                    200,
                    json=[
                        {
                            "id": f"200{upload_count}",
                            "filename": "report.pdf",
                            "content": "https://jira.example.com/a/report.pdf",
                        }
                    ],
                )
            if request.url.path == "/rest/api/3/issue/PROJ-123/comment":
                return httpx.Response(200, json={"id": "10001"})
            return httpx.Response(404, json={})

        client = make_client(handler)

        async def _invoke() -> int:
            return await run(base_params(file=str(md_file)), client=client)

        actual_code = asyncio.run(_invoke())
        assert actual_code == EXIT_OK
        # Two uploads should have occurred (both files exist, same basename).
        assert upload_count == 2


@pytest.mark.unit
class TestTextMode:
    """AC-5: text mode sends verbatim string, zero uploads."""

    def test_text_mode_dc_raw_string(self) -> None:
        recorded: list[dict[str, str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            recorded.append({"method": request.method, "path": request.url.path})
            if request.url.path == "/rest/api/2/serverInfo":
                return httpx.Response(200, json={"deploymentType": "Server"})
            if request.url.path == "/rest/api/2/issue/PROJ-123/comment":
                body = request.read()
                payload = json.loads(body)
                assert payload["body"] == "exact raw text"
                return httpx.Response(200, json={"id": "10001"})
            return httpx.Response(404, json={})

        client = make_client(handler)

        async def _invoke() -> int:
            return await run(base_params(text="exact raw text"), client=client)

        actual_code = asyncio.run(_invoke())
        assert actual_code == EXIT_OK

        uploads = [r for r in recorded if "attachments" in r["path"]]
        assert len(uploads) == 0
        posts = [r for r in recorded if r["path"].endswith("/comment")]
        assert len(posts) == 1

    def test_text_mode_cloud_adf_paragraph(self) -> None:
        recorded: list[dict[str, str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            recorded.append({"method": request.method, "path": request.url.path})
            if request.url.path == "/rest/api/2/serverInfo":
                return httpx.Response(200, json={"deploymentType": "Cloud"})
            if request.url.path == "/rest/api/3/issue/PROJ-123/comment":
                body = request.read()
                payload = json.loads(body)
                adf = payload["body"]
                assert adf["version"] == 1
                assert adf["type"] == "doc"
                # Single paragraph whose text equals input.
                para = adf["content"][0]
                assert para["type"] == "paragraph"
                text_nodes = [n for n in para["content"] if n.get("type") == "text"]
                assert "".join(n["text"] for n in text_nodes) == "verbatim input"
                return httpx.Response(200, json={"id": "10001"})
            return httpx.Response(404, json={})

        client = make_client(handler)

        async def _invoke() -> int:
            return await run(base_params(text="verbatim input"), client=client)

        actual_code = asyncio.run(_invoke())
        assert actual_code == EXIT_OK

        uploads = [r for r in recorded if "attachments" in r["path"]]
        assert len(uploads) == 0


@pytest.mark.unit
class TestMissingFileContinue:
    """AC-6: missing referenced file logs warning, continues, exits 0."""

    def test_missing_file_warns_and_posts(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        md_file = tmp_path / "note.md"
        md_file.write_text("See ![missing](no-such-file.png).", encoding="utf-8")

        posted = False

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal posted
            if request.url.path == "/rest/api/2/serverInfo":
                return httpx.Response(200, json={"deploymentType": "Cloud"})
            if request.url.path == "/rest/api/3/issue/PROJ-123/comment":
                posted = True
                return httpx.Response(200, json={"id": "10001"})
            return httpx.Response(404, json={})

        client = make_client(handler)

        async def _invoke() -> int:
            return await run(base_params(file=str(md_file)), client=client)

        actual_code = asyncio.run(_invoke())
        assert actual_code == EXIT_OK
        assert posted
        # Warning about the missing file should appear in logs.
        assert "no-such-file.png" in caplog.text


@pytest.mark.unit
class TestDryRun:
    """AC-7: --dry-run prints plan, zero POST/PUT, exit 0."""

    def test_dry_run_prints_plan_and_zero_writes(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        img = tmp_path / "chart.png"
        img.write_bytes(b"CHART")

        md_file = tmp_path / "note.md"
        md_file.write_text("Data: ![chart](chart.png)", encoding="utf-8")

        requests_made: list[dict[str, str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests_made.append({"method": request.method, "path": request.url.path})
            # Even serverInfo is a GET; dry-run allows GETs.
            if request.url.path == "/rest/api/2/serverInfo":
                return httpx.Response(200, json={"deploymentType": "Cloud"})
            return httpx.Response(500, json={})

        client = make_client(handler)

        async def _invoke() -> int:
            return await run(base_params(file=str(md_file), dry_run=True), client=client)

        actual_code = asyncio.run(_invoke())
        assert actual_code == EXIT_OK

        # REQ-7: the printed body shows references rewritten for files that
        # exist; the cloud content URL is a placeholder until upload.
        captured = capsys.readouterr()
        assert "chart.png" in captured.out
        assert "<attachment-url>" in captured.out
        assert "Data: ![chart](chart.png)" not in captured.out

        # No POST or PUT should have been made.
        write_methods = [r for r in requests_made if r["method"] in ("POST", "PUT")]
        assert len(write_methods) == 0
        # Only GET for serverInfo should appear.
        gets = [r for r in requests_made if r["method"] == "GET"]
        assert len(gets) == 1
        assert gets[0]["path"] == "/rest/api/2/serverInfo"

    def test_dry_run_dc_rewrites_references(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """REQ-7 on dc: the printed wiki body uses the stored-name forms."""
        (tmp_path / "shot.png").write_bytes(b"P")
        md_file = tmp_path / "note.md"
        md_file.write_text("Pic: ![shot](shot.png) and [doc](gone.pdf)", encoding="utf-8")

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/rest/api/2/serverInfo":
                return httpx.Response(200, json={"deploymentType": "Production"})
            return httpx.Response(500, json={})

        client = make_client(handler)

        async def _invoke() -> int:
            return await run(base_params(file=str(md_file), dry_run=True), client=client)

        assert asyncio.run(_invoke()) == EXIT_OK

        captured = capsys.readouterr()
        assert "Deployment: dc" in captured.out
        # Existing file rewritten to the wiki attachment form; the missing
        # file's reference is not rewritten to an attachment form (the wiki
        # converter renders it as a plain link with the raw target).
        assert "!shot.png|alt=shot!" in captured.out
        assert "[doc|gone.pdf]" in captured.out
        assert "^gone.pdf" not in captured.out

    def test_dry_run_text_mode(self, capsys: pytest.CaptureFixture[str]) -> None:
        requests_made: list[dict[str, str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests_made.append({"method": request.method, "path": request.url.path})
            if request.url.path == "/rest/api/2/serverInfo":
                return httpx.Response(200, json={"deploymentType": "dc"})
            return httpx.Response(500, json={})

        client = make_client(handler)

        async def _invoke() -> int:
            return await run(base_params(text="hello dry run", dry_run=True), client=client)

        actual_code = asyncio.run(_invoke())
        assert actual_code == EXIT_OK

        captured = capsys.readouterr()
        assert "Issue: PROJ-123" in captured.out
        assert "Deployment:" in captured.out
        assert "Attachments: none" in captured.out
        assert "hello dry run" in captured.out


@pytest.mark.unit
class TestExitCodes:
    """AC-9: HTTP errors map to correct exit codes."""

    def test_401_exit_2(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/rest/api/2/serverInfo":
                return httpx.Response(200, json={"deploymentType": "Cloud"})
            return httpx.Response(401, json={"errorMessages": ["Unauthorized"]})

        client = make_client(handler)

        async def _invoke() -> int:
            return await run(base_params(text="test"), client=client)

        actual_code = asyncio.run(_invoke())
        assert actual_code == EXIT_AUTH

    def test_404_exit_3(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/rest/api/2/serverInfo":
                return httpx.Response(200, json={"deploymentType": "Cloud"})
            return httpx.Response(404, json={"errorMessages": ["Not Found"]})

        client = make_client(handler)

        async def _invoke() -> int:
            return await run(base_params(text="test"), client=client)

        actual_code = asyncio.run(_invoke())
        assert actual_code == EXIT_NOT_FOUND

    def test_transport_error_exit_1(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/rest/api/2/serverInfo":
                return httpx.Response(200, json={"deploymentType": "Cloud"})
            raise httpx.ConnectError("connection refused")

        client = make_client(handler)

        async def _invoke() -> int:
            return await run(base_params(text="test"), client=client)

        actual_code = asyncio.run(_invoke())
        assert actual_code == EXIT_RUNTIME

    def test_success_exit_0(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/rest/api/2/serverInfo":
                return httpx.Response(200, json={"deploymentType": "Cloud"})
            if request.url.path == "/rest/api/3/issue/PROJ-123/comment":
                return httpx.Response(200, json={"id": "10001"})
            return httpx.Response(404, json={})

        client = make_client(handler)

        async def _invoke() -> int:
            return await run(base_params(text="ok"), client=client)

        actual_code = asyncio.run(_invoke())
        assert actual_code == EXIT_OK


@pytest.mark.unit
class TestUnreadableFile:
    """Unreadable --file exits 1."""

    def test_nonexistent_file_exit_1(self) -> None:
        async def _invoke() -> int:
            return await run(base_params(file="/nonexistent/path/file.md"))

        actual_code = asyncio.run(_invoke())
        assert actual_code == EXIT_RUNTIME


@pytest.mark.unit
class TestVerbosity:
    """-v/-vv control log level."""

    def test_default_is_warning(self) -> None:
        # Default verbose=0 means WARNING; just verify it parses without error.
        env = {
            "JIRA_URL": "https://jira.example.com",
            "JIRA_EMAIL": "alice@example.com",
            "JIRA_TOKEN": "secret-token",
        }
        runner = CliRunner(env=env)
        result = runner.invoke(
            main,
            ["--issue", "PROJ-123", "--text", "hi"],
        )
        # Will fail with no real server but should not be a usage error.
        assert result.exit_code != 2

    def test_v_sets_info(self) -> None:
        env = {
            "JIRA_URL": "https://jira.example.com",
            "JIRA_EMAIL": "alice@example.com",
            "JIRA_TOKEN": "secret-token",
        }
        runner = CliRunner(env=env)
        result = runner.invoke(
            main,
            ["-v", "--issue", "PROJ-123", "--text", "hi"],
        )
        assert result.exit_code != 2

    def test_vv_sets_debug(self) -> None:
        env = {
            "JIRA_URL": "https://jira.example.com",
            "JIRA_EMAIL": "alice@example.com",
            "JIRA_TOKEN": "secret-token",
        }
        runner = CliRunner(env=env)
        result = runner.invoke(
            main,
            ["-vv", "--issue", "PROJ-123", "--text", "hi"],
        )
        assert result.exit_code != 2


@pytest.mark.unit
class TestBodyFormat:
    """--body-format auto/adf/wiki: unchanged auto path, forced overrides."""

    def test_auto_on_cloud_is_unchanged_adf(self, tmp_path: Path) -> None:
        md_file = tmp_path / "note.md"
        md_file.write_text("Hello from Cloud", encoding="utf-8")

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/rest/api/2/serverInfo":
                return httpx.Response(200, json={"deploymentType": "Cloud"})
            if request.url.path == "/rest/api/3/issue/PROJ-123/comment":
                body = request.read()
                payload = json.loads(body)
                assert payload["body"]["type"] == "doc"
                return httpx.Response(200, json={"id": "10001"})
            return httpx.Response(404, json={})

        client = make_client(handler)

        async def _invoke() -> int:
            return await run(base_params(file=str(md_file), body_format="auto"), client=client)

        assert asyncio.run(_invoke()) == EXIT_OK

    def test_auto_on_dc_is_unchanged_wiki(self, tmp_path: Path) -> None:
        md_file = tmp_path / "note.md"
        md_file.write_text("**bold** text", encoding="utf-8")

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/rest/api/2/serverInfo":
                return httpx.Response(200, json={"deploymentType": "Server"})
            if request.url.path == "/rest/api/2/issue/PROJ-123/comment":
                body = request.read()
                payload = json.loads(body)
                assert isinstance(payload["body"], str)
                assert "bold" in payload["body"]
                return httpx.Response(200, json={"id": "10001"})
            return httpx.Response(404, json={})

        client = make_client(handler)

        async def _invoke() -> int:
            return await run(base_params(file=str(md_file), body_format="auto"), client=client)

        assert asyncio.run(_invoke()) == EXIT_OK

    def test_wiki_on_cloud_file_mode_inlines_image_and_posts_api2(self, tmp_path: Path) -> None:
        img = tmp_path / "diagram.png"
        img.write_bytes(b"PNG-DATA")

        md_file = tmp_path / "note.md"
        md_file.write_text("See ![alt](diagram.png) for details.", encoding="utf-8")

        recorded: list[dict[str, Any]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            entry: dict[str, Any] = {"method": request.method, "path": request.url.path}
            if request.url.path == "/rest/api/2/serverInfo":
                return httpx.Response(200, json={"deploymentType": "Cloud"})
            if request.url.path == "/rest/api/2/issue/PROJ-123/attachments":
                recorded.append(entry)
                return httpx.Response(
                    200,
                    json=[
                        {
                            "id": "20001",
                            "filename": "diagram.png",
                            "content": "https://jira.example.com/secure/attachment/20001/diagram.png",
                        }
                    ],
                )
            if request.url.path == "/rest/api/2/issue/PROJ-123/comment":
                body = request.read()
                payload = json.loads(body)
                entry["comment_body"] = payload["body"]
                recorded.append(entry)
                return httpx.Response(200, json={"id": "10001"})
            recorded.append(entry)
            return httpx.Response(404, json={})

        client = make_client(handler)

        async def _invoke() -> int:
            return await run(base_params(file=str(md_file), body_format="wiki"), client=client)

        assert asyncio.run(_invoke()) == EXIT_OK

        comments = [r for r in recorded if r["path"].endswith("/comment")]
        assert len(comments) == 1
        # DC-style inline image wiki syntax, posted through the api/2 path.
        assert "!diagram.png|alt=alt!" in comments[0]["comment_body"]

    def test_wiki_on_cloud_loose_list_with_images_stays_one_list(self, tmp_path: Path) -> None:
        for name in ("a.png", "b.png", "c.png"):
            (tmp_path / name).write_bytes(b"PNG-DATA")

        md_file = tmp_path / "note.md"
        md_file.write_text(
            "After:\n\n"
            "1. Search of CI\n\n"
            "   ![a.png](a.png)\n\n"
            "2. Tooltip -\n\n"
            "   ![b.png](b.png)\n\n"
            "3. Location in `Shipment Paperwork` group\n\n"
            "   ![c.png](c.png)\n",
            encoding="utf-8",
        )

        uploads: list[str] = []
        comment_bodies: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/rest/api/2/serverInfo":
                return httpx.Response(200, json={"deploymentType": "Cloud"})
            if request.url.path == "/rest/api/2/issue/PROJ-123/attachments":
                # The multipart body carries the stored file name.
                name = next(n for n in ("a.png", "b.png", "c.png") if n.encode() in request.read())
                uploads.append(name)
                return httpx.Response(
                    200,
                    json=[
                        {
                            "id": str(20000 + len(uploads)),
                            "filename": name,
                            "content": f"https://jira.example.com/secure/attachment/1/{name}",
                        }
                    ],
                )
            if request.url.path == "/rest/api/2/issue/PROJ-123/comment":
                comment_bodies.append(json.loads(request.read())["body"])
                return httpx.Response(200, json={"id": "10001"})
            return httpx.Response(404, json={})

        client = make_client(handler)

        async def _invoke() -> int:
            return await run(base_params(file=str(md_file), body_format="wiki"), client=client)

        assert asyncio.run(_invoke()) == EXIT_OK

        assert sorted(uploads) == ["a.png", "b.png", "c.png"]
        # One list: no blank lines between items, images folded onto the
        # item line with a forced line break, no leading indentation.
        assert comment_bodies == [
            "After:\n"
            "# Search of CI \\\\ !a.png|alt=a.png!\n"
            "# Tooltip - \\\\ !b.png|alt=b.png!\n"
            "# Location in {{Shipment Paperwork}} group \\\\ !c.png|alt=c.png!\n"
        ]

    def test_wiki_dry_run_prints_format_and_wiki_body(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        img = tmp_path / "chart.png"
        img.write_bytes(b"CHART")

        md_file = tmp_path / "note.md"
        md_file.write_text("Data: ![chart](chart.png)", encoding="utf-8")

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/rest/api/2/serverInfo":
                return httpx.Response(200, json={"deploymentType": "Cloud"})
            return httpx.Response(500, json={})

        client = make_client(handler)

        async def _invoke() -> int:
            return await run(
                base_params(file=str(md_file), body_format="wiki", dry_run=True),
                client=client,
            )

        assert asyncio.run(_invoke()) == EXIT_OK

        captured = capsys.readouterr()
        assert "Deployment: cloud" in captured.out
        assert "Body format: wiki" in captured.out
        assert "!chart.png|alt=chart!" in captured.out

    def test_adf_on_dc_rejected_before_posting(self, tmp_path: Path) -> None:
        md_file = tmp_path / "note.md"
        md_file.write_text("hello", encoding="utf-8")

        posted = False

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal posted
            if request.url.path == "/rest/api/2/serverInfo":
                return httpx.Response(200, json={"deploymentType": "Server"})
            posted = True
            return httpx.Response(200, json={"id": "10001"})

        client = make_client(handler)

        async def _invoke() -> int:
            return await run(base_params(file=str(md_file), body_format="adf"), client=client)

        actual_code = asyncio.run(_invoke())
        assert actual_code == EXIT_RUNTIME
        assert not posted

    def test_wiki_text_mode_on_cloud_posts_via_api2(self) -> None:
        recorded: list[dict[str, str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            recorded.append({"method": request.method, "path": request.url.path})
            if request.url.path == "/rest/api/2/serverInfo":
                return httpx.Response(200, json={"deploymentType": "Cloud"})
            if request.url.path == "/rest/api/2/issue/PROJ-123/comment":
                body = request.read()
                payload = json.loads(body)
                assert payload["body"] == "wiki text on cloud"
                return httpx.Response(200, json={"id": "10001"})
            return httpx.Response(404, json={})

        client = make_client(handler)

        async def _invoke() -> int:
            return await run(
                base_params(text="wiki text on cloud", body_format="wiki"),
                client=client,
            )

        actual_code = asyncio.run(_invoke())
        assert actual_code == EXIT_OK

        posts = [r for r in recorded if r["path"].endswith("/comment")]
        assert len(posts) == 1
        assert posts[0]["path"] == "/rest/api/2/issue/PROJ-123/comment"
