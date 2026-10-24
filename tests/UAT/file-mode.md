# UAT: `comment2jira --file`

Manual user-acceptance test for `--file`: a Markdown file converted for whichever
deployment the instance turns out to be, and posted as one comment. This guide
covers conversion only - a fixture with no file references, so nothing is
uploaded. References and uploads are [`attachments.md`](attachments.md).

This guide **writes**: it posts one comment to the issue named by
`JIRA_TEST_ISSUE`, and removes it again in its last step.

## Prerequisites

The shared setup in [README.md](README.md): `uv` on `PATH`, a filled-in
`test.env` at the repository root pointing `JIRA_TEST_ISSUE` at a throwaway
issue, and the credentials exported into the shell -

```bash
set -a; . ./test.env; set +a
```

Run [`dry-run.md`](dry-run.md) first if the instance has not been reached yet
this session; it proves the credentials without writing anything.

## What this uses

| Flag | Value |
| --- | --- |
| `--issue` | `$JIRA_TEST_ISSUE` - the scratch issue key from `test.env`. Never spelled out here: it is environment-specific and the guides stay synthetic. |
| `--file` | `tests/UAT/fixtures/uat-note.md` - a heading, a paragraph with a `**bold**` run, and a two-item bullet list. It references no files, so the conversion is the only thing under test. |

## Run it

From the repository root, under Git Bash:

```bash
uv run comment2jira --issue "$JIRA_TEST_ISSUE" --file tests/UAT/fixtures/uat-note.md
```

## What to check

- Exits 0 and prints nothing. The fixture references no files, so there is no
  upload warning either.

- The comment reached Jira, converted. Reading it back shows the heading as a
  heading and the bold run as bold - and no surviving Markdown `#` or `**`:

  ```bash
  uv run python tests/UAT/jira_probe.py --action latest-comment --env-file test.env
  ```

  ```text
  h1. comment2jira-uat note

  This paragraph carries *bold* text posted by the comment2jira UAT suite.

  * first bullet
  * second bullet
  ```

  The read-back goes through `api/2`, which is why the body comes back as wiki
  markup on both deployments: on Server/Data Center that is what was posted, and
  on Cloud the ADF document is rendered back into wiki markup on the way out.
  Either way the assertion is the same - `**bold**` must be gone.

- Nothing was uploaded. The fixture holds no references, so the issue's
  attachment count is unchanged:

  ```bash
  uv run python tests/UAT/jira_probe.py --action attachment-count --env-file test.env
  ```

- Cleanup removes the comment and is idempotent: the first run reports at least
  one removal, a second reports none.

## Scripted equivalent

[`file-mode.sh`](file-mode.sh) runs this guide's own commands as a guided
walkthrough, asserting each check above and removing the comment in its last
step:

```bash
./file-mode.sh          # step through it, one keypress per step
./file-mode.sh --auto   # run it unattended and print a verdict
```

See [README.md](README.md#scripted-runs) for the shared flags.

## Related automated coverage

`tests/integration/test_post_comment.py::TestFileMode` posts the same shape
against a live instance and reads it back. `tests/test_md_to_wiki.py` and
`tests/test_md_to_adf.py` cover the two converters exhaustively with no network.

## Cleanup

The scripted walkthrough does this as its last step. To do it by hand, or to
clear up after an interrupted run:

```bash
uv run python tests/UAT/jira_probe.py --action cleanup --env-file test.env
```

It deletes only comments containing `comment2jira-uat` and attachments whose
name starts with `uat-`, so anything else on the scratch issue is left alone.
