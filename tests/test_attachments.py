"""Tests for comment2jira attachment extraction, classification and rewriting."""

from __future__ import annotations

import logging

import pytest

from comment2jira.attachments import (
    Deployment,
    RefKind,
    UploadPlan,
    UploadResult,
    extract_refs,
    plan_uploads,
    rewrite_body,
)


class TestExtractRefs:
    """Extraction of image and link references with source spans."""

    @pytest.mark.unit
    def test_extract_image_ref(self) -> None:
        md = "See ![chart](data.png) for details"
        refs = extract_refs(md)
        assert len(refs) == 1
        ref = refs[0]
        assert ref.kind == RefKind.IMAGE
        assert ref.alt_or_label == "chart"
        assert ref.target == "data.png"
        # Span should cover ![chart](data.png)
        assert md[ref.start : ref.end] == "![chart](data.png)"

    @pytest.mark.unit
    def test_extract_link_ref(self) -> None:
        md = "Read [the doc](manual.pdf)"
        refs = extract_refs(md)
        assert len(refs) == 1
        ref = refs[0]
        assert ref.kind == RefKind.LINK
        assert ref.alt_or_label == "the doc"
        assert ref.target == "manual.pdf"

    @pytest.mark.unit
    def test_extract_mixed_refs(self) -> None:
        md = "See ![img](a.png) and [link](b.pdf)"
        refs = extract_refs(md)
        assert len(refs) == 2
        assert refs[0].kind == RefKind.IMAGE
        assert refs[1].kind == RefKind.LINK

    @pytest.mark.unit
    def test_angle_bracket_destination(self) -> None:
        md = "See ![alt](<path with spaces.png>)"
        refs = extract_refs(md)
        assert len(refs) == 1
        assert refs[0].target == "path with spaces.png"

    @pytest.mark.unit
    def test_empty_alt(self) -> None:
        md = "![](empty-alt.png)"
        refs = extract_refs(md)
        assert len(refs) == 1
        assert refs[0].alt_or_label == ""

    @pytest.mark.unit
    def test_ignore_fenced_code_block(self) -> None:
        md = """\
```
![code-image](fake.png)
[code-link](fake.pdf)
```
Real ![real](real.png)
"""
        refs = extract_refs(md)
        assert len(refs) == 1
        assert refs[0].target == "real.png"

    @pytest.mark.unit
    def test_link_not_duplicated_from_image(self) -> None:
        """A link regex must not double-match inside ![alt](path)."""
        md = "![chart](data.png)"
        refs = extract_refs(md)
        assert len(refs) == 1
        assert refs[0].kind == RefKind.IMAGE


class TestClassification:
    """Remote vs local classification of reference targets."""

    @pytest.mark.unit
    def test_http_remote(self) -> None:
        refs = extract_refs("![remote](http://example.com/img.png)")
        from comment2jira.attachments import _is_remote

        assert _is_remote(refs[0].target) is True

    @pytest.mark.unit
    def test_https_remote(self) -> None:
        refs = extract_refs("![remote](https://example.com/img.png)")
        from comment2jira.attachments import _is_remote

        assert _is_remote(refs[0].target) is True

    @pytest.mark.unit
    def test_https_case_insensitive(self) -> None:
        from comment2jira.attachments import _is_remote

        assert _is_remote("HTTP://example.com/x") is True
        assert _is_remote("HTTPS://example.com/x") is True

    @pytest.mark.unit
    def test_local_path_not_remote(self) -> None:
        from comment2jira.attachments import _is_remote

        assert _is_remote("local/file.png") is False

    @pytest.mark.unit
    def test_empty_target_is_non_file(self) -> None:
        from comment2jira.attachments import _is_remote

        assert _is_remote("") is True
        assert _is_remote("#") is True

    @pytest.mark.unit
    def test_plan_uploads_skips_remote(self, tmp_path: pytest.TempPathFactory) -> None:
        md = "![local](img.png) ![remote](https://host/img.png)"
        img_file = tmp_path / "img.png"
        img_file.write_bytes(b"png data")
        refs = extract_refs(md)
        plan = plan_uploads(refs, tmp_path)
        assert len(plan.to_upload) == 1
        assert plan.to_upload[0].target == "img.png"


