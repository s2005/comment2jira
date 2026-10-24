#!/usr/bin/env bash
#
# text-mode.sh - guided, self-checking walkthrough of text-mode.md.
#
# Runs every check the guide describes for `comment2jira --text`: each step
# explains what it exercises, echoes and runs the guide's exact command, shows
# the real output and the observed vs expected exit code, asserts the
# expectation, and waits for a keypress before the next step.
#
# Prerequisites - the shared setup in README.md:
#   uv sync
#   cp test.env.example test.env      # then fill it in, JIRA_TEST_ISSUE included
#
# The credentials are loaded from test.env by project.sh, which is the scripted
# form of the guide's own `set -a; . ./test.env; set +a` line.
#
# This guide WRITES: step 1 posts one comment to the scratch issue named by
# JIRA_TEST_ISSUE. The last step deletes it again, matching on the
# comment2jira-uat marker so nothing else on the issue is touched. Cleanup is an
# ordinary step rather than a trap, so an interrupted run leaves the comment in
# place to be inspected; `./text-mode.sh --cleanup` removes it afterwards.
#
# Exit codes: 0 all assertions passed, 1 an assertion failed, 2 bad invocation,
# 3 a prerequisite is missing, 130 interrupted.
#
# No `set -e`: uat_run captures each exit code itself, and errexit would abort
# the walkthrough rather than let it report every problem (see common.sh).
set -uo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

# The string this guide posts. It carries the suite's marker so cleanup can find
# it, and a Markdown emphasis run that must survive untouched.
readonly TEXT_BODY="comment2jira-uat text mode: **not bold** stays literal."

