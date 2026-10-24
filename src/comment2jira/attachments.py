"""Attachment reference extraction, classification and rewriting.

New code written for comment2jira (not copied from any upstream project).
Handles Markdown image ``![alt](path)`` and link ``[label](path)`` references:
extracts them with source spans, classifies remote vs local targets, resolves
local paths against a base directory, handles same-basename collision suffixing,
and rewrites surviving references into Jira-specific forms per deployment.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path

logger = logging.getLogger("comment2jira")


class RefKind(Enum):
    """Kind of Markdown reference."""

    IMAGE = "image"
    LINK = "link"


class Deployment(Enum):
    """Jira deployment type."""

    DC = "dc"
    CLOUD = "cloud"


@dataclass(frozen=True)
class FileRef:
    """A single Markdown file reference with its source location.

    Attributes:
        kind: Whether this is an image or a link reference.
        alt_or_label: Alt text (images) or label text (links).
        target: Raw destination path/URL as it appears in the Markdown.
        start: Character offset of the opening bracket in the source text.
        end: Character offset one past the closing parenthesis.
        resolved_path: Absolute path to the local file (set after resolution).
        stored_name: Filename under which the file will be uploaded (after
            collision suffixing).
        content_url: Server-reported content URL (set after upload).
    """

    kind: RefKind
    alt_or_label: str
    target: str
    start: int
    end: int
    resolved_path: Path | None = None
    stored_name: str | None = None
    content_url: str | None = None


@dataclass(frozen=True)
class UploadPlan:
    """Result of planning uploads for all local file references.

    Attributes:
        to_upload: List of refs that exist locally and should be uploaded,
            each with its ``stored_name`` assigned.
        skipped: List of refs whose target files were missing (warned about).
    """

    to_upload: list[FileRef]
    skipped: list[FileRef]


@dataclass(frozen=True)
class UploadResult:
    """Metadata returned by Jira after an attachment upload.

    Attributes:
        id: Attachment ID from Jira.
        filename: The filename under which Jira stored the attachment.
        content_url: Direct download URL for the attachment content.
    """

    id: str
    filename: str
    content_url: str


# Combined regex: group 1 = optional ! prefix (present for images),
# group 2 = alt/label text, group 3 = destination (with or without angle brackets).
_REF_RE = re.compile(r"(!?)\[([^\]]*)\]\((<[^>]+>|[^)]*)\)")


def extract_refs(markdown: str) -> list[FileRef]:
    """Extract image and link references from Markdown with their spans.

    References inside fenced code blocks (`` ```...``` ```) are ignored.
    Angle-bracket destinations like ``![alt](<path with spaces>)`` are
    handled; the angle brackets are stripped from the stored target.

    Uses a single regex pass that captures both ``![alt](path)`` (image,
    identified by a leading ``!``) and ``[label](path)`` (link).  This
    avoids the duplicate-match problem where a link pattern would also
    fire on the bracketed portion of an image reference.

    Args:
        markdown: Raw Markdown source text.

    Returns:
        List of :class:`FileRef` instances in source order, each carrying
        the exact ``start``/``end`` offsets for in-place rewriting.
    """
    # Find fenced code block ranges to exclude.
    code_ranges: list[tuple[int, int]] = []
    for m in re.finditer(r"```[\w]*\n?([\s\S]*?)```", markdown):
        code_ranges.append((m.start(), m.end()))

    def _in_code(pos: int) -> bool:
        return any(cs <= pos < ce for cs, ce in code_ranges)

    refs: list[FileRef] = []
    for m in _REF_RE.finditer(markdown):
        if _in_code(m.start()):
            continue
        bang = m.group(1)
        alt_or_label = m.group(2)
        raw_target = m.group(3)
        # Strip angle brackets if present.
        target = raw_target[1:-1] if raw_target.startswith("<") else raw_target
        kind = RefKind.IMAGE if bang == "!" else RefKind.LINK
        refs.append(
            FileRef(
                kind=kind,
                alt_or_label=alt_or_label,
                target=target,
                start=m.start(),
                end=m.end(),
            )
        )

    return refs


def _is_remote(target: str) -> bool:
    """Return True if *target* is a remote URL that should never be uploaded."""
    lower = target.lower().strip()
    if lower.startswith(("http://", "https://")):
        return True
    # Empty or anchor-only targets are not file references.
    return not lower or lower == "#"


def resolve_ref(ref: FileRef, base_dir: Path) -> FileRef:
    """Resolve a single reference's target against *base_dir*.

    Windows backslash separators and drive letters are normalised via
    ``pathlib``.  Absolute paths (``C:\\...`` or ``/abs``) stay absolute;
    relative paths are joined to *base_dir*.

    Args:
        ref: The reference to resolve.
        base_dir: Directory of the Markdown file (for relative paths).

    Returns:
        A new :class:`FileRef` with ``resolved_path`` set, or the original
        ref unchanged if the target is remote/non-file.
    """
    if _is_remote(ref.target):
        return ref
    # Normalise backslashes to forward slashes for pathlib compatibility.
    normalized = ref.target.replace("\\", "/")
    p = Path(normalized)
    if not p.is_absolute():
        p = base_dir / p
    # Resolve to absolute without following symlinks (strict=False).
    p = p.resolve(strict=False)
    return replace(ref, resolved_path=p)


def plan_uploads(refs: list[FileRef], base_dir: Path) -> UploadPlan:
    """Resolve references and assign stored names with collision suffixing.

    For each local-file reference whose target exists on disk, assigns a
    ``stored_name`` using the file's basename.  When multiple files share
    the same basename, the second gets ``name-1.ext``, the third
    ``name-2.ext``, etc. (suffix applied to the stem).

    Missing files trigger a ``logger.warning`` and are placed in the
    ``skipped`` list; their refs retain ``stored_name=None`` and must be
    left unrewritten.

    Args:
        refs: Extracted references from :func:`extract_refs`.
        base_dir: Directory of the Markdown file.

    Returns:
        An :class:`UploadPlan` with ``to_upload`` and ``skipped`` lists.
    """
    resolved: list[FileRef] = []
    for ref in refs:
        resolved.append(resolve_ref(ref, base_dir))

    # Separate uploadable vs skip candidates.
    uploadable: list[FileRef] = []
    skipped: list[FileRef] = []
    for ref in resolved:
        if ref.resolved_path is None or _is_remote(ref.target):
            # Remote / non-file — not an upload candidate at all.
            continue
        if not ref.resolved_path.exists():
            logger.warning(
                "Referenced file not found, skipping: %s",
                ref.resolved_path,
            )
            skipped.append(ref)
            continue
        uploadable.append(ref)

    # Assign stored names with basename collision suffixing.
    basename_counts: dict[str, int] = {}
    to_upload: list[FileRef] = []
    for ref in uploadable:
        assert ref.resolved_path is not None  # guarded above
        base = ref.resolved_path.name
        count = basename_counts.get(base, 0)
        if count == 0:
            stored = base
        else:
            stem = ref.resolved_path.stem
            suffix = ref.resolved_path.suffix
            stored = f"{stem}-{count}{suffix}"
        basename_counts[base] = count + 1
        to_upload.append(replace(ref, stored_name=stored))

    return UploadPlan(to_upload=to_upload, skipped=skipped)


def rewrite_body(
    markdown: str,
    plan: UploadPlan,
    results: list[UploadResult],
    deployment: Deployment,
) -> str:
    """Rewrite Markdown references using upload results.

    Builds a mapping from ``(start, end)`` span to replacement text by
    matching upload results to planned refs (by stored_name), then applies
    replacements from right to left to preserve offsets.

    Rewriting rules per deployment:

    - **dc** (Server/DC wiki):

      - Images: ``![alt](x.png)`` -> ``!stored|alt=alt!`` or ``!stored!``
        when alt is empty.
      - Local file links: ``[label](x.pdf)`` -> ``[label|^stored]``

    - **cloud** (ADF): Both images and local file links become a plain
      Markdown link ``[label](content-url)`` where *label* is the alt text
      (or stored name when alt is empty) for images, and the original label
      for links.

    Args:
        markdown: Original Markdown source.
        plan: The upload plan produced by :func:`plan_uploads`.
        results: Server-reported metadata for each uploaded attachment,
            in the same order as ``plan.to_upload``.
        deployment: Target Jira deployment.

    Returns:
        The rewritten Markdown string.
    """
    # Build span -> replacement map.
    replacements: dict[tuple[int, int], str] = {}

    for ref, result in zip(plan.to_upload, results, strict=True):
        key = (ref.start, ref.end)
        if deployment == Deployment.DC:
            replacements[key] = _rewrite_dc(ref, result.filename)
        elif deployment == Deployment.CLOUD:
            replacements[key] = _rewrite_cloud(ref, result.filename, result.content_url)

    # Apply replacements right-to-left to preserve offsets.
    sorted_spans = sorted(replacements.keys(), reverse=True)
    body = markdown
    for start, end in sorted_spans:
        body = body[:start] + replacements[(start, end)] + body[end:]

    return body


def _rewrite_dc(ref: FileRef, stored_name: str) -> str:
    """Rewrite a reference for Server/DC (wiki markup)."""
    if ref.kind == RefKind.IMAGE:
        if ref.alt_or_label:
            return f"!{stored_name}|alt={ref.alt_or_label}!"
        return f"!{stored_name}!"
    # LINK
    return f"[{ref.alt_or_label}|^{stored_name}]"


def _rewrite_cloud(ref: FileRef, stored_name: str, content_url: str) -> str:
    """Rewrite a reference for Cloud (plain Markdown link to content URL)."""
    label = ref.alt_or_label if ref.kind == RefKind.IMAGE and ref.alt_or_label else stored_name
    if ref.kind == RefKind.LINK:
        label = ref.alt_or_label
    return f"[{label}]({content_url})"
