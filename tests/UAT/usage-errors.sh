#!/usr/bin/env bash
#
# usage-errors.sh - guided, self-checking walkthrough of usage-errors.md.
#
# Runs every check the guide describes for the invocations comment2jira refuses
# before it reaches Jira: each step explains what it exercises, echoes and runs
# the guide's exact command, shows the real output and the observed vs expected
# exit code, asserts the expectation, and waits for a keypress before the next
# step.
#
# Prerequisites - uv on PATH and the repository checked out:
#   uv sync
#
# No credentials, no scratch issue and no network. Unlike every other guide in
# this suite, this one deliberately does not load test.env: two of its steps
# prove what happens when no credentials can be resolved, and they run with the
# JIRA_* variables stripped from the child environment so an operator's own
# shell cannot change the outcome.
#
# Read-only: every command here is rejected before any request is made, so
# there is nothing to clean up.
#
# Exit codes: 0 all assertions passed, 1 an assertion failed, 2 bad invocation,
# 3 a prerequisite is missing, 130 interrupted.
#
# No `set -e`: every step below expects a non-zero exit code, so errexit would
# abort the walkthrough at step 1 (see common.sh).
set -uo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

# The values this guide names. All synthetic and published in README.md.
readonly NOTE_FIXTURE="tests/UAT/fixtures/uat-note.md"
readonly NO_CREDENTIALS_ENV="tests/UAT/fixtures/uat-no-credentials.env.example"
readonly MISSING_ENV="tests/UAT/fixtures/uat-does-not-exist.env"
readonly PROBE_TEXT="probe"

# Strips the ambient credentials so the two configuration steps see the same
# environment on every machine, whatever the operator has exported.
readonly UNSET_CREDENTIALS=(env -u JIRA_URL -u JIRA_EMAIL -u JIRA_TOKEN -u JIRA_AUTH)

