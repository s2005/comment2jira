"""Markdown to Jira wiki markup converter.

Copyright (c) 2024 Hyeonsoo Lee
Licensed under the MIT License.
Source: mcp-atlassian project
  - src/mcp_atlassian/preprocessing/jira.py (markdown_to_jira)
  - src/mcp_atlassian/preprocessing/base.py (_extract_blocks, _restore_blocks)

Extracted and adapted as a dependency-free module (stdlib only).
"""

import re
from collections.abc import Callable

# Step 1: Valid JIRA languages (official list)
# Source: https://jira.atlassian.com/browse/JRASERVER-21067 (JIRA 7.5.0+)
# and JIRA v9.12.12 release notes
# Official documentation: https://jira.atlassian.com/secure/WikiRendererHelpAction.jspa
VALID_JIRA_LANGUAGES: set[str] = {
    # Core languages from JIRA 7.5.0+
    "actionscript",
    "actionscript3",
    "ada",
    "applescript",
    "bash",
    "sh",  # alias for bash
    "c",
    "c#",
    "csharp",  # alias for c#
    "cs",  # alias for c#
    "c++",
    "cpp",  # alias for c++
    "css",
    "sass",  # CSS preprocessor
    "less",  # CSS preprocessor
    "coldfusion",
    "delphi",
    "diff",
    "patch",  # alias for diff
    "erlang",
    "erl",  # alias for erlang
    "go",
    "groovy",
    "haskell",
    "html",
    "xml",
    "java",
    "javafx",
    "javascript",
    "js",  # alias for javascript
    "json",
    "lua",
    "nyan",
    "objc",
    "objective-c",  # alias for objc
    "perl",
    "php",
    "powershell",
    "ps1",  # alias for powershell
    "python",
    "py",  # alias for python
    "r",
    "rainbow",
    "ruby",
    "rb",  # alias for ruby
    "scala",
    "sql",
    "swift",
    "visualbasic",
    "vb",  # alias for visualbasic
    "yaml",
    "yml",  # alias for yaml
    "none",  # plain text, no highlighting
}

# Step 2: Mapping for unsupported languages to closest valid JIRA alternative
# Only map to actual JIRA languages; unmapped languages will return None -> {code}
LANGUAGE_MAPPING: dict[str, str] = {
    # Dockerfile -> bash (similar shell syntax)
    "dockerfile": "bash",
    "docker": "bash",
    # TypeScript -> javascript
    "typescript": "javascript",
    "ts": "javascript",
    "tsx": "javascript",
    # JSX/React -> javascript
    "jsx": "javascript",
    # Kotlin -> java (JVM-based language)
    "kotlin": "java",
    "kt": "java",
    # Build files -> bash
    "makefile": "bash",
    "make": "bash",
    "cmake": "bash",
}


def _normalize_code_language(lang: str | None) -> str | None:
    """Normalize and map markdown code language to JIRA-supported language.

    Step 3: Default handling - unmapped languages return None for plain {code}

    Args:
        lang: Language identifier from markdown code block

    Returns:
        Valid JIRA language string, or None for plain {code} block
    """
    if not lang:
        return None

    lang_lower = lang.lower()

    # Step 1: Check if already valid JIRA language
    if lang_lower in VALID_JIRA_LANGUAGES:
        return lang_lower

    # Step 2: Check language mapping
    if lang_lower in LANGUAGE_MAPPING:
        return LANGUAGE_MAPPING[lang_lower]

    # Step 3: Default - unmapped language returns None for plain {code}
    return None


def _extract_blocks(
    text: str,
    pattern: str,
    transform_fn: Callable[[re.Match[str]], str],
    storage: list[str],
    prefix: str,
    flags: int = 0,
) -> str:
    """Extract blocks matching pattern, transform, store, and replace with placeholders.

    Args:
        text: Input text to process.
        pattern: Regex pattern to match blocks.
        transform_fn: Function to transform the match into the target format.
        storage: List to store transformed blocks.
        prefix: Placeholder prefix (e.g., "CODEBLOCK").
        flags: Regex flags to pass to ``re.sub``.

    Returns:
        Text with blocks replaced by placeholders.
    """

    def _replacer(match: re.Match[str]) -> str:
        transformed = transform_fn(match)
        placeholder = f"\x00{prefix}{len(storage)}\x00"
        storage.append(transformed)
        return placeholder

    return re.sub(pattern, _replacer, text, flags=flags)