STEP_TITLES=(
    "Preflight - uv, test.env, and a reachable scratch issue"
    "Post one line of text to the scratch issue"
    "The comment reached Jira with its Markdown markers intact"
    "Nothing was uploaded alongside it"
    "Cleanup - remove the comment this guide posted"
)
readonly LAST_STEP=$((${#STEP_TITLES[@]} - 1))

usage() {
    cat <<'USAGE'
text-mode.sh - guided walkthrough of text-mode.md

Usage:
  ./text-mode.sh [options]

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

Prerequisites: uv on PATH and a filled-in test.env at the repository root, with
JIRA_TEST_ISSUE pointing at a throwaway issue. See README.md.

This guide writes: it posts one comment to that issue. The last step deletes it
again, matching on the comment2jira-uat marker, so nothing else on the issue is
touched. After an interrupted run, clear up with:
  uv run python tests/UAT/jira_probe.py --action cleanup --env-file test.env
USAGE
}

# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------

step_0() {
    uat_step 0 "${STEP_TITLES[0]}"
    uat_explain "Everything below needs uv, a filled-in test.env, and a scratch issue this account may comment on. Checking all three once here turns a missing prerequisite into one clear message instead of four confusing step failures - and it fails before anything is posted."
    uat_expect "uv is on PATH, $UAT_ENV_FILE carries JIRA_URL, JIRA_TOKEN and JIRA_TEST_ISSUE, and the scratch issue's comments can be read."

    uat_require_cmd "uv" "Install uv: https://docs.astral.sh/uv/getting-started/installation/"
    uat_pass "uv is on PATH"

    _uat_load_env
    uat_pass "$UAT_ENV_FILE supplies JIRA_URL, JIRA_TOKEN and JIRA_TEST_ISSUE"

    uat_run_quiet "${UAT_PROBE_CMD[@]}" --action comment-count
    if [[ "$UAT_RC" -ne 0 ]]; then
        printf '%s\n' "$UAT_OUT"
        uat_fatal "$UAT_EXIT_PREREQ" \
            "the scratch issue named by JIRA_TEST_ISSUE cannot be read (exit $UAT_RC).
    Point it at a throwaway issue this account can see, then retry."
    fi
    uat_pass "the scratch issue is readable and holds $UAT_OUT comment(s)"
}

step_1() {
    uat_step 1 "${STEP_TITLES[1]}"
    uat_explain "The command under test. --text is the escape hatch for a one-line note: no file to read, no references to collect, no converter to run. On Cloud the string still has to be wrapped in an ADF paragraph, because the api/3 endpoint refuses a bare string - so a successful exit here already proves that wrapping happened."
    uat_expect "exit 0, and no output: --text prints nothing on a clean run."

    _uat_load_env
    uat_run 0 "${UAT_BASE_CMD[@]}" --issue "$UAT_ISSUE" --text "$TEXT_BODY"
    uat_assert_not_contains "error:" "no error line was printed"
    uat_assert_not_contains "WARNING" "no warning was printed"
}

step_2() {
    uat_step 2 "${STEP_TITLES[2]}"
    uat_explain "An exit code proves the request was accepted, not that the right thing landed. Reading the newest comment back is what proves it - and it is the only way to check the promise that makes --text worth having: the string is posted verbatim, so Markdown emphasis arrives as the literal asterisks a converter would have eaten."
    uat_expect "exit 0, and the newest comment on the issue is the string from step 1, '**not bold**' asterisks included."

    _uat_load_env
    uat_run 0 "${UAT_PROBE_CMD[@]}" --action latest-comment
    uat_assert_contains "comment2jira-uat text mode:" "the newest comment is the one this guide posted"
    uat_assert_contains '**not bold**' "the emphasis markers survived - nothing converted them"
    uat_assert_contains "stays literal." "the rest of the string arrived intact"
}

step_3() {
    uat_step 3 "${STEP_TITLES[3]}"
    uat_explain "--text skips reference extraction entirely, so it must never upload anything. This is worth asserting separately because the file path and the text path share a client: a mistake that routed --text through the upload code would still post a correct-looking comment."
    uat_expect "exit 0, and the issue's attachment count is unchanged by a --text post."

    _uat_load_env
    local before after
    before="$("${UAT_PROBE_CMD[@]}" --action attachment-count)"
    uat_note "before the run: $before attachment(s)"

    uat_run 0 "${UAT_BASE_CMD[@]}" --issue "$UAT_ISSUE" --text "$TEXT_BODY"

    after="$("${UAT_PROBE_CMD[@]}" --action attachment-count)"
    if [[ "$after" == "$before" ]]; then
        uat_pass "attachment count unchanged at $after - --text uploaded nothing"
    else
        uat_fail "attachment count went from $before to $after - --text uploaded something"
    fi
}

step_4() {
    uat_step 4 "${STEP_TITLES[4]}"
    uat_explain "The scratch issue is shared with every other guide in this suite, so a guide that leaves its writes behind makes the next run's counts meaningless. Cleanup matches on the comment2jira-uat marker, which is why every fixture and every posted string carries it."
    uat_expect "exit 0, at least one comment removed, and no comment carrying the marker left on the issue."

    _uat_load_env
    uat_run 0 "${UAT_PROBE_CMD[@]}" --action cleanup
    uat_assert_matches "removed comments: [1-9]" "the comments this guide posted were removed"

    uat_run 0 "${UAT_PROBE_CMD[@]}" --action cleanup
    uat_assert_contains "removed comments: 0" "a second cleanup finds nothing - the first one was complete"
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
        uat_list_steps "text-mode.sh"
        exit "$UAT_EXIT_OK"
    fi

    uat_resolve_range "$LAST_STEP"

    uat_banner "UAT walkthrough: comment2jira --text"
    printf '  guide  : text-mode.md\n'
    printf '  env    : %s\n' "$UAT_ENV_FILE"
    printf '  steps  : %s\n' "$(uat_step_range)"

    [[ "$UAT_DO_SEED" -eq 1 ]] && uat_seed

    uat_run_steps

    # Step 4 is the cleanup. --cleanup repeats it, which is harmless: the probe
    # is idempotent and finds nothing the second time.
    [[ "$UAT_DO_CLEANUP" -eq 1 ]] && uat_cleanup

    uat_summary
}

main "$@"
