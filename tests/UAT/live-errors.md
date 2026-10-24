# UAT: `comment2jira` failures reported by Jira

Manual user-acceptance test for the failures the command can only discover by
asking Jira: an issue key that does not resolve, and a token the instance will
not accept. Both must be reported as a readable `error:` line with a documented
exit code, never as a traceback and never as a silent success.

This guide **writes nothing**. Every step is either rejected by Jira or a
read-only probe.

## Prerequisites

The shared setup in [README.md](README.md): `uv` on `PATH`, a filled-in
`test.env` at the repository root, and the credentials exported into the shell -

```bash
set -a; . ./test.env; set +a
```

Run this guide last. It deliberately supplies a bad token, so a failure here
after the earlier guides passed points at the injected fault rather than at the
environment - and the last step confirms exactly that.

## What this uses

| Flag | Value |
| --- | --- |
| `--issue` | `UATNOPE-999999` - a synthetic key in a project that does not exist. Chosen to be unresolvable on any instance. |
| `--issue` | `$JIRA_TEST_ISSUE` - the real scratch issue, used only by the final control step. |
| `--text` | `comment2jira-uat live error probe` - carries the suite's marker, so a comment that escaped one of these failures would be findable and removable. |
| `JIRA_TOKEN` | `uat-invalid-token` - a synthetic value, exported for one command only, to make the instance reject the request. |

## Run it

From the repository root, under Git Bash:

```bash
uv run comment2jira --issue UATNOPE-999999 --text "comment2jira-uat live error probe"
```

## What to check

- An unresolvable issue key exits 3 and says why, quoting Jira's own message:

  ```text
  error: Not found or no permission for POST /rest/api/3/issue/UATNOPE-999999/comment; Issue does not exist or you do not have permission to see it.
  ```

  The path is `api/3` on Cloud and `api/2` on Server/Data Center.

- A token the instance will not accept also fails, reports an `error:` line, and
  does not raise:

  ```bash
  JIRA_TOKEN=uat-invalid-token uv run comment2jira --issue UATNOPE-999999 --text "comment2jira-uat live error probe"
  ```

  The exit code depends on the deployment, and this is the one place the two
  differ in a way that matters:

  | Deployment | HTTP | Exit | Why |
  | --- | --- | --- | --- |
  | Server/Data Center | 401 | 2 | The instance says the credentials are wrong. |
  | Cloud | 404 | 3 | Atlassian Cloud will not confirm that an issue exists to a caller it has not authenticated, so a rejected token is indistinguishable from a missing issue. |

  Against a Cloud instance, exit code 2 is therefore **not reachable** and this
  suite does not verify it. `tests/test_cli.py::TestExitCodeMapping` covers the
  mapping itself without a network.

- Nothing above was a real problem with the environment. With the token put
  back, the same scratch issue reads normally:

  ```bash
  uv run python tests/UAT/jira_probe.py --action comment-count --env-file test.env
  ```

  A number, and exit 0.

## Scripted equivalent

[`live-errors.sh`](live-errors.sh) runs this guide's own commands as a guided
walkthrough, asserting each check above:

```bash
./live-errors.sh          # step through it, one keypress per step
./live-errors.sh --auto   # run it unattended and print a verdict
```

See [README.md](README.md#scripted-runs) for the shared flags.

## Related automated coverage

`tests/integration/test_post_comment.py::TestErrorPaths` posts to an
unresolvable key against a live instance. `tests/test_client.py` covers the
status-to-exception mapping (401 to `AuthError`, 403/404 to `NotFoundError`) and
`tests/test_cli.py::TestExitCodeMapping` covers the exception-to-exit-code
mapping, both with no network.

## Cleanup

None. Every command here is refused by Jira before a comment is created, and the
final step only reads. The suite's `comment2jira-uat` marker is still on the
probe text so that, if a future change ever let one of these through, the
comment would be found and removed by:

```bash
uv run python tests/UAT/jira_probe.py --action cleanup --env-file test.env
```
