# UAT: `comment2jira --dry-run`

Manual user-acceptance test for the `--dry-run` flag: it must print the issue,
the detected deployment, the attachment plan and the fully converted comment
body, and then write nothing at all. This is the only guide in the suite that
touches the live instance without changing it, so run it first - a clean pass
here proves the credentials and the scratch issue are usable before any guide
starts posting.

## Prerequisites

The shared setup in [README.md](README.md): `uv` on `PATH`, a filled-in
`test.env` at the repository root, and the credentials exported into the shell -

```bash
set -a; . ./test.env; set +a
```

`--dry-run` performs one `GET /rest/api/2/serverInfo` for deployment detection
and nothing else, so this guide needs no cleanup.

## What this uses

| Flag | Value |
| --- | --- |
| `--issue` | `UAT-1` - a synthetic key. `--dry-run` never contacts the issue, so it does not have to exist, and the real scratch key stays out of this guide. |
| `--text` | `comment2jira-uat dry run probe` - carries the suite's marker so a comment that escaped a dry run would be findable. |
| `--file` | A committed fixture under `tests/UAT/fixtures/`; see the fixture table in [README.md](README.md). |
| `--dry-run` | The flag under test. |

## Run it

From the repository root, under Git Bash:

```bash
uv run comment2jira --issue UAT-1 --text "comment2jira-uat dry run probe" --dry-run
```

## What to check

- Prints the plan and the ADF envelope, and exits 0:

  ```text
  Issue: UAT-1
  Deployment: cloud
  Attachments: none
  Body (ADF):
  {
    "version": 1,
    "type": "doc",
    "content": [
      {
        "type": "paragraph",
        "content": [
          {
            "type": "text",
            "text": "comment2jira-uat dry run probe"
          }
        ]
      }
    ]
  }
  ```

  On a Server/Data Center instance the same run prints `Deployment: dc` and a
  `Body (wiki):` block holding the string unchanged.

- A Markdown file is converted, not passed through. Exits 0, and the ADF carries
  a `heading` node, a `strong` mark and a `bulletList` - none of which appear in
  the source file:

  ```bash
  uv run comment2jira --issue UAT-1 --file tests/UAT/fixtures/uat-note.md --dry-run
  ```

- The attachment plan names every local reference with its size on disk and the
  filename it would be stored under, and the body shows the rewritten
  references. Exits 0:

  ```bash
  uv run comment2jira --issue UAT-1 --file tests/UAT/fixtures/uat-with-attachments.md --dry-run
  ```

  ```text
  Attachments:
    <repo-root>/tests/UAT/fixtures/uat-shot.png (75 bytes) -> uat-shot.png
    <repo-root>/tests/UAT/fixtures/uat-report.txt (44 bytes) -> uat-report.txt
  ```

  The path on the left is absolute and therefore machine-specific; the
  `(75 bytes) -> uat-shot.png` part is not.

- In that same body, the placeholder `<attachment-url>` stands in for each
  uploaded file (a real URL is only known after uploading), the remote reference
  `https://example.com/uat-shot.png` is left exactly as written, and the
  reference inside the fenced code block survives as the literal text
  `![ignored](uat-shot.png)` - fenced references are never uploaded.

- Nothing was written. The issue's comment count and attachment count are the
  same before and after a dry run:

  ```bash
  uv run python tests/UAT/jira_probe.py --action comment-count --env-file test.env
  uv run python tests/UAT/jira_probe.py --action attachment-count --env-file test.env
  ```

## Scripted equivalent

[`dry-run.sh`](dry-run.sh) runs this guide's own commands as a guided
walkthrough, asserting each check above:

```bash
./dry-run.sh          # step through it, one keypress per step
./dry-run.sh --auto   # run it unattended and print a verdict
```

See [README.md](README.md#scripted-runs) for the shared flags.

## Related automated coverage

`tests/integration/test_post_comment.py::TestDryRun` covers the no-write
guarantee against a live instance. `tests/test_cli.py` covers the dry-run plan
formatting, and `tests/test_attachments.py` covers reference extraction,
fenced-block exclusion and remote-target handling with no network.

## Cleanup

None. Every command in this guide is a dry run plus two read-only probes, so
the issue is left exactly as it was found.
