"""Tests for md_to_adf (Markdown to ADF converter)."""

import pytest

from comment2jira.markup.md_to_adf import markdown_to_adf, verbatim_text_to_adf


@pytest.mark.unit
class TestDocumentStructure:
    """Top-level ADF document shape tests."""

    def test_version_and_type(self) -> None:
        doc = markdown_to_adf("hello")
        assert doc["version"] == 1
        assert doc["type"] == "doc"

    def test_content_is_list(self) -> None:
        doc = markdown_to_adf("hello")
        assert isinstance(doc["content"], list)

    def test_empty_string_has_paragraph(self) -> None:
        doc = markdown_to_adf("")
        assert len(doc["content"]) >= 1
        assert doc["content"][0]["type"] == "paragraph"


@pytest.mark.unit
class TestHeadings:
    """Heading node tests."""

    def test_h1_heading(self) -> None:
        doc = markdown_to_adf("# Title")
        para = doc["content"][0]
        assert para["type"] == "heading"
        assert para["attrs"]["level"] == 1

    def test_h3_heading(self) -> None:
        doc = markdown_to_adf("### Sub")
        para = doc["content"][0]
        assert para["type"] == "heading"
        assert para["attrs"]["level"] == 3


@pytest.mark.unit
class TestBoldItalic:
    """Inline formatting (bold/italic) tests."""

    def test_bold_produces_strong_mark(self) -> None:
        doc = markdown_to_adf("**bold**")
        text_node = doc["content"][0]["content"][0]
        assert text_node["type"] == "text"
        assert any(m["type"] == "strong" for m in text_node.get("marks", []))

    def test_italic_produces_em_mark(self) -> None:
        doc = markdown_to_adf("*italic*")
        text_node = doc["content"][0]["content"][0]
        assert text_node["type"] == "text"
        assert any(m["type"] == "em" for m in text_node.get("marks", []))


@pytest.mark.unit
class TestInlineCode:
    """Inline code node tests."""

    def test_inline_code_has_code_mark(self) -> None:
        doc = markdown_to_adf("`code`")
        text_node = doc["content"][0]["content"][0]
        assert text_node["type"] == "text"
        assert any(m["type"] == "code" for m in text_node.get("marks", []))


@pytest.mark.unit
class TestFencedCodeBlocks:
    """Fenced code block node tests."""

    def test_code_block_structure(self) -> None:
        doc = markdown_to_adf("```\nprint(1)\n```")
        cb = doc["content"][0]
        assert cb["type"] == "codeBlock"
        assert cb["content"][0]["text"] == "print(1)"

    def test_code_block_with_language(self) -> None:
        doc = markdown_to_adf("```python\nx = 1\n```")
        cb = doc["content"][0]
        assert cb["type"] == "codeBlock"
        assert cb["attrs"]["language"] == "python"


@pytest.mark.unit
class TestLists:
    """List node tests."""

    def test_bullet_list(self) -> None:
        doc = markdown_to_adf("- a\n- b")
        assert doc["content"][0]["type"] == "bulletList"
        items = doc["content"][0]["content"]
        assert len(items) == 2
        assert items[0]["type"] == "listItem"

    def test_ordered_list(self) -> None:
        doc = markdown_to_adf("1. first\n2. second")
        assert doc["content"][0]["type"] == "orderedList"
        items = doc["content"][0]["content"]
        assert len(items) == 2


@pytest.mark.unit
class TestLinks:
    """Link mark tests."""

    def test_link_has_href(self) -> None:
        doc = markdown_to_adf("[text](https://example.com)")
        text_node = doc["content"][0]["content"][0]
        link_marks = [m for m in text_node.get("marks", []) if m["type"] == "link"]
        assert len(link_marks) == 1
        assert link_marks[0]["attrs"]["href"] == "https://example.com"


@pytest.mark.unit
class TestTables:
    """Table node tests."""

    def test_table_structure(self) -> None:
        doc = markdown_to_adf("| A | B |\n|---|---|\n| 1 | 2 |")
        table = doc["content"][0]
        assert table["type"] == "table"
        assert "content" in table
        rows = table["content"]
        assert len(rows) == 2  # header + data row
        assert rows[0]["type"] == "tableRow"
        assert rows[0]["content"][0]["type"] == "tableHeader"
        assert rows[1]["content"][0]["type"] == "tableCell"


@pytest.mark.unit
class TestVerbatimWrapper:
    """verbatim_text_to_adf helper tests."""

    def test_document_shape(self) -> None:
        doc = verbatim_text_to_adf("plain")
        assert doc["version"] == 1
        assert doc["type"] == "doc"
        assert len(doc["content"]) == 1
        assert doc["content"][0]["type"] == "paragraph"

    def test_exact_text_preserved(self) -> None:
        original = "hello **world** `code` [link](url)"
        doc = verbatim_text_to_adf(original)
        text_node = doc["content"][0]["content"][0]
        assert text_node["text"] == original
        assert "marks" not in text_node  # no parsing applied

    def test_empty_string(self) -> None:
        doc = verbatim_text_to_adf("")
        text_node = doc["content"][0]["content"][0]
        assert text_node["text"] == ""

    def test_special_characters_unchanged(self) -> None:
        original = "<tag> & \"quotes' {curly}"
        doc = verbatim_text_to_adf(original)
        assert doc["content"][0]["content"][0]["text"] == original
