# comment2jira UAT guides

Hand-run user-acceptance tests for the `comment2jira` CLI. Each guide is a pair:
a short Markdown walkthrough an operator runs by hand and eyeballs, and a
self-checking script that runs the guide's own commands and asserts every
expectation. They complement `tests/` rather than replacing it - the automated
suite proves the units and the integration suite proves the pipeline, while
these prove the command is usable by a person against a real instance.

Every guide runs against the live Jira instance named by `test.env` at the
repository root - the same file `tests/integration` reads, documented in
`test.env.example`. `test.env` is gitignored, so no real URL, account, token or
issue key appears anywhere in this directory: the guides name only the shell
variable, and `project.sh` resolves it at run time.

## The guides

| Command | Guide | Script | Needs |
| --- | --- | --- | --- |
| usage and configuration errors | [usage-errors.md](usage-errors.md) | [usage-errors.sh](usage-errors.sh) | `uv` only - no credentials, no network |
| `--dry-run` | [dry-run.md](dry-run.md) | [dry-run.sh](dry-run.sh) | `test.env`; reads the instance, writes nothing |
| `--text` | [text-mode.md](text-mode.md) | [text-mode.sh](text-mode.sh) | `test.env`; posts one comment, removes it |
| `--file` | [file-mode.md](file-mode.md) | [file-mode.sh](file-mode.sh) | `test.env`; posts one comment, removes it |
| `--file` with attachments | [attachments.md](attachments.md) | [attachments.sh](attachments.sh) | `test.env`; posts two comments and two attachments, removes all four |
| failures reported by Jira | [live-errors.md](live-errors.md) | [live-errors.sh](live-errors.sh) | `test.env`; writes nothing. Run last - it injects a bad token |

## Shared prerequisites

Once per session, from the repository root under Git Bash:

```bash
uv sync
cp test.env.example test.env
```

Fill in `test.env`, pointing `JIRA_TEST_ISSUE` at a **throwaway** issue. The
guides post real comments and upload real attachments to it. Then export the
credentials into the shell, which is what every guide's command blocks assume:

```bash
set -a; . ./test.env; set +a
```

That single line exports `JIRA_URL`, `JIRA_EMAIL`, `JIRA_TOKEN` and `JIRA_AUTH`
for the CLI to read as environment variables, and `JIRA_TEST_ISSUE` for the
guides to pass as `--issue`. The scripts do the same thing themselves, in
`project.sh`, so a scripted run needs nothing exported.

Do not run a guide from a shell with `set -x` enabled: shell tracing echoes
every expansion, which would print the token.

Teardown, at any time:

```bash
uv run python tests/UAT/jira_probe.py --action cleanup --env-file test.env
```

## Scripted runs

Each script steps through its guide, pausing for a keypress between steps:

```bash
./tests/UAT/text-mode.sh            # one keypress per step
./tests/UAT/text-mode.sh --auto     # unattended, prints a verdict
./tests/UAT/run-all.sh              # the whole roster, sequentially
```

A step prints why it exists, the command it is about to run, that command's real
output, the observed versus expected exit code, and one `[PASS]` or `[FAIL]`
line per assertion. The summary at the end reports steps run, steps skipped,
steps failed and assertion totals, and ends in `RESULT: PASS` or `RESULT: FAIL`.

Shared flags, accepted by every script:

| Flag | Meaning |
| --- | --- |
| `--auto`, `--no-pause` | Run every step back-to-back with no keypress prompt |
| `--stop-on-fail` | Abort at the first failed step instead of continuing |
| `--from-step N` | Start at step `N` |
| `--only-step N` | Run exactly one step |
| `--list-steps` | Print the step index and exit |
| `--env-file PATH` | Credentials file (default: `test.env` at the repository root) |
| `--seed` | Check the scratch issue is reachable before starting |
| `--cleanup` | Remove this suite's comments and attachments afterwards |
| `--keep-output` | Keep the files a run writes; no guide here writes any |
| `--help`, `-h` | Usage and exit 0 |

`UAT_AUTO=1` in the environment is equivalent to `--auto`.

Exit codes: `0` every assertion passed, `1` an assertion failed, `2` bad
invocation, `3` a missing prerequisite (the message names the fix), `130`
interrupted.

## Run one at a time

