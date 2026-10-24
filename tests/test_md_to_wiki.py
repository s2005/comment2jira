"""Tests for md_to_wiki (Markdown to Jira wiki markup)."""

import pytest

from comment2jira.markup.md_to_wiki import markdown_to_jira


@pytest.mark.unit
class TestHeadings:
    """Heading conversion tests."""

    def test_atx_heading_h1(self) -> None:
        assert markdown_to_jira("# Title") == "h1. Title"

    def test_atx_heading_h3(self) -> None:
        assert markdown_to_jira("### Subsection") == "h3. Subsection"

    def test_setext_heading_h1(self) -> None:
        assert markdown_to_jira("Title\n=====") == "h1. Title"

    def test_setext_heading_h2(self) -> None:
        assert markdown_to_jira("Subtitle\n-----") == "h2. Subtitle"


@pytest.mark.unit
class TestBoldItalic:
    """Bold and italic conversion tests."""

    def test_bold(self) -> None:
        assert markdown_to_jira("**bold**") == "*bold*"

    def test_italic(self) -> None:
        assert markdown_to_jira("*italic*") == "_italic_"

    def test_bold_italic_combined(self) -> None:
        result = markdown_to_jira("**bold** and *italic*")
        assert result == "*bold* and _italic_"

    def test_list_line_not_treated_as_formatting(self) -> None:
        """Asterisk+space is Jira list syntax, not bold/italic."""
        result = markdown_to_jira("* item")
        assert "* item" in result


@pytest.mark.unit
class TestInlineCode:
    """Inline code conversion tests."""

    def test_inline_code(self) -> None:
        assert markdown_to_jira("`code`") == "{{code}}"

    def test_inline_code_preserves_content(self) -> None:
        assert markdown_to_jira("`var_name`") == "{{var_name}}"


@pytest.mark.unit
class TestFencedCodeBlocks:
    """Fenced code block conversion tests."""

    def test_code_block_no_language(self) -> None:
        md = "```\nprint('hello')\n```"
        result = markdown_to_jira(md)
        assert "{code}" in result
        assert "print('hello')" in result

    def test_code_block_with_python(self) -> None:
        md = "```python\nx = 1\n```"
        result = markdown_to_jira(md)
        assert "{code:python}" in result
        assert "x = 1" in result

    def test_code_block_unknown_language_falls_back(self) -> None:
        md = "```rust\nfn main() {}\n```"
        result = markdown_to_jira(md)
        assert "{code}" in result
        assert "{code:rust}" not in result
        assert "fn main() {}" in result

    def test_code_block_language_mapping(self) -> None:
        """TypeScript maps to javascript per LANGUAGE_MAPPING."""
        md = "```typescript\nconst x: number = 1;\n```"
        result = markdown_to_jira(md)
        assert "{code:javascript}" in result


@pytest.mark.unit
class TestLists:
    """List conversion tests."""

    def test_unordered_list(self) -> None:
        result = markdown_to_jira("- first\n- second")
        assert "* first" in result
        assert "* second" in result

    def test_ordered_list(self) -> None:
        result = markdown_to_jira("1. first\n2. second")
        assert "# first" in result
        assert "# second" in result

    def test_indented_nested_list(self) -> None:
        result = markdown_to_jira("  - nested")
        assert "** nested" in result


