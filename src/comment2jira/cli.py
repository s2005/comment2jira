"""Command-line interface for comment2jira.

Flat Click command posting one Markdown comment to a Jira issue per run.
Copied conventions from jira2md: exit-code constants, exit_code_for(),
-v/-vv stderr logging (default WARNING), and the injectable-client pattern
where run(params, client=...) accepts a pre-built client for tests.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any, Literal

import click

from comment2jira import __version__
from comment2jira.attachments import (
    Deployment,
    UploadPlan,
    UploadResult,
    extract_refs,
    plan_uploads,
    rewrite_body,
)
from comment2jira.client import (
    AuthError,
    HttpxJiraClient,
    JiraClient,
    JiraError,
    NotFoundError,
)
from comment2jira.config import ConfigError, resolve_credentials
from comment2jira.detect import detect_deployment
from comment2jira.markup.md_to_adf import markdown_to_adf, verbatim_text_to_adf
from comment2jira.markup.md_to_wiki import markdown_to_jira

logger = logging.getLogger("comment2jira")

EXIT_OK = 0
EXIT_RUNTIME = 1
EXIT_AUTH = 2
EXIT_NOT_FOUND = 3


def exit_code_for(error: Exception) -> int:
    """Map a typed error to its CLI exit code."""
    if isinstance(error, AuthError):
        return EXIT_AUTH
    if isinstance(error, NotFoundError):
        return EXIT_NOT_FOUND
    return EXIT_RUNTIME


def _effective_body_format(requested: str, deployment: str) -> Literal["adf", "wiki"]:
    """Resolve --body-format against the detected deployment.

    ``auto`` keeps today's behavior unchanged: ADF on Cloud, wiki markup on
    DC. ``wiki`` and ``adf`` force that body format regardless of what was
    detected, which is how a Cloud comment gets inline images (Cloud's
    ``api/3`` ADF path only ever links to attachments; its ``api/2`` wiki
    path renders ``!stored-name!`` inline).

    Args:
        requested: Value of --body-format ("auto", "adf" or "wiki").
        deployment: Detected deployment ("cloud" or "dc").

    Returns:
        The effective body format to use for conversion and posting.

    Raises:
        ConfigError: When "adf" is requested but the detected deployment is
            DC, which has no ``/rest/api/3`` to post ADF to.
    """
    is_cloud = deployment == "cloud"
    if requested == "adf":
        if not is_cloud:
            msg = "--body-format adf is not supported on Server/Data Center (no /rest/api/3)."
            raise ConfigError(msg)
        return "adf"
    if requested == "wiki":
        return "wiki"
    # auto: unchanged existing behavior.
    return "adf" if is_cloud else "wiki"


def _setup_logging(verbose: int) -> None:
    """Configure stderr logging from the -v/-vv flags."""
    if verbose >= 2:
        level = logging.DEBUG
    elif verbose == 1:
        level = logging.INFO
    else:
        level = logging.WARNING
    logging.basicConfig(
        level=level,
        stream=sys.stderr,
        format="%(levelname)s - %(name)s - %(message)s",
        force=True,
    )


async def _run_file_mode(
    params: dict[str, Any],
    client: JiraClient,
    deployment: str,
    dry_run: bool,
    body_format: Literal["adf", "wiki"],
) -> int:
    """Execute --file mode: read, extract, upload, rewrite, convert, post.

    ``body_format`` (already resolved by :func:`_effective_body_format`)
    picks the attachment-rewrite rules, the Markdown converter and the
    comment API version; ``deployment`` is only the detected value, kept
    for the dry-run "Deployment:" line.
    """
    file_path = Path(params["file"])
    base_dir = file_path.parent
    post_path: Literal["dc", "cloud"] = "cloud" if body_format == "adf" else "dc"
    deployment_enum = Deployment.CLOUD if post_path == "cloud" else Deployment.DC

    markdown = file_path.read_text(encoding="utf-8")
    refs = extract_refs(markdown)
    plan = plan_uploads(refs, base_dir)

    if dry_run:
        _print_dry_run_plan(
            issue_key=params["issue"],
            deployment=deployment,
            body_format=body_format,
            plan=plan,
            deployment_enum=deployment_enum,
            markdown=markdown,
        )
        return EXIT_OK

    # Upload each planned attachment, rewrite references using the
    # server-reported filenames, convert and post. Any failure after the
    # first successful upload leaves orphaned attachments on the issue;
    # warn about them (Jira has no transaction to roll back to).
    results: list[UploadResult] = []
    uploaded_filenames: list[str] = []
    try:
        for ref in plan.to_upload:
            stored_name = ref.stored_name
            assert stored_name is not None
            result = await client.upload_attachment(
                params["issue"],
                str(ref.resolved_path),
                stored_name,
            )
            results.append(
                UploadResult(
                    id=result.id,
                    filename=result.filename,
                    content_url=result.content_url,
                )
            )
            uploaded_filenames.append(result.filename)

        body = rewrite_body(markdown, plan, results, deployment_enum)

        converted: str | dict[str, Any] = (
            markdown_to_adf(body) if post_path == "cloud" else markdown_to_jira(body)
        )

        await client.post_comment(params["issue"], converted, deployment=post_path)
    except Exception:
        if uploaded_filenames:
            logger.warning(
                "Run failed after attachments were uploaded; the issue now holds "
                "orphaned attachments: %s",
                ", ".join(uploaded_filenames),
            )
        raise

    return EXIT_OK


async def _run_text_mode(
    params: dict[str, Any],
    client: JiraClient,
    deployment: str,
    dry_run: bool,
    body_format: Literal["adf", "wiki"],
) -> int:
    """Execute --text mode: wrap verbatim and post.

    ``body_format`` picks the comment API version, mirroring the existing
    DC text-mode pattern (raw text, no conversion, posted via api/2) when
    it resolves to "wiki", even when the detected deployment is Cloud.
    """
    text = params["text"]
    post_path: Literal["dc", "cloud"] = "cloud" if body_format == "adf" else "dc"

    body: str | dict[str, Any] = verbatim_text_to_adf(text) if post_path == "cloud" else text

    if dry_run:
        click.echo(f"Issue: {params['issue']}")
        click.echo(f"Deployment: {deployment}")
        click.echo(f"Body format: {body_format}")
        click.echo("Attachments: none")
        if post_path == "cloud":
            click.echo("Body (ADF):")
            click.echo(json.dumps(body, indent=2))
        else:
            click.echo("Body (wiki):")
            click.echo(text)
        return EXIT_OK

    await client.post_comment(params["issue"], body, deployment=post_path)
    return EXIT_OK


def _print_dry_run_plan(
    *,
    issue_key: str,
    deployment: str,
    body_format: Literal["adf", "wiki"],
    plan: UploadPlan,
    deployment_enum: Deployment,
    markdown: str,
) -> None:
    """Print the dry-run plan to stdout.

    References to files that exist are rewritten with their planned stored
    names so the printed body matches what a real run would post. Cloud
    attachment URLs are only known after uploading, so they appear as the
    ``<attachment-url>`` placeholder there.

    ``deployment`` is the real detected deployment, printed as-is;
    ``body_format`` is the effective, already-resolved choice (never
    "auto") that decides which conversion is shown below it.
    """
    click.echo(f"Issue: {issue_key}")
    click.echo(f"Deployment: {deployment}")
    click.echo(f"Body format: {body_format}")
    if plan.to_upload:
        click.echo("Attachments:")
        for ref in plan.to_upload:
            assert ref.resolved_path is not None
            size = ref.resolved_path.stat().st_size
            click.echo(f"  {ref.resolved_path} ({size} bytes) -> {ref.stored_name}")
    else:
        click.echo("Attachments: none")

    dry_results = [
        UploadResult(id="", filename=ref.stored_name or "", content_url="<attachment-url>")
        for ref in plan.to_upload
    ]
    rewritten = rewrite_body(markdown, plan, dry_results, deployment_enum)

    converted: str | dict[str, Any]
    if body_format == "adf":
        converted = markdown_to_adf(rewritten)
        click.echo("Body (ADF):")
        click.echo(json.dumps(converted, indent=2))
    else:
        converted = markdown_to_jira(rewritten)
        click.echo("Body (wiki):")
        click.echo(converted)


async def run(params: dict[str, Any], *, client: JiraClient | None = None) -> int:
    """Run the CLI orchestration; returns the process exit code.

    Args:
        params: Click parameter mapping.
        client: Injectable client (tests inject a fake transport).
    """
    try:
        # --url/--email/--token supply these values from the CLI now.
        # Precedence over the environment and the .env file is
        # resolve_credentials' job, not this call site's.
        credentials = resolve_credentials(
            url=params.get("url"),
            email=params.get("email"),
            token=params.get("token"),
            auth=params.get("auth"),
            env_file=params.get("env_file"),
        )
    except ConfigError as exc:
        click.echo(f"error: {exc}", err=True)
        return EXIT_RUNTIME

    owns_client = client is None
    if client is None:
        client = HttpxJiraClient(credentials, retry_delay_base=0.0)

    try:
        deployment = await detect_deployment(client, host=credentials.host)
        dry_run = bool(params.get("dry_run"))
        body_format = _effective_body_format(str(params.get("body_format") or "auto"), deployment)

        if params.get("file"):
            return await _run_file_mode(params, client, deployment, dry_run, body_format)
        if params.get("text"):
            return await _run_text_mode(params, client, deployment, dry_run, body_format)

        # Should be unreachable: Click mutual-exclusion guard catches this.
        click.echo("error: either --file or --text is required", err=True)
        return EXIT_RUNTIME

    except (AuthError, NotFoundError, JiraError, ConfigError) as exc:
        click.echo(f"error: {exc}", err=True)
        return exit_code_for(exc)
    except FileNotFoundError as exc:
        click.echo(f"error: {exc}", err=True)
        return EXIT_RUNTIME
    except OSError as exc:
        click.echo(f"error: {exc}", err=True)
        return EXIT_RUNTIME
    finally:
        if owns_client:
            await client.aclose()


@click.command(name="comment2jira")
@click.version_option(__version__, prog_name="comment2jira")
@click.option(
    "--issue",
    required=True,
    help="Jira issue key (e.g. PROJ-123).",
)
@click.option(
    "--file",
    "file",
    default=None,
    type=click.Path(exists=False),
    help="Path to a Markdown file to post.",
)
@click.option(
    "--text",
    default=None,
    help="Inline comment text to post.",
)
@click.option(
    "--url",
    default=None,
    help="Jira base URL [env: JIRA_URL]",
)
@click.option(
    "--email",
    default=None,
    help="Account email [env: JIRA_EMAIL]",
)
@click.option(
    "--token",
    default=None,
    help="API token / PAT [env: JIRA_TOKEN]",
)
@click.option(
    "--env-file",
    "env_file",
    default=None,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Path to .env file [env: COMMENT2JIRA_ENV_FILE]",
)
@click.option(
    "--auth",
    type=click.Choice(["auto", "basic", "bearer"]),
    default=None,
    help="Auth scheme (default: auto)",
)
@click.option(
    "--body-format",
    "body_format",
    type=click.Choice(["auto", "adf", "wiki"]),
    default="auto",
    help=(
        "Comment body format: auto (Cloud -> ADF, DC -> wiki), adf (force ADF; "
        "Cloud only), or wiki (force wiki markup; use for inline images on Cloud)."
    ),
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show what would be done without posting.",
)
@click.option("-v", "--verbose", count=True, help="Verbose (-v) / debug (-vv)")
def main(**params: Any) -> None:
    """Post a Markdown comment to a Jira issue.

    Exactly one of --file or --text must be provided. Local image and file
    references in the Markdown are uploaded as attachments before posting.
    """
    # Validate mutual exclusion of --file / --text.
    if params.get("file") and params.get("text"):
        raise click.UsageError("--file and --text are mutually exclusive")
    if not params.get("file") and not params.get("text"):
        raise click.UsageError("either --file or --text is required")

    _setup_logging(int(params.get("verbose") or 0))
    try:
        exit_code = asyncio.run(run(params))
    except KeyboardInterrupt:
        click.echo("interrupted", err=True)
        sys.exit(EXIT_RUNTIME)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