def _restore_blocks(text: str, storage: list[str], prefix: str) -> str:
    """Restore blocks from placeholders.

    Replaces in reverse order (highest index first) to avoid
    index collisions when placeholder text contains digits.

    Args:
        text: Text with placeholders.
        storage: List of stored blocks.
        prefix: Placeholder prefix used during extraction.

    Returns:
        Text with placeholders replaced by stored blocks.
    """
    for i in range(len(storage) - 1, -1, -1):
        text = text.replace(f"\x00{prefix}{i}\x00", storage[i])
    return text


# Jira wiki forced line break: two backslashes.
_JIRA_LINE_BREAK = "\\\\"

_LIST_ITEM_RE = re.compile(r"^(\s*)(?:[-+*]|\d+\.) ")


def _indent_of(line: str) -> int:
    """Return the number of leading whitespace characters of *line*."""
    return len(line) - len(line.lstrip())


def _join_list_continuations(text: str) -> str:
    r"""Fold loose-list continuation blocks onto their list item's line.

    In Jira wiki markup a blank line ends a list, so a Markdown item
    followed by a blank line and an indented block (paragraph, image,
    ...) would restart numbering at every item and leave the block outside
    the item. Each blank-separated block that belongs to an item is instead
    appended to the item's line, joined by the forced line break ``\``,
    with its indentation removed. Blank lines between items of one list are
    dropped as well so the list stays a single list.

    Items without a blank-separated block (tight lists) are emitted
    unchanged. An item whose body holds a fenced code block is also left as
    it is, because ``{code}`` cannot live on a single list line. A block
    indented deeper than a nested item attaches to that nested item, the
    last item before it.

    Runs after code blocks and inline code are replaced by placeholders, so
    their content is never inspected.

    Args:
        text: Markdown with code blocks and inline code already extracted.

    Returns:
        Markdown with loose-list items collapsed onto single lines.
    """
    lines = text.split("\n")
    out: list[str] = []
    root_indent: int | None = None  # indent of the active list's first item
    i = 0
    while i < len(lines):
        match = _LIST_ITEM_RE.match(lines[i])
        if not match:
            root_indent = None
            out.append(lines[i])
            i += 1
            continue

        if root_indent is None:
            root_indent = len(match.group(1))

        # Collect the item's body: everything up to the next item line or
        # the first non-blank line that is not indented past the list root.
        j = i + 1
        while j < len(lines) and not _LIST_ITEM_RE.match(lines[j]):
            if lines[j].strip() and _indent_of(lines[j]) <= root_indent:
                break
            j += 1
        body = lines[i + 1 : j]
        trailing: list[str] = []
        while body and not body[-1].strip():
            trailing.append(body.pop())

        # Split the body into blank-separated blocks; a block's own lines
        # are one paragraph, so they are joined with a space.
        blocks: list[list[str]] = [[]]
        for raw in body:
            if raw.strip():
                blocks[-1].append(raw.strip())
            elif blocks[-1]:
                blocks.append([])
        loose = any(not raw.strip() for raw in body)
        if loose and not any("\x00CODEBLOCK" in raw for raw in body):
            joined = f" {_JIRA_LINE_BREAK} ".join(" ".join(block) for block in blocks)
            out.append(f"{lines[i]} {_JIRA_LINE_BREAK} {joined}")
        else:
            out.append(lines[i])
            out.extend(body)

        # Blank lines are kept unless another item of the same list follows.
        nxt = _LIST_ITEM_RE.match(lines[j]) if j < len(lines) else None
        if nxt and len(nxt.group(1)) >= root_indent:
            trailing = []
        else:
            root_indent = None
        out.extend(trailing)
        i = j
    return "\n".join(out)


