# UAT: `comment2jira` usage and configuration errors

Manual user-acceptance test for everything the command refuses before it reaches
Jira: a contradictory or incomplete invocation, and credentials it cannot
resolve. Every case here has a documented exit code, and telling them apart is
the whole point - exit 2 means the operator got the command line wrong, exit 1
means the command line was fine but the configuration was not.

Nothing in this guide contacts Jira. It needs no credentials, no scratch issue
and no network, and it writes nothing.

## Prerequisites

`uv` on `PATH` and the repository checked out. That is all - unlike every other
guide in [README.md](README.md), this one deliberately does **not** want
`test.env` sourced into the shell, because two of its cases prove what happens
when no credentials can be found. Run it in a fresh shell, or unset the
variables first:

```bash
unset JIRA_URL JIRA_EMAIL JIRA_TOKEN JIRA_AUTH COMMENT2JIRA_ENV_FILE
```

## What this uses

| Flag | Value |
| --- | --- |
| `--issue` | `UAT-1` - a synthetic key. No case here gets far enough to resolve an issue. |
| `--file` | `tests/UAT/fixtures/uat-note.md` - a real, committed file, so a rejection is never about the file being missing. |
| `--text` | `probe` - a short string, present only to make the invocation contradictory. |
| `--env-file` | `tests/UAT/fixtures/uat-does-not-exist.env` - deliberately absent. |
| `COMMENT2JIRA_ENV_FILE` | `tests/UAT/fixtures/uat-no-credentials.env.example` - a real, committed file that holds only comments, so credential resolution finds nothing without depending on whether the operator has a `.env`. |

## Run it

From the repository root, under Git Bash:

```bash
uv run comment2jira --issue UAT-1 --file tests/UAT/fixtures/uat-note.md --text probe
```

## What to check

- `--file` and `--text` together is a usage error. Click prints its own message
  and the usage line, and exits 2:

  ```text
  Error: --file and --text are mutually exclusive
  ```

- Neither `--file` nor `--text` is the same kind of error, also exit 2:

  ```bash
  uv run comment2jira --issue UAT-1
  ```

  ```text
  Error: either --file or --text is required
  ```

- A missing `--issue` is caught by Click itself, again exit 2:

  ```bash
  uv run comment2jira --text probe
  ```

  ```text
  Error: Missing option '--issue'.
  ```

- Credentials that cannot be resolved are a configuration error, not a usage
  error: exit 1, and a line beginning `error:` rather than Click's `Error:`:

  ```bash
  env -u JIRA_URL -u JIRA_EMAIL -u JIRA_TOKEN -u JIRA_AUTH COMMENT2JIRA_ENV_FILE=tests/UAT/fixtures/uat-no-credentials.env.example uv run comment2jira --issue UAT-1 --text probe
  ```

  ```text
  error: No Jira URL provided (use --url, JIRA_URL, or a .env file).
  ```

- An env file named through `COMMENT2JIRA_ENV_FILE` that does not exist is an
  error, not a silent fallback to `./.env`. Exit 1:

  ```bash
  env -u JIRA_URL -u JIRA_EMAIL -u JIRA_TOKEN -u JIRA_AUTH COMMENT2JIRA_ENV_FILE=tests/UAT/fixtures/uat-does-not-exist.env uv run comment2jira --issue UAT-1 --text probe
  ```

  ```text
  error: Env file not found: tests/UAT/fixtures/uat-does-not-exist.env
  ```

  The path is echoed in the platform's own separator form, so it appears with
  backslashes on Windows.

- The `--env-file` flag must behave identically. It is documented as the
  higher-priority form of the same setting, so naming a file that does not exist
  must produce the same message and the same exit code 1:

  ```bash
  uv run comment2jira --issue UAT-1 --text probe --env-file tests/UAT/fixtures/uat-does-not-exist.env
  ```

  ```text
  error: Env file not found: tests/UAT/fixtures/uat-does-not-exist.env
  ```

## Scripted equivalent

[`usage-errors.sh`](usage-errors.sh) runs this guide's own commands as a guided
walkthrough, asserting each check above:

```bash
./usage-errors.sh          # step through it, one keypress per step
./usage-errors.sh --auto   # run it unattended and print a verdict
```

See [README.md](README.md#scripted-runs) for the shared flags.

## Related automated coverage

`tests/test_cli.py::TestMutualExclusion` covers the two usage errors, and
`tests/test_config.py` covers credential resolution including the missing-env-file
case - but only through `resolve_credentials()` directly, with a `Path` value.
`tests/test_cli.py::TestEnvFileOption` drives `--env-file` through the Click
command with a value, covering the missing-file message and exit code, an
existing file resolving credentials, and the `COMMENT2JIRA_ENV_FILE` control.

## Cleanup

None. Every command in this guide is rejected before any request is made, so
nothing is written anywhere.