STEP_TITLES=(
    "Preflight - uv, the fixtures, and a genuinely absent env file"
    "--file and --text together is a usage error"
    "Neither --file nor --text is a usage error"
    "A missing --issue is a usage error"
    "Credentials that cannot be resolved are a configuration error"
    "COMMENT2JIRA_ENV_FILE naming a missing file is an error, not a fallback"
    "--env-file naming a missing file must behave identically"
)
readonly LAST_STEP=$((${#STEP_TITLES[@]} - 1))

usage() {
    cat <<'USAGE'
usage-errors.sh - guided walkthrough of usage-errors.md

Usage:
  ./usage-errors.sh [options]

Options:
  --auto, --no-pause     Run every step back-to-back with no keypress prompt
  --stop-on-fail         Abort at the first failed step (default: run them all)
  --from-step N          Start at step N, skipping the earlier ones
  --only-step N          Run exactly one step
  --list-steps           Print the step index and exit
  --env-file PATH        Accepted for consistency with the other guides; this
                         one needs no credentials and never reads it
  --seed                 Accepted for consistency; there is no fixture to seed
  --cleanup              Accepted for consistency; this guide writes nothing
  --help                 Show this help and exit

Prerequisites: uv on PATH and the repository checked out. No credentials, no
scratch issue and no network. See README.md.

Nothing to clean: every command here is rejected before any request is made.
USAGE
}

# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------

step_0() {
    uat_step 0 "${STEP_TITLES[0]}"
    uat_explain "This guide needs almost nothing - which is the point, since it is the one that still runs when the Jira instance is down. What it does need is uv, the two committed fixtures, and the absence of the env file two steps expect to be missing: were someone to create that file, those steps would pass for the wrong reason."
    uat_expect "uv is on PATH, both fixtures are present, and $MISSING_ENV does not exist."

    uat_require_cmd "uv" "Install uv: https://docs.astral.sh/uv/getting-started/installation/"
    uat_pass "uv is on PATH"

    uat_require_file "$NOTE_FIXTURE" "The fixture is committed; check out tests/UAT/fixtures."
    uat_require_file "$NO_CREDENTIALS_ENV" "The fixture is committed; check out tests/UAT/fixtures."
    uat_pass "both fixtures are present"

    if [[ -e "$MISSING_ENV" ]]; then
        uat_fatal "$UAT_EXIT_PREREQ" \
            "$MISSING_ENV exists, but steps 5 and 6 need it absent.
    Remove it: rm $MISSING_ENV"
    fi
    uat_pass "$MISSING_ENV is absent, as steps 5 and 6 require"
}

step_1() {
    uat_step 1 "${STEP_TITLES[1]}"
    uat_explain "One run posts exactly one comment, so a command line naming two sources of that comment is ambiguous rather than merely redundant. Guessing which one the operator meant would post the wrong body; the command has to refuse."
    uat_expect "exit 2, with Click's own message '--file and --text are mutually exclusive' and the usage line."

    uat_run 2 "${UAT_BASE_CMD[@]}" --issue "$UAT_DRY_RUN_ISSUE" --file "$NOTE_FIXTURE" --text "$PROBE_TEXT"
    uat_assert_contains "--file and --text are mutually exclusive" "the conflict is named"
    uat_assert_contains "Try 'comment2jira --help' for help." "Click printed its usage line"
}

step_2() {
    uat_step 2 "${STEP_TITLES[2]}"
    uat_explain "The mirror image of step 1, and the reason both are checked: it would be easy to enforce the exclusion while letting an invocation with neither source through to a confusing failure much later, after credentials were resolved and the instance contacted."
    uat_expect "exit 2, with 'either --file or --text is required'."

    uat_run 2 "${UAT_BASE_CMD[@]}" --issue "$UAT_DRY_RUN_ISSUE"
    uat_assert_contains "either --file or --text is required" "the missing source is named"
}

step_3() {
    uat_step 3 "${STEP_TITLES[3]}"
    uat_explain "--issue is the one genuinely required option, and Click enforces it before the command's own body runs. Checking it here records that the same exit code 2 covers Click's built-in validation and the command's own mutual-exclusion guard."
    uat_expect "exit 2, with Click's \"Missing option '--issue'\"."

    uat_run 2 "${UAT_BASE_CMD[@]}" --text "$PROBE_TEXT"
    uat_assert_contains "Missing option '--issue'" "the missing required option is named"
}

step_4() {
    uat_step 4 "${STEP_TITLES[4]}"
    uat_explain "The line the exit codes draw: a command line the operator got wrong is exit 2, a command line that was fine but had nowhere to read credentials from is exit 1. Conflating the two would send someone hunting through their flags for a problem that is in their .env file. The JIRA_* variables are stripped and the env file points at a committed file holding only comments, so the result does not depend on what the operator has configured."
    uat_expect "exit 1, and a line beginning 'error:' naming the missing Jira URL - not Click's 'Error:'."

    uat_run 1 "${UNSET_CREDENTIALS[@]}" "COMMENT2JIRA_ENV_FILE=$NO_CREDENTIALS_ENV" \
        "${UAT_BASE_CMD[@]}" --issue "$UAT_DRY_RUN_ISSUE" --text "$PROBE_TEXT"
    uat_assert_contains "error: No Jira URL provided" "the configuration failure is reported, not a usage error"
    uat_assert_not_contains "Try 'comment2jira --help' for help." "this is not a usage error, so no usage line is printed"
    uat_assert_not_contains "Traceback" "the failure is reported, not raised"
}

step_5() {
    uat_step 5 "${STEP_TITLES[5]}"
    uat_explain "Naming an env file that does not exist has to be an error rather than a silent fall back to ./.env. A fallback would quietly post with whatever credentials happened to be lying around in the working directory - the exact opposite of what someone naming a file explicitly asked for."
    uat_expect "exit 1, with 'error: Env file not found:' naming the path that was asked for."

    uat_run 1 "${UNSET_CREDENTIALS[@]}" "COMMENT2JIRA_ENV_FILE=$MISSING_ENV" \
        "${UAT_BASE_CMD[@]}" --issue "$UAT_DRY_RUN_ISSUE" --text "$PROBE_TEXT"
    uat_assert_contains "error: Env file not found:" "the missing env file is reported"
    uat_assert_contains "uat-does-not-exist.env" "the message names the path that was asked for"
    uat_assert_not_contains "Traceback" "the failure is reported, not raised"
}

step_6() {
    uat_step 6 "${STEP_TITLES[6]}"
    uat_explain "--env-file and COMMENT2JIRA_ENV_FILE are documented as the same setting at two priorities, so they have to fail the same way. This step is step 5 with the flag substituted for the variable, and nothing else changed."
    uat_expect "exit 1, with the same 'error: Env file not found:' message step 5 produced, and no traceback."

    uat_run 1 "${UAT_BASE_CMD[@]}" --issue "$UAT_DRY_RUN_ISSUE" --text "$PROBE_TEXT" --env-file "$MISSING_ENV"
    uat_assert_contains "error: Env file not found:" "the missing env file is reported, as it is for the env var"
    uat_assert_not_contains "Traceback" "the failure is reported, not raised"
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
        uat_list_steps "usage-errors.sh"
        exit "$UAT_EXIT_OK"
    fi

    uat_resolve_range "$LAST_STEP"

    uat_banner "UAT walkthrough: comment2jira usage and configuration errors"
    printf '  guide  : usage-errors.md\n'
    printf '  env    : none - this guide needs no credentials\n'
    printf '  steps  : %s\n' "$(uat_step_range)"

    # No --seed: there is no fixture to provision, and uat_seed would reach for
    # credentials this guide deliberately does without.
    uat_run_steps

    # Nothing to clean: every command above is rejected before any request is
    # made, so this guide writes nothing anywhere.
    uat_summary
}

main "$@"
