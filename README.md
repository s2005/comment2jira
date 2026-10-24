# comment2jira

Post Markdown comments to Jira work items from the command line.

One run posts exactly one comment. Local image and file references inside the
Markdown are uploaded to the issue as attachments first, and the references are
rewritten to point at them. The comment body is converted for whichever
deployment the instance turns out to be: Atlassian Document Format on Cloud
(`api/3`), wiki markup on Server/Data Center (`api/2`).

## Requirements

- Python 3.13 or newer
- [uv](https://docs.astral.sh/uv/)

## Install

Development setup:

```bash
uv sync
```

Install as a global tool:

```bash
uv tool install --from . comment2jira
```

## Quick start

```bash
# Post a Markdown file, uploading any local images it references
uv run comment2jira --issue PROJ-123 --file notes/review.md

# Post a short line of text exactly as written, with no conversion
uv run comment2jira --issue PROJ-123 --text "Deployed to staging."
```

## CLI reference

| Option | Required | Default | Description |
| --- | --- | --- | --- |
| `--issue` | yes | - | Jira issue key, for example `PROJ-123`. |
| `--file` | one of | - | Path to a Markdown file to convert and post. Mutually exclusive with `--text`. |
| `--text` | one of | - | Inline comment text, posted verbatim. Mutually exclusive with `--file`. |
| `--url` | no | - | Base URL of the Jira instance. Overrides `JIRA_URL`. |
| `--email` | no | - | Account email. Overrides `JIRA_EMAIL`. |
| `--token` | no | - | API token (Cloud) or personal access token (Server/DC). Overrides `JIRA_TOKEN`. |
| `--env-file` | no | see below | Path to the `.env` file holding credentials. Also read from `COMMENT2JIRA_ENV_FILE`. |
| `--auth` | no | `auto` | Auth scheme: `auto`, `basic` or `bearer`. |
| `--body-format` | no | `auto` | Comment body format: `auto`, `adf` or `wiki`. See below. |
| `--dry-run` | no | off | Print the plan and the converted body; perform no uploads and no post. |
| `-v` / `-vv` | no | `WARNING` | Raise stderr logging to `INFO` (`-v`) or `DEBUG` (`-vv`). |
| `--version` | no | - | Print the version and exit. |
| `--help` | no | - | Print usage and exit. |

Exactly one of `--file` or `--text` must be given; supplying both, or neither,
is a usage error.

### `--file` versus `--text`

`--file` runs the full pipeline: extract local references, upload them, rewrite
the references, convert the Markdown, post.

`--text` posts the string verbatim. Nothing is converted, so `**bold**` reaches
Jira as the literal characters `**bold**`, and nothing is uploaded. On Cloud the
string is wrapped in a single ADF paragraph, because the API will not accept a
bare string there.

### Attachments

In `--file` mode, `![alt](path)` and `[label](path)` references are collected.

- `http://` and `https://` targets are left alone and never uploaded.
- Relative paths resolve against the directory of the Markdown file.
- Two references with the same basename get `-1`, `-2` suffixes so neither
  overwrites the other on the issue.
- A reference to a file that does not exist produces a warning on stderr; the
  reference is left as written and the run continues.
- References inside fenced code blocks are ignored.

Surviving references are rewritten per deployment: `!stored-name|alt=alt!` and
`[label|^stored-name]` on Server/DC, `[label](content-url)` on Cloud.

### `--body-format`

By default (`auto`), the comment body is converted for whichever deployment
was detected: Atlassian Document Format on Cloud, wiki markup on Server/DC.
`--body-format` overrides that choice:

- `auto` (default): unchanged behavior, as described above.
- `wiki`: force wiki markup and post it through the `api/2` comment endpoint,
  regardless of the detected deployment. Attachment references use the
  Server/DC rewrite rules (`!stored-name|alt=alt!`), not the Cloud ones.
  **This is how to get images to render inline in a comment on Jira Cloud.**
  Cloud's ADF path (the `auto` default there) can only turn a local image
  into a plain link to the uploaded attachment, never an inline image; its
  `api/2` wiki path renders `!stored-name!` inline instead.
- `adf`: force Atlassian Document Format and post it through the `api/3`
  comment endpoint, regardless of the detected deployment. Rejected with an
  error on Server/DC, which has no `api/3` to post to.

The detected deployment is still reported accurately everywhere, including in
`--dry-run` output; `--body-format` only changes which body format and API
version are used to post it.

## Credentials

The tool reads `JIRA_URL`, `JIRA_EMAIL`, `JIRA_TOKEN` and `JIRA_AUTH`.

Resolution order, first hit wins:

1. Command-line flags: `--url`, `--email`, `--token` and `--auth`.
2. Environment variables.
3. A `.env` file.

A token passed as `--token` is visible to other processes on the machine, so
prefer `JIRA_TOKEN` or a `.env` file for anything but a throwaway.

The `.env` file is `--env-file` / `COMMENT2JIRA_ENV_FILE` when given, otherwise
`./.env`, otherwise the per-user location `~/.config/comment2jira/.env`
(`%APPDATA%\comment2jira\.env` on Windows). The first file that exists wins;
files are not merged. Naming a file with `--env-file` that does not exist is an
error rather than a silent fallback.

| Variable | Description |
| --- | --- |
| `JIRA_URL` | Base URL of the Jira instance. Required. |
| `JIRA_EMAIL` | Account email. Set it for Cloud basic auth; leave it empty for a Server/Data Center personal access token. |
| `JIRA_TOKEN` | API token (Cloud) or personal access token (Server/Data Center). |
| `JIRA_AUTH` | Auth scheme override: `auto`, `basic` or `bearer`. |
| `COMMENT2JIRA_ENV_FILE` | Path to the `.env` file to read. |

With `--auth auto` (the default), an email present selects HTTP basic and an
email absent selects a bearer token. See `.env.example` for a template.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Success |
| 1 | Operational failure: config error, missing file, HTTP or Jira error, interrupted |
| 2 | Authentication failure, or invalid command-line usage |
| 3 | Issue not found |

Code 2 covers two different things. Click emits it for a usage error such as
passing both `--file` and `--text`, and the tool emits it for an authentication
failure from Jira. A usage error prints Click's own message and the usage line;
an auth failure prints a line beginning `error:`.

## Examples

```bash
# Convert and post a Markdown file
uv run comment2jira --issue PROJ-123 --file docs/findings.md

# See what would be posted, without posting it
uv run comment2jira --issue PROJ-123 --file docs/findings.md --dry-run

# Post verbatim text with debug logging on stderr
uv run comment2jira --issue PROJ-123 --text "Rolled back." -vv

# Use a specific credentials file and force bearer auth
uv run comment2jira --issue PROJ-123 --file note.md --env-file ./dc.env --auth bearer

# Point one run at another instance, taking the token from the environment
uv run comment2jira --issue PROJ-123 --text "Smoke test passed." --url https://other-jira.example.com --token "$JIRA_TOKEN"
```

## Development

```bash
uv sync                      # install dependencies
uv run pytest                # run tests
uv run pytest --cov          # run tests with coverage
uv run ruff check --fix .    # lint and autofix
uv run ruff format .         # format
uv run mypy                  # type check
```

### Integration tests

`tests/integration/` runs the real CLI against a live Jira instance and reads
the issue back to check what landed. The suite is opt-in: it is skipped unless
pytest is given `--jira-env-file`, the path to an env file holding the
credentials. The path can be anywhere; tests are skipped with a reason when the
file is missing or lacks a required key.

```bash
cp test.env.example test.env   # then fill in the values
uv run pytest tests/integration -q --jira-env-file test.env
```

| Option | Description |
| --- | --- |
| `--jira-env-file PATH` | Env file with the live-Jira credentials and scratch issue. Omit it to skip the suite. |

Keep the file out of version control (`*.env` is gitignored). Its keys are
documented in `test.env.example`:

| Key | Required | Description |
| --- | --- | --- |
| `JIRA_URL` | yes | Base URL of the Jira instance under test. |
| `JIRA_EMAIL` | no | Account email, for Cloud basic auth. |
| `JIRA_TOKEN` | yes | API token or personal access token. |
| `JIRA_AUTH` | no | Auth scheme override. |
| `JIRA_TEST_ISSUE` | yes | Key of a scratch issue the suite may comment on and attach files to. |

The tests post real comments and upload real attachments to `JIRA_TEST_ISSUE`.
Point it at a throwaway issue, never at a live ticket. When `test.env` is
absent or missing a required key, the suite skips with that reason rather than
failing.

### UAT guides

`tests/UAT/` holds hand-run user-acceptance tests: one Markdown walkthrough per
command mode plus a self-checking script that runs the guide's own commands and
asserts every expectation. They read the same `test.env` and write to the same
scratch issue as the integration suite, so run them one at a time and never
alongside it.

```bash
./tests/UAT/text-mode.sh --auto   # one guide, unattended
./tests/UAT/run-all.sh            # the whole roster, sequentially
```

See [tests/UAT/README.md](tests/UAT/README.md) for the guide index, the shared
flags, and the fixture tables.

## Attribution

`src/comment2jira/markup/md_to_wiki.py` and
`src/comment2jira/markup/md_to_adf.py` are derived from
[mcp-atlassian](https://github.com/sooperset/mcp-atlassian), MIT licensed. Each
file carries its own attribution and source pointer.

## License

MIT
