#!/usr/bin/env bash
#
# live-errors.sh - guided, self-checking walkthrough of live-errors.md.
#
# Runs every check the guide describes for the failures comment2jira can only
# discover by asking Jira: each step explains what it exercises, echoes and runs
# the guide's exact command, shows the real output and the observed vs expected
# exit code, asserts the expectation, and waits for a keypress before the next
# step.
#
# Prerequisites - the shared setup in README.md:
#   uv sync
#   cp test.env.example test.env      # then fill it in, JIRA_TEST_ISSUE included
#
# The credentials are loaded from test.env by project.sh, which is the scripted
# form of the guide's own `set -a; . ./test.env; set +a` line.
#
# Writes nothing: every step is either refused by Jira before a comment is
# created, or a read-only probe. The posted text still carries the
# comment2jira-uat marker, so a comment that somehow escaped would be found by
# `--action cleanup` like any other.
#
# Run this guide last. It deliberately supplies a bad token, so the final step
# puts the real one back and confirms the instance was fine all along.
#
# Exit codes: 0 all assertions passed, 1 an assertion failed, 2 bad invocation,
# 3 a prerequisite is missing, 130 interrupted.
#
# No `set -e`: steps 1 and 2 expect a non-zero exit code, so errexit would abort
# the walkthrough at the first of them (see common.sh).
set -uo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

# The values this guide names. UAT_UNKNOWN_ISSUE is synthetic and published in
# README.md; the real scratch key is read from test.env into UAT_ISSUE.
readonly BAD_TOKEN="uat-invalid-token"
readonly PROBE_TEXT="comment2jira-uat live error probe"

