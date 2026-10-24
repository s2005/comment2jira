"""End-to-end CLI runs against the scratch issue named by JIRA_TEST_ISSUE.

Each test invokes the real Click command with real credentials and then
reads the issue back through the REST API, so a green test means Jira
actually holds the comment or attachment - not merely that the CLI exited
zero. No test prints a credential value.
"""

from __future__ import annotations

import struct
import uuid
import zlib
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from comment2jira.cli import EXIT_OK, main

pytestmark = pytest.mark.integration

# A 1x1 transparent PNG, small enough to inline and cheap to upload.
PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100ffff03000006000557bfabd400"
    "00000049454e44ae426082"
)


def solid_png(size: int = 64, rgb: tuple[int, int, int] = (220, 30, 30)) -> bytes:
    """Build an opaque single-colour PNG, so an inline render is visible by eye.

    The transparent ``PNG_BYTES`` proves an upload happened but renders as an
    empty box, which cannot be told apart from a missing image in the Jira UI.
    """

    def chunk(kind: bytes, data: bytes) -> bytes:
        payload = kind + data
        return struct.pack(">I", len(data)) + payload + struct.pack(">I", zlib.crc32(payload))

    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    row = b"\x00" + bytes(rgb) * size
    pixels = zlib.compress(row * size)
    return (
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", pixels) + chunk(b"IEND", b"")
    )


def unique_marker() -> str:
    """Return a token unique to one test run, used to find the comment again."""
    return f"comment2jira-it-{uuid.uuid4().hex[:12]}"