Every guide writes to the same scratch issue, and nothing serializes access to
it. Two guides running concurrently would see each other's comments in their
before-and-after counts, and one guide's cleanup would delete the other's
comments mid-run. Run them one at a time, and never alongside
`uv run pytest tests/integration --jira-env-file <path>`, which writes to the same issue.

`run-all.sh` is a plain sequential loop for exactly this reason.

## Skipped steps

A step that cannot run reports `[SKIP]` with its reason. A skip never changes
the exit code, but it moves the step out of `steps run` and qualifies the
verdict as `RESULT: PASS (N step(s) skipped)`, so a run where little actually
happened cannot read as a clean pass.

## Fixture values

Every value the guides name is synthetic. Nothing here is a real issue key,
account, host or credential.

| Value | Meaning |
| --- | --- |
| `UAT-1` | A synthetic issue key used only by `--dry-run` steps, which never contact the issue. |
| `UATNOPE-999999` | A synthetic key in a project that does not exist, used to provoke the not-found path. |
| `uat-invalid-token` | A synthetic token value, exported for one command, to provoke a rejection. |
| `comment2jira-uat` | The marker every comment this suite posts contains. Cleanup matches on it. |
| `uat-` | The prefix every attachment this suite uploads carries. Cleanup matches on it. |
| `$JIRA_TEST_ISSUE` | The real scratch issue key, read from `test.env` at run time and never written down here. |

Committed fixtures, under `fixtures/`:

| File | Contents | Used by |
| --- | --- | --- |
| `uat-note.md` | A heading, a paragraph with a `**bold**` run, a two-item list. No references. | dry-run, file-mode, usage-errors |
| `uat-with-attachments.md` | An image reference, a file link, a remote URL, and a reference inside a fenced code block - all four classifications. | dry-run, attachments |
| `uat-missing-ref.md` | One image reference to `uat-gone.png`, which is deliberately absent. | attachments |
| `uat-shot.png` | A 75-byte 1x1 transparent PNG. The image `uat-with-attachments.md` references. | attachments |
| `uat-report.txt` | A 44-byte text file. The link target `uat-with-attachments.md` references. | attachments |
| `uat-no-credentials.env.example` | An env file holding only comments, so credential resolution finds nothing regardless of the operator's own `.env`. | usage-errors |

Two names are deliberately **absent** and must stay that way:
`fixtures/uat-gone.png` and `fixtures/uat-does-not-exist.env`. Creating either
would make a step pass for the wrong reason, so the preflight of the guide that
needs it absent checks and exits 3 if it appears.

## The read-back helper

`jira_probe.py` reads the scratch issue back and removes this suite's own
writes. The CLI only writes, so a step asserting on an exit code alone would
prove nothing about what actually landed; every write in this suite is paired
with a read through the probe, the same way `tests/integration` does it.

```bash
uv run python tests/UAT/jira_probe.py --action <action> --env-file test.env
```

| Action | Prints |
| --- | --- |
| `deployment` | `cloud` or `dc` |
| `comment-count` | The number of comments on the issue |
| `attachment-count` | The number of attachments on the issue |
| `latest-comment` | The newest comment, flattened to plain text |
| `attachments` | One attachment filename per line |
| `cleanup` | How many comments and attachments it removed |

`--issue KEY` overrides the `JIRA_TEST_ISSUE` default. Cleanup only removes
comments containing `comment2jira-uat` and attachments named `uat-*`, so
anything else on the scratch issue is left alone, and it is idempotent.

## Adding a guide

1. Write `<command>.md` first and completely: prerequisites, a flag table, the
   exact command, one concrete expectation per bullet including the failure
   modes, the scripted-equivalent link, and a cleanup section if it writes.
   No placeholders, and only synthetic values.
2. Run every command in it and paste the real output.
3. Transcribe it into `<command>.sh` - one step per `## What to check` bullet,
   numbered from 0, with step 0 as the preflight. Source `common.sh`; never
   copy it and never redefine a `uat_*` helper.
4. Add a row to the guide table above, any new value to the fixture tables, and
   an entry to the `run-all.sh` roster in a position that respects its
   dependencies.
5. Record the exec bit in the index: `git update-index --chmod=+x tests/UAT/<command>.sh`.
   A local `chmod +x` commits nothing on Windows.
6. Run it: `./tests/UAT/<command>.sh --auto` must reach the summary, and the
   verdict must match what the guide claims.

`tests/test_uat_scripts.py` guards the conventions above.
