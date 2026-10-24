#!/usr/bin/env bash
#
# dry-run.sh - guided, self-checking walkthrough of dry-run.md.
#
# Runs every check the guide describes for `comment2jira --dry-run`: each step
# explains what it exercises, echoes and runs the guide's exact command, shows
# the real output and the observed vs expected exit code, asserts the
# expectation, and waits for a keypress before the next step.
#
# Prerequisites - the shared setup in README.md:
#   uv sync
#   cp test.env.example test.env      # then fill it in
#
# The credentials are loaded from test.env by project.sh, which is the scripted
# form of the guide's own `set -a; . ./test.env; set +a` line.
#
# Read-only: every step issues a --dry-run, which performs one serverInfo GET
# and no writes, plus two read-only probes. There is nothing to clean up.
#
# Exit codes: 0 all assertions passed, 1 an assertion failed, 2 bad invocation,
# 3 a prerequisite is missing, 130 interrupted.
#
# No `set -e`: uat_run captures each exit code itself, and errexit would abort
# the walkthrough rather than let it report every problem (see common.sh).
set -uo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

# The values this guide names. UAT_DRY_RUN_ISSUE is synthetic and published in
# README.md; the real scratch issue key is never written down, it is read from
# test.env into UAT_ISSUE at run time.
readonly NOTE_FIXTURE="tests/UAT/fixtures/uat-note.md"
readonly ATTACHMENT_FIXTURE="tests/UAT/fixtures/uat-with-attachments.md"
readonly PROBE_TEXT="comment2jira-uat dry run probe"