def markdown_to_jira(input_text: str) -> str:
    """Convert Markdown syntax to Jira markup syntax.

    Args:
        input_text: Text in Markdown format

    Returns:
        Text in Jira markup format
    """
    if not input_text:
        return ""

    code_blocks: list[str] = []
    inline_codes: list[str] = []

    def _md_code_to_jira(match: re.Match[str]) -> str:
        syntax = match.group(1) or ""
        content = match.group(2)
        jira_lang = _normalize_code_language(syntax)
        code = "{code"
        if jira_lang:
            code += ":" + jira_lang
        code += "}" + content + "{code}"
        return code

    def _md_inline_to_jira(
        match: re.Match[str],
    ) -> str:
        return "{{" + match.group(1) + "}}"

    # Extract code blocks and inline code before
    # any other transformations.
    output = _extract_blocks(
        input_text,
        r"```(\w*)\n([\s\S]+?)```",
        _md_code_to_jira,
        code_blocks,
        "CODEBLOCK",
    )
    output = _extract_blocks(
        output,
        r"`([^`]+)`",
        _md_inline_to_jira,
        inline_codes,
        "INLINECODE",
    )

    # Keep loose-list continuation blocks inside their list item.
    output = _join_list_continuations(output)

    # Headers with = or - underlines
    output = re.sub(
        r"^(.*?)\n([=-])+$",
        lambda match: f"h{1 if match.group(2)[0] == '=' else 2}. {match.group(1)}",
        output,
        flags=re.MULTILINE,
    )

    # Headers with # prefix - require space after #
    # to distinguish from Jira lists (issue #786)
    output = re.sub(
        r"^([#]+) (.*)$",
        lambda match: f"h{len(match.group(1))}. " + match.group(2),
        output,
        flags=re.MULTILINE,
    )

    # Bold and italic - skip lines starting with
    # asterisks+space (Jira list syntax, issue #786)
    def convert_bold_italic_line(line: str) -> str:
        if re.match(r"^[*_]+\s", line):
            return line
        return re.sub(
            r"([*_]+)(.*?)\1",
            lambda m: (
                ("_" if len(m.group(1)) == 1 else "*")
                + m.group(2)
                + ("_" if len(m.group(1)) == 1 else "*")
            ),
            line,
        )

    lines = output.split("\n")
    output = "\n".join(convert_bold_italic_line(line) for line in lines)

    # Multi-level bulleted list
    def bulleted_list_fn(match: re.Match[str]) -> str:
        ident = len(match.group(1)) if match.group(1) else 0
        level = ident // 2 + 1
        return str("*" * level + " " + match.group(2))

    output = re.sub(
        r"^(\s+)?[-+*] (.*)$",
        bulleted_list_fn,
        output,
        flags=re.MULTILINE,
    )

    # Multi-level numbered list
    def numbered_list_fn(
        match: re.Match[str],
    ) -> str:
        ident = len(match.group(1)) if match.group(1) else 0
        level = ident // 2 + 1
        return str("#" * level + " " + match.group(2))

    output = re.sub(
        r"^(\s+)?\d+\. (.*)$",
        numbered_list_fn,
        output,
        flags=re.MULTILINE,
    )

    # HTML formatting tags to Jira markup
    tag_map = {
        "cite": "??",
        "del": "-",
        "ins": "+",
        "sup": "^",
        "sub": "~",
    }

    for tag, replacement in tag_map.items():
        output = re.sub(
            rf"<{tag}>(.*?)<\/{tag}>",
            rf"{replacement}\1{replacement}",
            output,
        )

    # Colored text
    output = re.sub(
        r"<span style=\"color:(#[^\"]+)\">"
        r"([\s\S]*?)</span>",
        r"{color:\1}\2{color}",
        output,
        flags=re.MULTILINE,
    )

    # Strikethrough
    output = re.sub(r"~~(.*?)~~", r"-\1-", output)

    # Images without alt text
    output = re.sub(r"!\[\]\(([^)\n\s]+)\)", r"!\1!", output)

    # Images with alt text
    output = re.sub(
        r"!\[([^\]\n]+)\]\(([^)\n\s]+)\)",
        r"!\2|alt=\1!",
        output,
    )

    # Links
    output = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"[\1|\2]", output)
    output = re.sub(r"<([^>]+)>", r"[\1]", output)

    # Convert markdown tables to Jira table format
    lines = output.split("\n")
    i = 0
    while i < len(lines):
        if i < len(lines) - 1 and re.match(r"\|[-\s|]+\|", lines[i + 1]):
            lines[i] = lines[i].replace("|", "||")
            lines.pop(i + 1)
        i += 1

    # Rejoin the lines
    output = "\n".join(lines)

    # Restore code blocks and inline code
    output = _restore_blocks(output, code_blocks, "CODEBLOCK")
    output = _restore_blocks(output, inline_codes, "INLINECODE")

    return output