class TestRelativeResolution:
    """Path resolution against base_dir."""

    @pytest.mark.unit
    def test_relative_resolved_against_base(
        self,
        tmp_path: pytest.TempPathFactory,
    ) -> None:
        subdir = tmp_path / "sub"
        subdir.mkdir()
        img_file = subdir / "pic.png"
        img_file.write_bytes(b"data")
        md = "![x](pic.png)"
        refs = extract_refs(md)
        plan = plan_uploads(refs, subdir)
        assert len(plan.to_upload) == 1
        assert plan.to_upload[0].resolved_path == img_file

    @pytest.mark.unit
    def test_absolute_path_stays_absolute(
        self,
        tmp_path: pytest.TempPathFactory,
    ) -> None:
        abs_file = tmp_path / "abs.png"
        abs_file.write_bytes(b"data")
        # Use an absolute path in the markdown.
        md = f"![x]({abs_file})"
        refs = extract_refs(md)
        plan = plan_uploads(refs, tmp_path)
        assert len(plan.to_upload) == 1
        assert plan.to_upload[0].resolved_path == abs_file


class TestBackslashTolerance:
    """Windows backslash path normalisation."""

    @pytest.mark.unit
    def test_backslash_path_resolved(
        self,
        tmp_path: pytest.TempPathFactory,
    ) -> None:
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        img_file = subdir / "image.png"
        img_file.write_bytes(b"data")
        md = "![x](subdir\\image.png)"
        refs = extract_refs(md)
        plan = plan_uploads(refs, tmp_path)
        assert len(plan.to_upload) == 1
        # The resolved path should point to tmp_path/subdir/image.png
        expected = (subdir / "image.png").resolve(strict=False)
        assert plan.to_upload[0].resolved_path == expected

    @pytest.mark.unit
    def test_windows_drive_letter(
        self,
        tmp_path: pytest.TempPathFactory,
    ) -> None:
        # A C:\... style path should be treated as absolute.
        md = "![x](C:\\\\users\\\\file.png)"
        refs = extract_refs(md)
        from comment2jira.attachments import resolve_ref

        resolved = resolve_ref(refs[0], tmp_path)
        # Should be absolute after resolution.
        assert resolved.resolved_path is not None
        assert resolved.resolved_path.is_absolute()


class TestBasenameSuffixing:
    """Same-basename collision suffixing."""

    @pytest.mark.unit
    def test_unique_basenames_no_suffix(self, tmp_path: pytest.TempPathFactory) -> None:
        (tmp_path / "a.png").write_bytes(b"a")
        (tmp_path / "b.pdf").write_bytes(b"b")
        md = "![x](a.png) [y](b.pdf)"
        refs = extract_refs(md)
        plan = plan_uploads(refs, tmp_path)
        names = [r.stored_name for r in plan.to_upload]
        assert names == ["a.png", "b.pdf"]

    @pytest.mark.unit
    def test_collision_gets_suffix(self, tmp_path: pytest.TempPathFactory) -> None:
        (tmp_path / "file.txt").write_bytes(b"original")
        other_dir = tmp_path / "other"
        other_dir.mkdir()
        (other_dir / "file.txt").write_bytes(b"collision")
        md = "![x](file.txt) [y](other/file.txt)"
        refs = extract_refs(md)
        plan = plan_uploads(refs, tmp_path)
        names = [r.stored_name for r in plan.to_upload]
        assert "file.txt" in names
        assert "file-1.txt" in names

    @pytest.mark.unit
    def test_triple_collision(self, tmp_path: pytest.TempPathFactory) -> None:
        (tmp_path / "f.txt").write_bytes(b"1")
        d1 = tmp_path / "d1"
        d1.mkdir()
        (d1 / "f.txt").write_bytes(b"2")
        d2 = tmp_path / "d2"
        d2.mkdir()
        (d2 / "f.txt").write_bytes(b"3")
        md = "![a](f.txt) ![b](d1/f.txt) ![c](d2/f.txt)"
        refs = extract_refs(md)
        plan = plan_uploads(refs, tmp_path)
        names = [r.stored_name for r in plan.to_upload]
        assert names == ["f.txt", "f-1.txt", "f-2.txt"]