def comment_text(comment: dict[str, Any]) -> str:
    """Flatten a comment body to plain text for both api/2 and api/3 shapes.

    Server/DC returns wiki markup as a string; Cloud returns an ADF
    document, whose text lives in nested ``text`` keys.
    """
    body = comment.get("body")
    if isinstance(body, str):
        return body
    collected: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if isinstance(node.get("text"), str):
                collected.append(node["text"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(body)
    return " ".join(collected)


class TestTextMode:
    """AC-5: --text posts verbatim with no uploads."""

    def test_posts_text_verbatim(self, issue_key: str, latest_comment: Any) -> None:
        marker = unique_marker()
        result = CliRunner().invoke(
            main,
            ["--issue", issue_key, "--text", f"{marker} plain **not bold** text"],
        )
        assert result.exit_code == EXIT_OK, result.output

        posted = comment_text(latest_comment())
        assert marker in posted
        # Verbatim means the asterisks survive untouched by any converter.
        assert "**not bold**" in posted


class TestFileMode:
    """AC-2: --file converts Markdown for the detected deployment."""

    def test_posts_converted_markdown(
        self, tmp_path: Path, issue_key: str, latest_comment: Any
    ) -> None:
        marker = unique_marker()
        source = tmp_path / "comment.md"
        source.write_text(
            f"# {marker}\n\nA paragraph with **bold** text.\n\n- first\n- second\n",
            encoding="utf-8",
        )

        result = CliRunner().invoke(main, ["--issue", issue_key, "--file", str(source)])
        assert result.exit_code == EXIT_OK, result.output

        posted = comment_text(latest_comment())
        assert marker in posted
        assert "first" in posted
        # Markdown emphasis markers are consumed by the converter on both
        # deployments: wiki markup uses *bold*, ADF uses a mark on the node.
        assert "**bold**" not in posted


class TestAttachments:
    """AC-3, AC-4: local references upload and the body is rewritten."""

    def test_uploads_and_rewrites_reference(
        self,
        tmp_path: Path,
        issue_key: str,
        latest_comment: Any,
        attachment_filenames: Any,
    ) -> None:
        marker = unique_marker()
        image = tmp_path / f"{marker}.png"
        image.write_bytes(PNG_BYTES)
        source = tmp_path / "comment.md"
        source.write_text(f"{marker} shot:\n\n![screenshot]({image.name})\n", encoding="utf-8")

        before = attachment_filenames()
        result = CliRunner().invoke(main, ["--issue", issue_key, "--file", str(source)])
        assert result.exit_code == EXIT_OK, result.output

        after = attachment_filenames()
        assert image.name in after
        assert len(after) == len(before) + 1

        posted = comment_text(latest_comment())
        assert marker in posted
        # The original relative reference must not survive the rewrite.
        assert f"({image.name})" not in posted

    def test_missing_file_is_skipped_and_run_succeeds(
        self, tmp_path: Path, issue_key: str, latest_comment: Any, attachment_filenames: Any
    ) -> None:
        """AC-6: a reference to a missing file warns and does not fail the run."""
        marker = unique_marker()
        source = tmp_path / "comment.md"
        source.write_text(f"{marker}\n\n![gone](does-not-exist.png)\n", encoding="utf-8")

        before = attachment_filenames()
        result = CliRunner().invoke(main, ["--issue", issue_key, "--file", str(source)])
        assert result.exit_code == EXIT_OK, result.output

        assert attachment_filenames() == before
        assert marker in comment_text(latest_comment())


class TestDryRun:
    """AC-7: --dry-run performs no writes."""

    def test_dry_run_posts_nothing(
        self, tmp_path: Path, issue_key: str, jira_read: Any, attachment_filenames: Any
    ) -> None:
        marker = unique_marker()
        image = tmp_path / f"{marker}.png"
        image.write_bytes(PNG_BYTES)
        source = tmp_path / "comment.md"
        source.write_text(f"{marker}\n\n![shot]({image.name})\n", encoding="utf-8")

        def comment_count() -> int:
            payload = jira_read(f"/rest/api/2/issue/{issue_key}/comment", maxResults=0)
            return int(payload.get("total", 0))

        comments_before = comment_count()
        attachments_before = attachment_filenames()

        result = CliRunner().invoke(
            main, ["--issue", issue_key, "--file", str(source), "--dry-run"]
        )
        assert result.exit_code == EXIT_OK, result.output
        assert issue_key in result.output
        assert image.name in result.output

        assert comment_count() == comments_before
        assert attachment_filenames() == attachments_before


class TestErrorPaths:
    """The CLI reports live failures rather than exiting zero."""

    def test_unknown_issue_key_is_reported(self, tmp_path: Path) -> None:
        source = tmp_path / "comment.md"
        source.write_text("body\n", encoding="utf-8")
        result = CliRunner().invoke(
            main, ["--issue", "NOSUCHPROJECT-999999", "--file", str(source)]
        )
        assert result.exit_code != EXIT_OK
        assert "error:" in result.output


def adf_node_types(node: Any) -> set[str]:
    """Collect every ``type`` value found in an ADF document."""
    found: set[str] = set()
    if isinstance(node, dict):
        if isinstance(node.get("type"), str):
            found.add(node["type"])
        for value in node.values():
            found |= adf_node_types(value)
    elif isinstance(node, list):
        for value in node:
            found |= adf_node_types(value)
    return found


def adf_nodes(node: Any, node_type: str) -> list[dict[str, Any]]:
    """Collect every ADF node of *node_type* found beneath *node* (inclusive)."""
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        if node.get("type") == node_type:
            found.append(node)
        for value in node.values():
            found += adf_nodes(value, node_type)
    elif isinstance(node, list):
        for value in node:
            found += adf_nodes(value, node_type)
    return found


class TestWikiBodyFormat:
    """--body-format wiki embeds images inline instead of linking them."""

    def test_image_renders_inline_on_cloud(
        self,
        tmp_path: Path,
        issue_key: str,
        jira_read: Any,
        attachment_filenames: Any,
    ) -> None:
        server = jira_read("/rest/api/2/serverInfo")
        if server.get("deploymentType") != "Cloud":
            pytest.skip("inline-image check reads ADF, which only Jira Cloud serves")

        marker = unique_marker()
        image = tmp_path / f"{marker}.png"
        image.write_bytes(solid_png())
        source = tmp_path / "comment.md"
        source.write_text(f"{marker} inline:\n\n![shot]({image.name})\n", encoding="utf-8")

        result = CliRunner().invoke(
            main,
            ["--issue", issue_key, "--file", str(source), "--body-format", "wiki"],
        )
        assert result.exit_code == EXIT_OK, result.output
        assert image.name in attachment_filenames()

        # Read back through api/3: Jira converts the posted wiki markup to
        # ADF, and an inline image is stored as a media node, not a link.
        payload = jira_read(
            f"/rest/api/3/issue/{issue_key}/comment",
            orderBy="-created",
            maxResults=1,
        )
        comments = payload.get("comments") or []
        assert comments, f"no comments found on {issue_key}"
        body = comments[0].get("body")
        assert marker in comment_text(comments[0])
        types = adf_node_types(body)
        assert "media" in types, f"expected an inline media node, got {sorted(types)}"

    def test_loose_ordered_list_with_images_keeps_numbering(
        self,
        tmp_path: Path,
        issue_key: str,
        jira_read: Any,
    ) -> None:
        server = jira_read("/rest/api/2/serverInfo")
        if server.get("deploymentType") != "Cloud":
            pytest.skip("list-structure check reads ADF, which only Jira Cloud serves")

        marker = unique_marker()
        lines = [f"{marker} steps:", ""]
        for number, colour in enumerate([(220, 30, 30), (30, 220, 30), (30, 30, 220)], 1):
            image = tmp_path / f"{marker}-{number}.png"
            image.write_bytes(solid_png(rgb=colour))
            lines += [f"{number}. Step {number}", "", f"   ![shot{number}]({image.name})", ""]
        source = tmp_path / "comment.md"
        source.write_text("\n".join(lines), encoding="utf-8")

        result = CliRunner().invoke(
            main,
            ["--issue", issue_key, "--file", str(source), "--body-format", "wiki"],
        )
        assert result.exit_code == EXIT_OK, result.output

        payload = jira_read(
            f"/rest/api/3/issue/{issue_key}/comment",
            orderBy="-created",
            maxResults=1,
        )
        comments = payload.get("comments") or []
        assert comments, f"no comments found on {issue_key}"
        body = comments[0].get("body")
        assert marker in comment_text(comments[0])

        # One list of three items, each holding its image: a blank line in
        # the wiki markup would have produced three one-item lists.
        ordered = adf_nodes(body, "orderedList")
        assert len(ordered) == 1, f"expected one orderedList, got {len(ordered)}"
        items = [c for c in ordered[0].get("content", []) if c.get("type") == "listItem"]
        assert len(items) == 3, f"expected three listItem nodes, got {len(items)}"
        for item in items:
            assert adf_nodes(item, "media"), f"listItem has no media node: {item}"
