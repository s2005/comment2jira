"""Markdown to Atlassian Document Format (ADF) converter.

Copyright (c) 2024 Hyeonsoo Lee
Licensed under the MIT License.
Source: mcp-atlassian project
  - src/mcp_atlassian/models/jira/adf.py (markdown_to_adf)

Extracted and adapted as a dependency-free module (stdlib only).
"""

import re
from typing import Any


def _parse_inline_formatting(text: str) -> list[dict[str, Any]]:
    """Parse inline Markdown formatting into ADF inline nodes.

    Handles: bold (**), italic (*), inline code (`), links ([text](url)),
    strikethrough (~~), and Jira-flavored user mentions
    ([~accountid:ACCOUNT_ID]).

    The mention syntax mirrors what Jira's v2 wiki text returns when a real
    ADF mention is read back, so the read and write paths are symmetric.

    Args:
        text: Raw text potentially containing inline Markdown formatting.

    Returns:
        List of ADF inline nodes (text nodes with optional marks, plus
        mention nodes when [~accountid:...] is present).
    """
    if not text:
        return []

    nodes: list[dict[str, Any]] = []
    # Pattern order matters: mention before link (both start with `[`),
    # bold before italic, code before others
    inline_re = re.compile(
        r"\[~accountid:(?P<mention_id>[^\]]+)\]"
        r"|`(?P<code_inner>[^`]+)`"
        r"|\*\*(?P<bold_inner>.+?)\*\*"
        r"|~~(?P<strike_inner>.+?)~~"
        r"|\[(?P<link_text>[^\]]+)\]\((?P<link_href>[^)]+)\)"
        r"|(?<!\*)\*(?!\*)(?P<italic_inner>.+?)(?<!\*)\*(?!\*)"
    )

    pos = 0
    for m in inline_re.finditer(text):
        # Add any plain text before this match
        if m.start() > pos:
            plain = text[pos : m.start()]
            if plain:
                nodes.append({"type": "text", "text": plain})

        if m.group("mention_id") is not None:
            nodes.append(
                {
                    "type": "mention",
                    "attrs": {"id": m.group("mention_id")},
                }
            )
        elif m.group("code_inner") is not None:
            nodes.append(
                {
                    "type": "text",
                    "text": m.group("code_inner"),
                    "marks": [{"type": "code"}],
                }
            )
        elif m.group("bold_inner") is not None:
            nodes.append(
                {
                    "type": "text",
                    "text": m.group("bold_inner"),
                    "marks": [{"type": "strong"}],
                }
            )
        elif m.group("strike_inner") is not None:
            nodes.append(
                {
                    "type": "text",
                    "text": m.group("strike_inner"),
                    "marks": [{"type": "strike"}],
                }
            )
        elif m.group("link_text") is not None:
            nodes.append(
                {
                    "type": "text",
                    "text": m.group("link_text"),
                    "marks": [
                        {
                            "type": "link",
                            "attrs": {"href": m.group("link_href")},
                        }
                    ],
                }
            )
        elif m.group("italic_inner") is not None:
            nodes.append(
                {
                    "type": "text",
                    "text": m.group("italic_inner"),
                    "marks": [{"type": "em"}],
                }
            )

        pos = m.end()

    # Remaining plain text after last match
    if pos < len(text):
        remaining = text[pos:]
        if remaining:
            nodes.append({"type": "text", "text": remaining})

    # If no patterns matched, return the whole thing as plain text
    if not nodes and text:
        nodes.append({"type": "text", "text": text})

    return nodes


def _make_paragraph(text: str) -> dict[str, Any]:
    """Create an ADF paragraph node from text with inline formatting."""
    content = _parse_inline_formatting(text)
    if not content:
        content = [{"type": "text", "text": ""}]
    return {"type": "paragraph", "content": content}


def _make_list_item(text: str) -> dict[str, Any]:
    """Create an ADF listItem node wrapping a paragraph."""
    return {"type": "listItem", "content": [_make_paragraph(text)]}


def _make_task_item(text: str, checked: bool, local_id: str) -> dict[str, Any]:
    """Create an ADF taskItem node."""
    return {
        "type": "taskItem",
        "attrs": {"localId": local_id, "state": "DONE" if checked else "TODO"},
        "content": _parse_inline_formatting(text) or [{"type": "text", "text": text}],
    }