class TestMissingFileWarnAndSkip:
    """Missing files produce warnings and leave refs untouched."""

    @pytest.mark.unit
    def test_missing_file_warned_and_skipped(
        self,
        tmp_path: pytest.TempPathFactory,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        md = "![x](missing.png)"
        refs = extract_refs(md)
        with caplog.at_level(logging.WARNING, logger="comment2jira"):
            plan = plan_uploads(refs, tmp_path)
        assert len(plan.to_upload) == 0
        assert len(plan.skipped) == 1
        assert "missing.png" in caplog.text

    @pytest.mark.unit
    def test_missing_file_left_unrewritten(
        self,
        tmp_path: pytest.TempPathFactory,
    ) -> None:
        md = "Look at ![missing](gone.png) here"
        refs = extract_refs(md)
        plan = plan_uploads(refs, tmp_path)
        # No uploads, no results -- body unchanged.
        result = rewrite_body(md, plan, [], Deployment.DC)
        assert result == md

    @pytest.mark.unit
    def test_partial_missing_ok(
        self,
        tmp_path: pytest.TempPathFactory,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        (tmp_path / "exists.png").write_bytes(b"data")
        md = "![ok](exists.png) ![nope](missing.png)"
        refs = extract_refs(md)
        with caplog.at_level(logging.WARNING, logger="comment2jira"):
            plan = plan_uploads(refs, tmp_path)
        assert len(plan.to_upload) == 1
        assert len(plan.skipped) == 1


class TestRewriteDc:
    """Server/DC wiki markup rewriting forms."""

    @pytest.mark.unit
    def test_image_with_alt(self) -> None:
        body = "Start ![chart](x.png) end"
        refs = extract_refs(body)
        ref = refs[0]
        plan = UploadPlan(to_upload=[ref], skipped=[])
        results = [UploadResult(id="100", filename="x.png", content_url="")]
        out = rewrite_body(body, plan, results, Deployment.DC)
        assert out == "Start !x.png|alt=chart! end"

    @pytest.mark.unit
    def test_image_without_alt(self) -> None:
        body = "Look ![](x.png) now"
        refs = extract_refs(body)
        ref = refs[0]
        plan = UploadPlan(to_upload=[ref], skipped=[])
        results = [UploadResult(id="100", filename="x.png", content_url="")]
        out = rewrite_body(body, plan, results, Deployment.DC)
        assert out == "Look !x.png! now"

    @pytest.mark.unit
    def test_link_rewrite(self) -> None:
        body = "Read [Manual](doc.pdf) here"
        refs = extract_refs(body)
        ref = refs[0]
        plan = UploadPlan(to_upload=[ref], skipped=[])
        results = [UploadResult(id="101", filename="doc.pdf", content_url="")]
        out = rewrite_body(body, plan, results, Deployment.DC)
        assert out == "Read [Manual|^doc.pdf] here"


class TestRewriteCloud:
    """Cloud ADF-path rewriting (plain Markdown link to content URL)."""

    @pytest.mark.unit
    def test_image_with_alt(self) -> None:
        body = "See ![chart](x.png) text"
        refs = extract_refs(body)
        ref = refs[0]
        plan = UploadPlan(to_upload=[ref], skipped=[])
        results = [
            UploadResult(
                id="100", filename="x.png", content_url="https://jira/attachment/100/x.png"
            ),
        ]
        out = rewrite_body(body, plan, results, Deployment.CLOUD)
        assert out == "See [chart](https://jira/attachment/100/x.png) text"

    @pytest.mark.unit
    def test_image_without_alt_uses_filename(self) -> None:
        body = "View ![](x.png) now"
        refs = extract_refs(body)
        ref = refs[0]
        plan = UploadPlan(to_upload=[ref], skipped=[])
        results = [
            UploadResult(
                id="100", filename="x.png", content_url="https://jira/attachment/100/x.png"
            ),
        ]
        out = rewrite_body(body, plan, results, Deployment.CLOUD)
        assert out == "View [x.png](https://jira/attachment/100/x.png) now"

    @pytest.mark.unit
    def test_link_rewrite(self) -> None:
        body = "Get [Manual](doc.pdf) now"
        refs = extract_refs(body)
        ref = refs[0]
        plan = UploadPlan(to_upload=[ref], skipped=[])
        results = [
            UploadResult(
                id="101", filename="doc.pdf", content_url="https://jira/attachment/101/doc.pdf"
            ),
        ]
        out = rewrite_body(body, plan, results, Deployment.CLOUD)
        assert out == "Get [Manual](https://jira/attachment/101/doc.pdf) now"


class TestRewriteMultiple:
    """Multiple references rewritten correctly with offset handling."""

    @pytest.mark.unit
    def test_two_images_dc(self) -> None:
        body = "Start ![a](a.png) mid ![b](b.png) end"
        refs = extract_refs(body)
        plan = UploadPlan(to_upload=refs, skipped=[])
        results = [
            UploadResult(id="1", filename="a.png", content_url=""),
            UploadResult(id="2", filename="b.png", content_url=""),
        ]
        out = rewrite_body(body, plan, results, Deployment.DC)
        assert out == "Start !a.png|alt=a! mid !b.png|alt=b! end"

    @pytest.mark.unit
    def test_skipped_ref_unchanged(self) -> None:
        body = "See ![missing](gone.png) here"
        refs = extract_refs(body)
        skipped_ref = refs[0]
        plan = UploadPlan(to_upload=[], skipped=[skipped_ref])
        out = rewrite_body(body, plan, [], Deployment.DC)
        assert out == body
