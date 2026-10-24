# UAT: `comment2jira --file` with attachments

Manual user-acceptance test for the attachment half of `--file`: local image and
file references are uploaded to the issue first, and the references in the
comment body are rewritten to point at what was uploaded. Remote references and
references inside fenced code blocks are left alone, and a reference to a file
that does not exist warns without failing the run.

This guide **writes**: it posts two comments and uploads two attachments to the
issue named by `JIRA_TEST_ISSUE`, and removes all four in its last step.

## Prerequisites

The shared setup in [README.md](README.md): `uv` on `PATH`, a filled-in
`test.env` at the repository root pointing `JIRA_TEST_ISSUE` at a throwaway
issue, and the credentials exported into the shell -

```bash
set -a; . ./test.env; set +a
```

Run [`dry-run.md`](dry-run.md) first if the instance has not been reached yet
this session; its attachment step shows the same plan without uploading it.

## What this uses

| Flag | Value |
| --- | --- |
| `--issue` | `$JIRA_TEST_ISSUE` - the scratch issue key from `test.env`. Never spelled out here: it is environment-specific and the guides stay synthetic. |
| `--file` | `tests/UAT/fixtures/uat-with-attachments.md` - one image reference, one file link, one remote URL, and one reference inside a fenced code block. All four classifications in one fixture. |
| `--file` | `tests/UAT/fixtures/uat-missing-ref.md` - a single image reference to `uat-gone.png`, which is deliberately absent. |

## Run it

From the repository root, under Git Bash:

```bash
uv run comment2jira --issue "$JIRA_TEST_ISSUE" --file tests/UAT/fixtures/uat-with-attachments.md
```

## What to check

- Exits 0 and prints nothing. Both referenced files exist, so there is no
  warning.

- Both files are now attachments on the issue, stored under their own basenames:

  ```bash
  uv run python tests/UAT/jira_probe.py --action attachments --env-file test.env
  ```

  ```text
  uat-report.txt
  uat-shot.png
  ```

- The comment body no longer holds the relative paths. Each local reference has
  been rewritten to point at the uploaded attachment, while the remote reference
  and the fenced one are untouched:

  ```bash
  uv run python tests/UAT/jira_probe.py --action latest-comment --env-file test.env
  ```

  ```text
  comment2jira-uat attachment check.

  [screenshot|<jira-base-url>/rest/api/2/attachment/content/10001]

  [the report|<jira-base-url>/rest/api/2/attachment/content/10002]

  [upstream docs|https://example.com/uat-shot.png]

  {noformat}![ignored](uat-shot.png){noformat}
  ```

  The base URL and the numeric attachment ids are environment-specific; the
  `/rest/api/2/attachment/content/` path is not. What matters is that
  `![screenshot](uat-shot.png)` and `[the report](uat-report.txt)` are gone,
  that `https://example.com/uat-shot.png` survived exactly as written, and that
  the fenced `![ignored](uat-shot.png)` is still literal text. Match the
  references with their alt and label text: the bare `(uat-shot.png)` still
  occurs inside the fenced block, which is exactly the part that must not be
  rewritten.

- A reference to a file that does not exist warns on stderr and the run still
  succeeds, uploading nothing and leaving the reference as written:

  ```bash
  uv run comment2jira --issue "$JIRA_TEST_ISSUE" --file tests/UAT/fixtures/uat-missing-ref.md
  ```

  ```text
  WARNING - comment2jira - Referenced file not found, skipping: <repo-root>/tests/UAT/fixtures/uat-gone.png
  ```

  Exit code 0, the attachment count unchanged, and the comment carries
  `![gone|uat-gone.png]` - the reference left as it was.

- Cleanup removes both comments and both attachments, and is idempotent: the
  first run reports the removals, a second reports none.

## Scripted equivalent

[`attachments.sh`](attachments.sh) runs this guide's own commands as a guided
walkthrough, asserting each check above and removing everything in its last
step:

```bash
./attachments.sh          # step through it, one keypress per step
./attachments.sh --auto   # run it unattended and print a verdict
```

See [README.md](README.md#scripted-runs) for the shared flags.

## Related automated coverage

`tests/integration/test_post_comment.py::TestAttachments` uploads and reads back
against a live instance, including the missing-file case.
`tests/test_attachments.py` covers extraction, remote classification,
fenced-block exclusion, same-basename suffixing and the two rewrite forms with
no network.

## Cleanup

The scripted walkthrough does this as its last step. To do it by hand, or to
clear up after an interrupted run:

```bash
uv run python tests/UAT/jira_probe.py --action cleanup --env-file test.env
```

It deletes only comments containing `comment2jira-uat` and attachments whose
name starts with `uat-`, so anything else on the scratch issue is left alone.