@pytest.mark.unit
class TestLooseLists:
    """Loose lists keep continuation blocks inside their list item."""

    def test_loose_ordered_list_with_images(self) -> None:
        md = (
            "After:\n\n"
            "1. Search of CI\n\n"
            "   ![a.png](a.png)\n\n"
            "2. Tooltip -\n\n"
            "   ![b.png](b.png)\n\n"
            "3. Location in `Shipment Paperwork` group\n\n"
            "   ![c.png](c.png)"
        )
        # The blank line before a list is swallowed by the list regexes (unchanged).
        assert markdown_to_jira(md) == (
            "After:\n"
            "# Search of CI \\\\ !a.png|alt=a.png!\n"
            "# Tooltip - \\\\ !b.png|alt=b.png!\n"
            "# Location in {{Shipment Paperwork}} group \\\\ !c.png|alt=c.png!"
        )

    def test_loose_unordered_list(self) -> None:
        md = "- first\n\n  ![x](x.png)\n\n- second\n\n  more text"
        assert markdown_to_jira(md) == "* first \\\\ !x.png|alt=x!\n* second \\\\ more text"

    def test_loose_list_without_continuation_stays_one_list(self) -> None:
        assert markdown_to_jira("1. a\n\n2. b\n\n3. c") == "# a\n# b\n# c"

    def test_nested_loose_list(self) -> None:
        md = "1. a\n\n   ![x](x.png)\n\n   - sub\n\n     ![y](y.png)\n\n   - sub2\n\n2. b"
        assert markdown_to_jira(md) == (
            "# a \\\\ !x.png|alt=x!\n** sub \\\\ !y.png|alt=y!\n** sub2\n# b"
        )

    def test_item_with_two_continuation_paragraphs(self) -> None:
        md = "1. a\n\n   first para\n\n   second para\n\n2. b"
        assert markdown_to_jira(md) == "# a \\\\ first para \\\\ second para\n# b"

    def test_wrapped_continuation_paragraph_joined_with_space(self) -> None:
        md = "1. a\n\n   line one\n   line two\n\n2. b"
        assert markdown_to_jira(md) == "# a \\\\ line one line two\n# b"

    def test_tight_list_unchanged(self) -> None:
        md = "1. a\n2. b\n   - c\n   - d\n3. e\n\nafter"
        assert markdown_to_jira(md) == "# a\n# b\n** c\n** d\n# e\n\nafter"

    def test_blank_line_after_list_kept(self) -> None:
        assert markdown_to_jira("- a\n- b\n\nend") == "* a\n* b\n\nend"

    def test_fenced_code_in_item_keeps_current_behaviour(self) -> None:
        """A code block cannot sit on one list line; the item is left as is."""
        result = markdown_to_jira("1. a\n\n   ```\nx\n   ```\n\n2. b")
        assert "\\\\" not in result
        assert "# a\n\n" in result
        assert "{code}" in result


@pytest.mark.unit
class TestLinks:
    """Link conversion tests."""

    def test_link_with_text(self) -> None:
        assert markdown_to_jira("[Jira](https://example.com)") == "[Jira|https://example.com]"

    def test_bare_url(self) -> None:
        assert markdown_to_jira("<https://example.com>") == "[https://example.com]"


@pytest.mark.unit
class TestImages:
    """Image reference conversion tests."""

    def test_image_without_alt(self) -> None:
        result = markdown_to_jira("![](img.png)")
        assert "!img.png!" in result

    def test_image_with_alt(self) -> None:
        result = markdown_to_jira("![photo](img.png)")
        assert "!img.png|" in result
        assert "alt=photo" in result


@pytest.mark.unit
class TestTables:
    """Table conversion tests."""

    def test_simple_table(self) -> None:
        md = "| A | B |\n|---|---|\n| 1 | 2 |"
        result = markdown_to_jira(md)
        assert "|| A || B ||" in result
        assert "|---|---|" not in result  # separator removed


@pytest.mark.unit
class TestEdgeCases:
    """Edge case and boundary tests."""

    def test_empty_string(self) -> None:
        assert markdown_to_jira("") == ""

    def test_strikethrough(self) -> None:
        assert markdown_to_jira("~~deleted~~") == "-deleted-"


@pytest.mark.unit
class TestExtractRestoreBlocks:
    """Block extraction/restoration round-trip tests."""

    def test_code_block_protected_from_header_conversion(self) -> None:
        """Code containing # should not become a heading."""
        md = "```\n# not a heading\n```"
        result = markdown_to_jira(md)
        assert "h1." not in result
        assert "# not a heading" in result

    def test_inline_code_protected_from_formatting(self) -> None:
        """Inline code with asterisks should stay as inline code."""
        result = markdown_to_jira("`**not bold**`")
        assert "{{**not bold**}}" in result
        # The raw *bold* markup must NOT appear outside the inline-code wrapper
        assert result.strip() == "{{**not bold**}}"
