# UAT: `comment2jira --text`

Manual user-acceptance test for `--text`: one short string posted to the scratch
issue exactly as written, with no Markdown conversion and no attachment upload.
This guide **writes** - it posts one comment to the issue named by
`JIRA_TEST_ISSUE` - and removes it again in its last step.

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
| `--text` | `comment2jira-uat text mode: **not bold** stays literal.` The `**not bold**` is the point of the test, and the `comment2jira-uat` marker is what cleanup matches on. |

## Run it

From the repository root, under Git Bash:

```bash
uv run comment2jira --issue "$JIRA_TEST_ISSUE" --text "comment2jira-uat text mode: **not bold** stays literal."
```

## What to check

- Exits 0 and prints nothing on success. `--text` is quiet: the only output on a
  clean run is an empty line.

- The comment reached Jira. Reading the issue back shows the string, and the
  `**not bold**` asterisks are still there - `--text` runs no converter, so
  Markdown emphasis arrives as literal characters:

  ```bash
  uv run python tests/UAT/jira_probe.py --action latest-comment --env-file test.env
  ```

  ```text
  comment2jira-uat text mode: **not bold** stays literal.
  ```

- Nothing was uploaded. `--text` never collects references, so the issue's
  attachment count is the same before and after:

  ```bash
  uv run python tests/UAT/jira_probe.py --action attachment-count --env-file test.env
  ```

- Cleanup removes the comment and is idempotent. The first run reports at least
  one removal, and running it a second time reports none - proving the first
  one was complete and that nothing carrying the marker is left behind:

  ```text
  removed comments: 2
  removed attachments: 0
  ```

## Scripted equivalent

[`text-mode.sh`](text-mode.sh) runs this guide's own commands as a guided
walkthrough, asserting each check above and removing the comment in its last
step:

```bash
./text-mode.sh          # step through it, one keypress per step
./text-mode.sh --auto   # run it unattended and print a verdict
```

See [README.md](README.md#scripted-runs) for the shared flags.

## Related automated coverage

`tests/integration/test_post_comment.py::TestTextMode` posts the same shape
against a live instance and reads it back. `tests/test_cli.py` covers the
`--text` branch and the ADF wrapping with no network.

## Cleanup

The scripted walkthrough does this as its last step. To do it by hand, or to
clear up after an interrupted run:

```bash
uv run python tests/UAT/jira_probe.py --action cleanup --env-file test.env
```

It deletes only comments containing `comment2jira-uat` and attachments whose
name starts with `uat-`, so anything else on the scratch issue is left alone.