STEP_TITLES=(
    "Preflight - uv, test.env, the fixtures, and a reachable Jira instance"
    "A verbatim --text dry run prints the plan and the body envelope"
    "A Markdown file is converted, not passed through"
    "Local references are planned, remote and fenced ones are left alone"
    "A dry run writes nothing to the issue"
)
readonly LAST_STEP=$((${#STEP_TITLES[@]} - 1))

usage() {
    cat <<'USAGE'
dry-run.sh - guided walkthrough of dry-run.md

Usage:
  ./dry-run.sh [options]

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

Nothing to clean: every step is a --dry-run plus a read-only probe, so this
guide writes no files and posts nothing. --cleanup is accepted for consistency
with the writing guides and removes anything an earlier guide left behind.
USAGE
}

# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------

step_0() {
    uat_step 0 "${STEP_TITLES[0]}"
    uat_explain "Everything below needs uv, a filled-in test.env, the committed fixtures, and a Jira instance that answers serverInfo. Checking all four once here turns a missing prerequisite into one clear message instead of four confusing step failures."
    uat_expect "uv is on PATH, $UAT_ENV_FILE exists and carries JIRA_URL, JIRA_TOKEN and JIRA_TEST_ISSUE, both fixtures are present, and the instance reports a deployment type."

    uat_require_cmd "uv" "Install uv: https://docs.astral.sh/uv/getting-started/installation/"
    uat_pass "uv is on PATH"

    _uat_load_env
    uat_pass "$UAT_ENV_FILE supplies JIRA_URL, JIRA_TOKEN and JIRA_TEST_ISSUE"

    uat_require_file "$NOTE_FIXTURE" "The fixture is committed; check out tests/UAT/fixtures."
    uat_require_file "$ATTACHMENT_FIXTURE" "The fixture is committed; check out tests/UAT/fixtures."
    uat_pass "both Markdown fixtures are present"

    uat_pass "Jira reports deployment: $(_uat_deployment)"
}

step_1() {
    uat_step 1 "${STEP_TITLES[1]}"
    uat_explain "The cheapest shape of the command: --text is posted verbatim, so the printed body proves only that the deployment envelope is right - an ADF document on Cloud, the bare string on Server/DC. Getting this wrong means every later post is malformed."
    uat_expect "exit 0, with Issue, Deployment and 'Attachments: none' printed, and the probe text carried in the body."

    _uat_load_env
    uat_run 0 "${UAT_BASE_CMD[@]}" --issue "$UAT_DRY_RUN_ISSUE" --text "$PROBE_TEXT" --dry-run
    uat_assert_contains "Issue: $UAT_DRY_RUN_ISSUE" "the plan names the issue it was given"
    uat_assert_matches "Deployment: (cloud|dc)" "a deployment type was detected"
    uat_assert_contains "Attachments: none" "a --text run never plans an upload"
    uat_assert_contains "$PROBE_TEXT" "the body carries the text verbatim"

    if [[ "$(_uat_deployment)" == "cloud" ]]; then
        uat_assert_contains "Body (ADF):" "Cloud wraps the string in an ADF document"
        uat_assert_contains '"type": "doc"' "the ADF envelope is a doc node"
    else
        uat_assert_contains "Body (wiki):" "Server/DC posts wiki markup, so the string is shown as-is"
    fi
}

step_2() {
    uat_step 2 "${STEP_TITLES[2]}"
    uat_explain "The guide's conversion bullet. --file must run the Markdown through the converter, not hand it to Jira raw. The heading, the bold run and the bullet list in the fixture each have to come out as structure, so a converter that silently passed the text through would be caught here."
    uat_expect "exit 0, and the printed body carries converted structure - a heading, a strong/bold run and a list - rather than the Markdown source."

    _uat_load_env
    uat_run 0 "${UAT_BASE_CMD[@]}" --issue "$UAT_DRY_RUN_ISSUE" --file "$NOTE_FIXTURE" --dry-run
    uat_assert_contains "Attachments: none" "the note fixture references no files"
    uat_assert_contains "comment2jira-uat note" "the heading text survives conversion"

    if [[ "$(_uat_deployment)" == "cloud" ]]; then
        uat_assert_contains '"type": "heading"' "the '# ' line became a heading node"
        uat_assert_contains '"type": "strong"' "the '**bold**' run became a strong mark"
        uat_assert_contains '"type": "bulletList"' "the '- ' lines became a bullet list"
        uat_assert_not_contains '"text": "# comment2jira-uat note"' "the Markdown source was not passed through"
    else
        uat_assert_contains "h1. comment2jira-uat note" "the '# ' line became a wiki heading"
        uat_assert_contains "*bold*" "the '**bold**' run became wiki bold"
    fi
    uat_assert_not_contains '**bold**' "the Markdown emphasis markers were consumed"
}

step_3() {
    uat_step 3 "${STEP_TITLES[3]}"
    uat_explain "The guide's attachment-plan bullet, and the three classifications that decide it: a local file that exists is planned for upload, a remote http(s) target is never touched, and a reference inside a fenced code block is not a reference at all. Getting the last two wrong would upload files nobody asked for, or mangle a code sample."
    uat_expect "exit 0; both fixtures are listed with their byte size and stored name; the remote URL survives; the fenced reference stays literal; and each uploaded reference shows the <attachment-url> placeholder, since a real URL is only known after uploading."

    _uat_load_env
    uat_run 0 "${UAT_BASE_CMD[@]}" --issue "$UAT_DRY_RUN_ISSUE" --file "$ATTACHMENT_FIXTURE" --dry-run

    uat_assert_contains "uat-shot.png (75 bytes) -> uat-shot.png" "the image is planned at its size on disk"
    uat_assert_contains "uat-report.txt (44 bytes) -> uat-report.txt" "the linked file is planned at its size on disk"
    uat_assert_contains "<attachment-url>" "planned references carry the placeholder URL"
    uat_assert_contains "https://example.com/uat-shot.png" "the remote reference is left exactly as written"
    uat_assert_contains '![ignored](uat-shot.png)' "the fenced reference stays literal and is never planned"
    uat_assert_not_contains "uat-gone.png" "no reference from another fixture leaked in"
}

step_4() {
    uat_step 4 "${STEP_TITLES[4]}"
    uat_explain "The promise the whole flag rests on. A dry run that quietly posted would be worse than no dry run at all, so this counts the issue's comments and attachments on either side of a run that plans two uploads - the case with the most to write."
    uat_expect "exit 0, and both the comment count and the attachment count are unchanged across the run."

    _uat_load_env
    local comments_before attachments_before comments_after attachments_after
    comments_before="$("${UAT_PROBE_CMD[@]}" --action comment-count)"
    attachments_before="$("${UAT_PROBE_CMD[@]}" --action attachment-count)"
    uat_note "before the run: $comments_before comment(s), $attachments_before attachment(s)"

    uat_run 0 "${UAT_BASE_CMD[@]}" --issue "$UAT_ISSUE" --file "$ATTACHMENT_FIXTURE" --dry-run

    comments_after="$("${UAT_PROBE_CMD[@]}" --action comment-count)"
    attachments_after="$("${UAT_PROBE_CMD[@]}" --action attachment-count)"

    if [[ "$comments_after" == "$comments_before" ]]; then
        uat_pass "comment count unchanged at $comments_after - the dry run posted nothing"
    else
        uat_fail "comment count went from $comments_before to $comments_after - the dry run posted"
    fi
    if [[ "$attachments_after" == "$attachments_before" ]]; then
        uat_pass "attachment count unchanged at $attachments_after - the dry run uploaded nothing"
    else
        uat_fail "attachment count went from $attachments_before to $attachments_after - the dry run uploaded"
    fi
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
        uat_list_steps "dry-run.sh"
        exit "$UAT_EXIT_OK"
    fi

    uat_resolve_range "$LAST_STEP"

    uat_banner "UAT walkthrough: comment2jira --dry-run"
    printf '  guide  : dry-run.md\n'
    printf '  env    : %s\n' "$UAT_ENV_FILE"
    printf '  steps  : %s\n' "$(uat_step_range)"

    [[ "$UAT_DO_SEED" -eq 1 ]] && uat_seed

    uat_run_steps

    # Nothing to clean: every step above is a dry run or a read-only probe, so
    # this guide leaves the issue exactly as it found it.
    [[ "$UAT_DO_CLEANUP" -eq 1 ]] && uat_cleanup

    uat_summary
}

main "$@"
