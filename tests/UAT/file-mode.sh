#!/usr/bin/env bash
#
# file-mode.sh - guided, self-checking walkthrough of file-mode.md.
#
# Runs every check the guide describes for `comment2jira --file` on a fixture
# that references no files, so conversion is the only thing under test: each
# step explains what it exercises, echoes and runs the guide's exact command,
# shows the real output and the observed vs expected exit code, asserts the
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
# place to be inspected; `./file-mode.sh --cleanup` removes it afterwards.
#
# Exit codes: 0 all assertions passed, 1 an assertion failed, 2 bad invocation,
# 3 a prerequisite is missing, 130 interrupted.
#
# No `set -e`: uat_run captures each exit code itself, and errexit would abort
# the walkthrough rather than let it report every problem (see common.sh).
set -uo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

# The committed fixture this guide posts: a heading, a bold run and a bullet
# list, with no file references at all.
readonly NOTE_FIXTURE="tests/UAT/fixtures/uat-note.md"

STEP_TITLES=(
    "Preflight - uv, test.env, the fixture, and a reachable scratch issue"
    "Post the Markdown fixture to the scratch issue"
    "The comment reached Jira converted, not as raw Markdown"
    "A fixture with no references uploads nothing"
    "Cleanup - remove the comment this guide posted"
)
readonly LAST_STEP=$((${#STEP_TITLES[@]} - 1))

usage() {
    cat <<'USAGE'
file-mode.sh - guided walkthrough of file-mode.md

Usage:
  ./file-mode.sh [options]

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
    uat_explain "Everything below needs uv, a filled-in test.env, the committed fixture, and a scratch issue this account may comment on. Checking all four once here turns a missing prerequisite into one clear message instead of four confusing step failures - and it fails before anything is posted."
    uat_expect "uv is on PATH, $UAT_ENV_FILE carries JIRA_URL, JIRA_TOKEN and JIRA_TEST_ISSUE, the fixture is present, and the scratch issue's comments can be read."

    uat_require_cmd "uv" "Install uv: https://docs.astral.sh/uv/getting-started/installation/"
    uat_pass "uv is on PATH"

    _uat_load_env
    uat_pass "$UAT_ENV_FILE supplies JIRA_URL, JIRA_TOKEN and JIRA_TEST_ISSUE"

    uat_require_file "$NOTE_FIXTURE" "The fixture is committed; check out tests/UAT/fixtures."
    uat_pass "the Markdown fixture is present: $NOTE_FIXTURE"

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
    uat_explain "The full --file pipeline, minus the attachment half: read the file, find no references, convert for the detected deployment, post. A clean exit here means the converter produced something the API accepted, which on Cloud is a strictly validated ADF document."
    uat_expect "exit 0, with no output: a fixture that references nothing produces no upload warning either."

    _uat_load_env
    uat_run 0 "${UAT_BASE_CMD[@]}" --issue "$UAT_ISSUE" --file "$NOTE_FIXTURE"
    uat_assert_not_contains "error:" "no error line was printed"
    uat_assert_not_contains "WARNING" "no reference warning was printed - the fixture references nothing"
}

step_2() {
    uat_step 2 "${STEP_TITLES[2]}"
    uat_explain "This is what separates --file from --text. The read-back must show structure the source did not have - a heading marker and a bold run - and, just as importantly, must NOT show the Markdown that produced them. A converter that silently passed the text through would still exit 0 in step 1."
    uat_expect "exit 0; the newest comment shows 'h1. comment2jira-uat note', wiki bold '*bold*' and '* ' bullets, and the Markdown '# ' and '**bold**' forms are gone."

    _uat_load_env
    uat_run 0 "${UAT_PROBE_CMD[@]}" --action latest-comment
    uat_assert_contains "h1. comment2jira-uat note" "the '# ' heading was converted to a wiki heading"
    uat_assert_contains "*bold*" "the bold run survived as wiki bold"
    uat_assert_contains "* first bullet" "the list items survived as wiki list items"
    uat_assert_not_contains '**bold**' "the Markdown emphasis markers were consumed by the converter"
    uat_assert_not_contains "# comment2jira-uat note" "the Markdown heading marker was consumed by the converter"
}

step_3() {
    uat_step 3 "${STEP_TITLES[3]}"
    uat_explain "The --file path runs reference extraction on every run, so a fixture with no references is the case that proves extraction stays quiet when there is nothing to find. An upload here would mean the extractor matched something that is not a file reference."
    uat_expect "exit 0, and the issue's attachment count is unchanged by posting this fixture."

    _uat_load_env
    local before after
    before="$("${UAT_PROBE_CMD[@]}" --action attachment-count)"
    uat_note "before the run: $before attachment(s)"

    uat_run 0 "${UAT_BASE_CMD[@]}" --issue "$UAT_ISSUE" --file "$NOTE_FIXTURE"

    after="$("${UAT_PROBE_CMD[@]}" --action attachment-count)"
    if [[ "$after" == "$before" ]]; then
        uat_pass "attachment count unchanged at $after - a reference-free fixture uploaded nothing"
    else
        uat_fail "attachment count went from $before to $after - something was uploaded"
    fi
}

step_4() {
    uat_step 4 "${STEP_TITLES[4]}"
    uat_explain "The scratch issue is shared with every other guide in this suite, so a guide that leaves its writes behind makes the next run's counts meaningless. Cleanup matches on the comment2jira-uat marker, which is why every fixture carries it."
    uat_expect "exit 0, at least one comment removed, and a second cleanup finding nothing."

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
        uat_list_steps "file-mode.sh"
        exit "$UAT_EXIT_OK"
    fi

    uat_resolve_range "$LAST_STEP"

    uat_banner "UAT walkthrough: comment2jira --file"
    printf '  guide  : file-mode.md\n'
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