def markdown_to_adf(markdown_text: str) -> dict[str, Any]:
    """Convert Markdown text to ADF (Atlassian Document Format) document.

    Implements a line-by-line parser that handles common Markdown constructs.
    No external dependencies required.

    Args:
        markdown_text: Markdown-formatted text to convert.

    Returns:
        ADF document dict with version, type, and content keys.
    """
    doc: dict[str, Any] = {"version": 1, "type": "doc", "content": []}

    if not markdown_text:
        doc["content"].append({"type": "paragraph", "content": []})
        return doc

    lines = markdown_text.split("\n")
    i = 0

    while i < len(lines):
        line = lines[i]

        # --- Fenced code block ---
        if line.startswith("```"):
            lang = line[3:].strip()
            code_lines: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                code_lines.append(lines[i])
                i += 1
            # Skip closing ```
            if i < len(lines):
                i += 1
            cb: dict[str, Any] = {
                "type": "codeBlock",
                "attrs": {"language": lang} if lang else {},
                "content": [{"type": "text", "text": "\n".join(code_lines)}],
            }
            doc["content"].append(cb)
            continue

        # --- Horizontal rule ---
        stripped = line.strip()
        is_hr = stripped in ("---", "***", "___") or (
            len(stripped) >= 3 and all(c == stripped[0] for c in stripped) and stripped[0] in "-*_"
        )
        if is_hr and not line.startswith("- ") and not line.startswith("* "):
            doc["content"].append({"type": "rule"})
            i += 1
            continue

        # --- Heading ---
        heading_match = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading_match:
            level = len(heading_match.group(1))
            text = heading_match.group(2)
            heading_node: dict[str, Any] = {
                "type": "heading",
                "attrs": {"level": level},
                "content": _parse_inline_formatting(text),
            }
            doc["content"].append(heading_node)
            i += 1
            continue

        # --- Blockquote ---
        if line.startswith("> "):
            quote_lines: list[str] = []
            while i < len(lines) and lines[i].startswith("> "):
                quote_lines.append(lines[i][2:])
                i += 1
            bq_content = [_make_paragraph(ln) for ln in quote_lines]
            doc["content"].append({"type": "blockquote", "content": bq_content})
            continue

        # --- Task list (- [ ] / - [x]) ---
        if re.match(r"^[-*]\s+\[[ xX]\]\s+", line):
            task_items: list[dict[str, Any]] = []
            task_counter = 0
            while i < len(lines) and re.match(r"^[-*]\s+\[[ xX]\]\s+", lines[i]):
                checked = bool(re.match(r"^[-*]\s+\[[xX]\]\s+", lines[i]))
                item_text = re.sub(r"^[-*]\s+\[[ xX]\]\s+", "", lines[i])
                task_counter += 1
                task_items.append(
                    _make_task_item(item_text, checked, f"task-{id(doc)}-{task_counter}")
                )
                i += 1
            doc["content"].append(
                {
                    "type": "taskList",
                    "attrs": {"localId": f"tasklist-{id(doc)}-{i}"},
                    "content": task_items,
                }
            )
            continue

        # --- Panel block ---
        panel_match = re.match(r"^:::(\w+)\s*$", line)
        if panel_match:
            panel_type = panel_match.group(1).lower()
            valid_panel_types = {"note", "info", "warning", "success", "error"}
            if panel_type in valid_panel_types:
                panel_lines: list[str] = []
                i += 1
                while i < len(lines) and lines[i].strip() != ":::":
                    panel_lines.append(lines[i])
                    i += 1
                # Skip closing :::
                if i < len(lines):
                    i += 1
                # Recursively parse panel content
                inner_doc = markdown_to_adf("\n".join(panel_lines))
                panel_node: dict[str, Any] = {
                    "type": "panel",
                    "attrs": {"panelType": panel_type},
                    "content": inner_doc["content"],
                }
                doc["content"].append(panel_node)
                continue

        # --- Unordered list ---
        if re.match(r"^[-*]\s+", line):
            items: list[dict[str, Any]] = []
            while i < len(lines) and re.match(r"^[-*]\s+", lines[i]):
                item_text = re.sub(r"^[-*]\s+", "", lines[i])
                items.append(_make_list_item(item_text))
                i += 1
            doc["content"].append({"type": "bulletList", "content": items})
            continue

        # --- Ordered list ---
        if re.match(r"^\d+\.\s+", line):
            items_ol: list[dict[str, Any]] = []
            while i < len(lines) and re.match(r"^\d+\.\s+", lines[i]):
                item_text = re.sub(r"^\d+\.\s+", "", lines[i])
                items_ol.append(_make_list_item(item_text))
                i += 1
            doc["content"].append({"type": "orderedList", "content": items_ol})
            continue

        # --- Table ---
        if line.startswith("|") and "|" in line[1:]:
            table_rows: list[str] = []
            while i < len(lines) and lines[i].startswith("|"):
                table_rows.append(lines[i])
                i += 1

            # Parse rows, skip separator (|---|---|)
            data_rows: list[list[str]] = []
            for row_line in table_rows:
                cells = [c.strip() for c in row_line.strip("|").split("|")]
                if all(re.match(r"^:?-+:?$", c) for c in cells if c):
                    continue
                data_rows.append(cells)

            if data_rows:
                adf_rows: list[dict[str, Any]] = []
                for idx, cells in enumerate(data_rows):
                    cell_type = "tableHeader" if idx == 0 else "tableCell"
                    adf_cells = []
                    for cell_text in cells:
                        content = _parse_inline_formatting(cell_text)
                        if not content:
                            content = [{"type": "text", "text": ""}]
                        adf_cells.append(
                            {
                                "type": cell_type,
                                "content": [{"type": "paragraph", "content": content}],
                            }
                        )
                    adf_rows.append({"type": "tableRow", "content": adf_cells})

                doc["content"].append(
                    {
                        "type": "table",
                        "attrs": {"isNumberColumnEnabled": False, "layout": "default"},
                        "content": adf_rows,
                    }
                )
            continue

        # --- Empty line (skip) ---
        if not stripped:
            i += 1
            continue

        # --- Paragraph (default) ---
        doc["content"].append(_make_paragraph(line))
        i += 1

    # Ensure at least one content node
    if not doc["content"]:
        doc["content"].append({"type": "paragraph", "content": []})

    return doc


def verbatim_text_to_adf(text: str) -> dict[str, Any]:
    """Wrap raw text in a single-paragraph ADF document without transformation.

    Produces ``{"version": 1, "type": "doc", "content": [paragraph]}`` where
    the paragraph contains exactly one text node holding *text* unchanged.
    This mirrors mcp-atlassian's fallback pattern for plain-text input.

    Args:
        text: Raw string to embed verbatim.

    Returns:
        A minimal ADF document with one paragraph containing the exact text.
    """
    return {
        "version": 1,
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": text}],
            }
        ],
    }
