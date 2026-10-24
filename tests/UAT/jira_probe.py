"""Read-back and cleanup helper for the guided UAT walkthroughs.

The comment2jira CLI only writes: it posts a comment and uploads
attachments, and it never reads an issue back. A UAT step that asserted on
an exit code alone would therefore prove nothing about what actually
landed in Jira, so the guides pair every write with a read through this
helper - the same shape ``tests/integration`` uses for its assertions.

Credentials come from the same ``test.env`` the guides point the CLI at.
Nothing here prints a credential: the token is read into a request header
and never echoed, and ``--action deployment`` reports the deployment type
without naming the host.

Every action takes named parameters only. Run it through the project's
interpreter so the dependencies resolve:

    uv run python tests/UAT/jira_probe.py --action deployment --env-file test.env

Exit codes: 0 on success, 1 on a request or configuration failure, 2 on
bad invocation (argparse).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import httpx
from dotenv import dotenv_values

# Comments the UAT suite posts all carry this token, either from a fixture
# file or from the --text string, so cleanup can find its own writes and
# leave anything else on the scratch issue untouched.
COMMENT_MARKER = "comment2jira-uat"

# Attachments the UAT fixtures upload all start with this prefix, for the
# same reason.
ATTACHMENT_PREFIX = "uat-"

REQUIRED_KEYS = ("JIRA_URL", "JIRA_TOKEN", "JIRA_TEST_ISSUE")


class ProbeError(Exception):
    """Raised when the probe cannot run or a request fails."""


def read_env(env_file: Path) -> dict[str, str]:
    """Parse the env file, dropping keys with empty values."""
    if not env_file.is_file():
        msg = f"env file not found: {env_file}"
        raise ProbeError(msg)
    values = {key: value for key, value in dotenv_values(env_file).items() if value}
    missing = [key for key in REQUIRED_KEYS if key not in values]
    if missing:
        msg = f"{env_file} is missing required keys: {', '.join(missing)}"
        raise ProbeError(msg)
    return values


def build_client(values: dict[str, str]) -> httpx.Client:
    """Build an authenticated client; the token never leaves this function."""
    email = values.get("JIRA_EMAIL")
    token = values["JIRA_TOKEN"]
    headers = {"Accept": "application/json"}
    auth: httpx.Auth | None = None
    if email:
        auth = httpx.BasicAuth(email, token)
    else:
        headers["Authorization"] = f"Bearer {token}"
    return httpx.Client(
        base_url=values["JIRA_URL"].rstrip("/"),
        headers=headers,
        auth=auth,
        timeout=30.0,
    )


def flatten(body: Any) -> str:
    """Flatten a comment body to plain text for both api/2 and api/3 shapes.

    Server/DC returns wiki markup as a string; Cloud returns an ADF
    document, whose text lives in nested ``text`` and ``href`` keys. Both
    keys are collected so a rewritten attachment reference - which becomes
    a link mark on Cloud - is visible to an assertion.
    """
    if isinstance(body, str):
        return body
    collected: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key in ("text", "href"):
                if isinstance(node.get(key), str):
                    collected.append(node[key])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(body)
    return " ".join(collected)


def get_json(client: httpx.Client, path: str, **params: Any) -> dict[str, Any]:
    """GET a Jira endpoint and decode it, turning any HTTP error into ProbeError."""
    try:
        response = client.get(path, params=params or None)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        msg = f"GET {path} failed: {exc}"
        raise ProbeError(msg) from exc
    payload: dict[str, Any] = response.json()
    return payload


def action_deployment(client: httpx.Client, _issue: str) -> int:
    """Print the deployment type, so a guide can branch on cloud vs dc."""
    info = get_json(client, "/rest/api/2/serverInfo")
    deployment = str(info.get("deploymentType") or "").lower()
    print("cloud" if deployment == "cloud" else "dc")
    return 0


def action_comment_count(client: httpx.Client, issue: str) -> int:
    """Print the total number of comments on the issue."""
    payload = get_json(client, f"/rest/api/2/issue/{issue}/comment", maxResults=0)
    print(int(payload.get("total", 0)))
    return 0


def action_attachment_count(client: httpx.Client, issue: str) -> int:
    """Print the number of attachments on the issue."""
    payload = get_json(client, f"/rest/api/2/issue/{issue}", fields="attachment")
    print(len(payload.get("fields", {}).get("attachment") or []))
    return 0


def action_latest_comment(client: httpx.Client, issue: str) -> int:
    """Print the newest comment on the issue as flattened plain text."""
    payload = get_json(
        client,
        f"/rest/api/2/issue/{issue}/comment",
        orderBy="-created",
        maxResults=1,
    )
    comments = payload.get("comments") or []
    if not comments:
        msg = f"no comments found on {issue}"
        raise ProbeError(msg)
    print(flatten(comments[0].get("body")))
    return 0


def action_attachments(client: httpx.Client, issue: str) -> int:
    """Print one attachment filename per line, in the order Jira reports them."""
    payload = get_json(client, f"/rest/api/2/issue/{issue}", fields="attachment")
    for entry in payload.get("fields", {}).get("attachment") or []:
        print(str(entry.get("filename", "")))
    return 0


def action_cleanup(client: httpx.Client, issue: str) -> int:
    """Delete only what this suite wrote, and report the counts.

    Comments are matched on COMMENT_MARKER and attachments on
    ATTACHMENT_PREFIX, so anything else already on the scratch issue is
    left alone. Idempotent: a second run finds nothing and still exits 0.
    """
    payload = get_json(client, f"/rest/api/2/issue/{issue}/comment", maxResults=1000)
    removed_comments = 0
    for comment in payload.get("comments") or []:
        if COMMENT_MARKER not in flatten(comment.get("body")):
            continue
        response = client.delete(f"/rest/api/2/issue/{issue}/comment/{comment['id']}")
        if response.status_code in (200, 204):
            removed_comments += 1

    issue_payload = get_json(client, f"/rest/api/2/issue/{issue}", fields="attachment")
    removed_attachments = 0
    for entry in issue_payload.get("fields", {}).get("attachment") or []:
        if not str(entry.get("filename", "")).startswith(ATTACHMENT_PREFIX):
            continue
        response = client.delete(f"/rest/api/2/attachment/{entry['id']}")
        if response.status_code in (200, 204):
            removed_attachments += 1

    print(f"removed comments: {removed_comments}")
    print(f"removed attachments: {removed_attachments}")
    return 0


ACTIONS = {
    "attachment-count": action_attachment_count,
    "attachments": action_attachments,
    "cleanup": action_cleanup,
    "comment-count": action_comment_count,
    "deployment": action_deployment,
    "latest-comment": action_latest_comment,
}


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse the named parameters; there are no positional arguments."""
    parser = argparse.ArgumentParser(
        prog="jira_probe.py",
        description="Read back or clean up what the comment2jira UAT guides wrote.",
    )
    parser.add_argument(
        "--action",
        required=True,
        choices=sorted(ACTIONS),
        help="What to do: read the issue back, or delete this suite's own writes.",
    )
    parser.add_argument(
        "--env-file",
        default="test.env",
        help="Credentials file to read (default: test.env at the repository root).",
    )
    parser.add_argument(
        "--issue",
        default=None,
        help="Issue key to act on (default: the JIRA_TEST_ISSUE key in the env file).",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    """Run one action and return the process exit code."""
    args = parse_args(argv)
    try:
        values = read_env(Path(args.env_file))
        issue = args.issue or values["JIRA_TEST_ISSUE"]
        with build_client(values) as client:
            return ACTIONS[args.action](client, issue)
    except ProbeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