STEP_TITLES=(
    "Preflight - uv, test.env, and a reachable Jira instance"
    "An unresolvable issue key exits 3 and quotes Jira's own message"
    "A token the instance rejects fails cleanly, not with a traceback"
    "Control - with the real token the same issue reads normally"
)
readonly LAST_STEP=$((${#STEP_TITLES[@]} - 1))

usage() {
    cat <<'USAGE'
live-errors.sh - guided walkthrough of live-errors.md

Usage:
  ./live-errors.sh [options]

Options:
  --auto, --no-pause     Run every step back-to-back with no keypress prompt
  --stop-on-fail         Abort at the first failed step (default: run them all)
  --from-step N          Start at step N, skipping the earlier ones
  --only-step N          Run exactly one step
  --list-steps           Print the step index and exit
  --env-file PATH        Credentials file (default: test.env at the repo root)
  --seed                 Check the scratch issue is reachable before starting
  --cleanup              Remove this suite's comments and attachments afterwards
  --help                 Show this help and exit

Prerequisites: uv on PATH and a filled-in test.env at the repository root. See
README.md.

Writes nothing: every step is refused by Jira before a comment is created, or is
a read-only probe. Run this guide last - it supplies a bad token on purpose, and
its final step confirms the instance was fine all along.

Note: against a Cloud instance, exit code 2 (authentication failure) is not
reachable - Cloud answers an unauthenticated caller with 404, not 401. Step 2
asserts the code the detected deployment actually produces and says so.
USAGE
}

# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------

step_0() {
    uat_step 0 "${STEP_TITLES[0]}"
    uat_explain "Two of the steps below assert that a request FAILED, which is a claim worth nothing unless a correctly-formed request would have succeeded. Establishing that here - real credentials, reachable instance - is what makes those failures meaningful rather than a broken environment reported as a pass."
    uat_expect "uv is on PATH, $UAT_ENV_FILE carries JIRA_URL, JIRA_TOKEN and JIRA_TEST_ISSUE, and the instance reports a deployment type."

    uat_require_cmd "uv" "Install uv: https://docs.astral.sh/uv/getting-started/installation/"
    uat_pass "uv is on PATH"

    _uat_load_env
    uat_pass "$UAT_ENV_FILE supplies JIRA_URL, JIRA_TOKEN and JIRA_TEST_ISSUE"

    uat_pass "Jira reports deployment: $(_uat_deployment)"
}

step_1() {
    uat_step 1 "${STEP_TITLES[1]}"
    uat_explain "The commonest live failure by far: a mistyped or stale key in a script. It has its own exit code precisely so a caller can tell it apart from a network problem, and Jira's own explanation is passed through rather than replaced, because 'does not exist' and 'you cannot see it' are the same HTTP status and only the operator can tell which they are looking at."
    uat_expect "exit 3, with an 'error:' line naming the issue key and quoting Jira's message, and no traceback."

    _uat_load_env
    uat_run 3 "${UAT_BASE_CMD[@]}" --issue "$UAT_UNKNOWN_ISSUE" --text "$PROBE_TEXT"
    uat_assert_contains "error: Not found or no permission" "the not-found failure is reported"
    uat_assert_contains "$UAT_UNKNOWN_ISSUE" "the message names the key that could not be resolved"
    uat_assert_contains "Issue does not exist or you do not have permission to see it." "Jira's own explanation is passed through"
    uat_assert_not_contains "Traceback" "the failure is reported, not raised"
}

step_2() {
    uat_step 2 "${STEP_TITLES[2]}"
    uat_explain "A rejected credential has to surface as a readable line, not a stack trace, because it is the failure an operator hits most often on their first run. The exit code, though, is the instance's decision rather than the command's: Server/DC answers 401 and the command maps that to 2, while Cloud answers 404 to any caller it has not authenticated and the command maps that to 3."
    uat_expect "an 'error:' line, no traceback, and the exit code the detected deployment produces - 2 on Server/Data Center, 3 on Cloud."

    _uat_load_env
    local deployment expected
    deployment="$(_uat_deployment)"
    if [[ "$deployment" == "cloud" ]]; then
        expected=3
        uat_note "Cloud will not confirm an issue exists to an unauthenticated caller, so a rejected token arrives as 404 and exits 3. Exit code 2 is therefore NOT reachable against this instance and this suite does not verify it; tests/test_cli.py::TestExitCodeMapping covers the mapping without a network."
    else
        expected=2
        uat_note "Server/Data Center answers 401 for a rejected token, which the command maps to exit 2."
    fi

    uat_run "$expected" env "JIRA_TOKEN=$BAD_TOKEN" \
        "${UAT_BASE_CMD[@]}" --issue "$UAT_UNKNOWN_ISSUE" --text "$PROBE_TEXT"
    uat_assert_contains "error:" "the rejection is reported as an error line"
    uat_assert_not_contains "Traceback" "the failure is reported, not raised"
    uat_assert_not_contains "$BAD_TOKEN" "the token is not echoed back in the error"
}

step_3() {
    uat_step 3 "${STEP_TITLES[3]}"
    uat_explain "The control for the two steps above. Both of them assert a failure, and a failure proves nothing unless the same environment can still succeed - otherwise a down instance or an expired real token would make this guide pass while telling the operator nothing. Reading the scratch issue is the smallest authenticated success available, and it writes nothing."
    uat_expect "exit 0 and a comment count, using the real token from $UAT_ENV_FILE."

    _uat_load_env
    uat_run 0 "${UAT_PROBE_CMD[@]}" --action comment-count
    uat_assert_matches "^[0-9]+$" "the scratch issue read back a comment count - the credentials and the instance are fine"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

main() {
    uat_init

    local arg
    for arg in "$@"; do
        if [[ "$arg" == "--help" || "$arg" == "-h" ]]; then
            usage
            exit "$UAT_EXIT_OK"
        fi
    done

    uat_parse_common_args "$@"
    if [[ ${#UAT_REST[@]} -gt 0 ]]; then
        uat_fatal "$UAT_EXIT_USAGE" "unknown argument: ${UAT_REST[0]} (see --help)"
    fi

    if [[ "$UAT_LIST_ONLY" -eq 1 ]]; then
        uat_list_steps "live-errors.sh"
        exit "$UAT_EXIT_OK"
    fi

    uat_resolve_range "$LAST_STEP"

    uat_banner "UAT walkthrough: comment2jira failures reported by Jira"
    printf '  guide  : live-errors.md\n'
    printf '  env    : %s\n' "$UAT_ENV_FILE"
    printf '  steps  : %s\n' "$(uat_step_range)"

    [[ "$UAT_DO_SEED" -eq 1 ]] && uat_seed

    uat_run_steps

    # Nothing to clean: every step above is refused by Jira before a comment is
    # created, or reads only. --cleanup still works, and removes anything an
    # earlier guide left behind after an interrupted run.
    [[ "$UAT_DO_CLEANUP" -eq 1 ]] && uat_cleanup

    uat_summary
}

main "$@"
