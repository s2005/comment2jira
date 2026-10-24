#!/usr/bin/env bash
#
# attachments.sh - guided, self-checking walkthrough of attachments.md.
#
# Runs every check the guide describes for the attachment half of
# `comment2jira --file`: each step explains what it exercises, echoes and runs
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
# This guide WRITES: it posts two comments and uploads two attachments to the
# scratch issue named by JIRA_TEST_ISSUE. The last step deletes all four,
# matching on the comment2jira-uat marker and the uat- filename prefix so
# nothing else on the issue is touched. Cleanup is an ordinary step rather than
# a trap, so an interrupted run leaves the writes in place to be inspected;
# `./attachments.sh --cleanup` removes them afterwards.
#
# Exit codes: 0 all assertions passed, 1 an assertion failed, 2 bad invocation,
# 3 a prerequisite is missing, 130 interrupted.
#
# No `set -e`: uat_run captures each exit code itself, and errexit would abort
# the walkthrough rather than let it report every problem (see common.sh).
set -uo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

# The committed fixtures this guide posts, and the names their references
# resolve to. Every one is synthetic and published in README.md.
readonly ATTACHMENT_FIXTURE="tests/UAT/fixtures/uat-with-attachments.md"
readonly MISSING_REF_FIXTURE="tests/UAT/fixtures/uat-missing-ref.md"
readonly IMAGE_NAME="uat-shot.png"
readonly REPORT_NAME="uat-report.txt"
readonly MISSING_NAME="uat-gone.png"
readonly REMOTE_REF="https://example.com/uat-shot.png"

STEP_TITLES=(
    "Preflight - uv, test.env, the fixtures, and a reachable scratch issue"
    "Post the fixture that references two local files"
    "Both referenced files are now attachments on the issue"
    "The body's local references were rewritten, the others left alone"
    "A reference to a missing file warns without failing the run"
    "Cleanup - remove the comments and attachments this guide created"
)
readonly LAST_STEP=$((${#STEP_TITLES[@]} - 1))

usage() {
    cat <<'USAGE'
attachments.sh - guided walkthrough of attachments.md

Usage:
  ./attachments.sh [options]

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

This guide writes: it posts two comments and uploads two attachments to that
issue. The last step deletes all four, matching on the comment2jira-uat marker
and the uat- filename prefix, so nothing else on the issue is touched. After an
interrupted run, clear up with:
  uv run python tests/UAT/jira_probe.py --action cleanup --env-file test.env
USAGE
}

# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------

step_0() {
    uat_step 0 "${STEP_TITLES[0]}"
    uat_explain "Everything below needs uv, a filled-in test.env, both committed fixtures, and a scratch issue this account may attach files to. Checking them once here turns a missing prerequisite into one clear message instead of five confusing step failures - and it fails before anything is uploaded."
    uat_expect "uv is on PATH, $UAT_ENV_FILE carries JIRA_URL, JIRA_TOKEN and JIRA_TEST_ISSUE, both fixtures and the referenced files are present, and the scratch issue can be read."

    uat_require_cmd "uv" "Install uv: https://docs.astral.sh/uv/getting-started/installation/"
    uat_pass "uv is on PATH"

    _uat_load_env
    uat_pass "$UAT_ENV_FILE supplies JIRA_URL, JIRA_TOKEN and JIRA_TEST_ISSUE"

    uat_require_file "$ATTACHMENT_FIXTURE" "The fixture is committed; check out tests/UAT/fixtures."
    uat_require_file "$MISSING_REF_FIXTURE" "The fixture is committed; check out tests/UAT/fixtures."
    uat_require_file "$UAT_FIXTURES/$IMAGE_NAME" "The fixture is committed; check out tests/UAT/fixtures."
    uat_require_file "$UAT_FIXTURES/$REPORT_NAME" "The fixture is committed; check out tests/UAT/fixtures."
    uat_pass "both fixtures and both referenced files are present"

    if [[ -e "$UAT_FIXTURES/$MISSING_NAME" ]]; then
        uat_fatal "$UAT_EXIT_PREREQ" \
            "$UAT_FIXTURES/$MISSING_NAME exists, but step 4 needs it absent.
    Remove it: rm $UAT_FIXTURES/$MISSING_NAME"
    fi
    uat_pass "$MISSING_NAME is absent, as step 4 requires"

    uat_run_quiet "${UAT_PROBE_CMD[@]}" --action attachment-count
    if [[ "$UAT_RC" -ne 0 ]]; then
        printf '%s\n' "$UAT_OUT"
        uat_fatal "$UAT_EXIT_PREREQ" \
            "the scratch issue named by JIRA_TEST_ISSUE cannot be read (exit $UAT_RC).
    Point it at a throwaway issue this account can see, then retry."
    fi
    uat_pass "the scratch issue is readable and holds $UAT_OUT attachment(s)"
}

step_1() {
    uat_step 1 "${STEP_TITLES[1]}"
    uat_explain "The full pipeline: extract the references, upload the two that resolve to real files, rewrite the body with the names Jira reported, convert, post. Uploads happen before the comment, so a clean exit means every one of them succeeded."
    uat_expect "exit 0, with no output: both referenced files exist, so nothing is skipped and no warning is printed."

    _uat_load_env
    uat_run 0 "${UAT_BASE_CMD[@]}" --issue "$UAT_ISSUE" --file "$ATTACHMENT_FIXTURE"
    uat_assert_not_contains "error:" "no error line was printed"
    uat_assert_not_contains "Referenced file not found" "neither reference was skipped"
}

step_2() {
    uat_step 2 "${STEP_TITLES[2]}"
    uat_explain "The upload half, checked at the issue rather than at the exit code. Both references have to arrive, and they have to arrive under their own basenames - the stored name is what the rewritten body points at, so a renamed upload would produce a comment linking to nothing."
    uat_expect "exit 0, and the issue's attachment list holds both $IMAGE_NAME and $REPORT_NAME."

    _uat_load_env
    uat_run 0 "${UAT_PROBE_CMD[@]}" --action attachments
    uat_assert_contains "$IMAGE_NAME" "the image reference was uploaded under its own basename"
    uat_assert_contains "$REPORT_NAME" "the file link was uploaded under its own basename"
}

step_3() {
    uat_step 3 "${STEP_TITLES[3]}"
    uat_explain "The rewrite half, and the two classifications that must NOT be rewritten. A relative path left in the body would render as a broken link, an uploaded remote URL would attach files nobody asked for, and a rewritten fenced reference would corrupt a code sample."
    uat_expect "exit 0; the body points at /rest/api/2/attachment/content/, the relative paths are gone, the remote URL survives verbatim, and the fenced reference is still literal."

    _uat_load_env
    uat_run 0 "${UAT_PROBE_CMD[@]}" --action latest-comment
    uat_assert_contains "comment2jira-uat attachment check." "the newest comment is the one step 1 posted"
    uat_assert_contains "/rest/api/2/attachment/content/" "both local references now point at an uploaded attachment"
    # Matched with their alt/label text: the bare "(uat-shot.png)" also occurs
    # inside the fenced block below, which must NOT be rewritten.
    uat_assert_not_contains "![screenshot]($IMAGE_NAME)" "the image reference was rewritten, not left as a relative path"
    uat_assert_not_contains "[the report]($REPORT_NAME)" "the link reference was rewritten, not left as a relative path"
    uat_assert_contains "$REMOTE_REF" "the remote reference was left exactly as written"
    uat_assert_contains "![ignored]($IMAGE_NAME)" "the fenced reference is still literal text"
}

step_4() {
    uat_step 4 "${STEP_TITLES[4]}"
    uat_explain "A comment is usually written long after the files it mentions, so a stale reference is the normal case, not an exceptional one. Failing the whole run over it would lose the comment; silently dropping the reference would lose information. The command has to warn, leave the reference alone, and post anyway."
    uat_expect "exit 0 with 'Referenced file not found, skipping' naming $MISSING_NAME on stderr, the attachment count unchanged, and the reference left as written."

    _uat_load_env
    local before after
    before="$("${UAT_PROBE_CMD[@]}" --action attachment-count)"
    uat_note "before the run: $before attachment(s)"

    uat_run 0 "${UAT_BASE_CMD[@]}" --issue "$UAT_ISSUE" --file "$MISSING_REF_FIXTURE"
    uat_assert_contains "Referenced file not found, skipping" "the missing reference was reported"
    uat_assert_contains "$MISSING_NAME" "the warning names the file it could not find"

    after="$("${UAT_PROBE_CMD[@]}" --action attachment-count)"
    if [[ "$after" == "$before" ]]; then
        uat_pass "attachment count unchanged at $after - nothing was uploaded for a missing file"
    else
        uat_fail "attachment count went from $before to $after - something was uploaded"
    fi

    uat_run 0 "${UAT_PROBE_CMD[@]}" --action latest-comment
    uat_assert_contains "comment2jira-uat missing reference check." "the comment was posted despite the warning"
    uat_assert_contains "$MISSING_NAME" "the unresolvable reference was left in the body as written"
}

step_5() {
    uat_step 5 "${STEP_TITLES[5]}"
    uat_explain "This is the only guide that uploads, so it is the only one whose leftovers accumulate on the scratch issue run after run. Cleanup matches comments on the comment2jira-uat marker and attachments on the uat- prefix, which is why every fixture is named and worded the way it is."
    uat_expect "exit 0, both comments and both attachments removed, and a second cleanup finding nothing."

    _uat_load_env
    uat_run 0 "${UAT_PROBE_CMD[@]}" --action cleanup
    uat_assert_matches "removed comments: [1-9]" "the comments this guide posted were removed"
    uat_assert_matches "removed attachments: [1-9]" "the attachments this guide uploaded were removed"

    uat_run 0 "${UAT_PROBE_CMD[@]}" --action cleanup
    uat_assert_contains "removed comments: 0" "a second cleanup finds no comment - the first one was complete"
    uat_assert_contains "removed attachments: 0" "a second cleanup finds no attachment - the first one was complete"
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
        uat_list_steps "attachments.sh"
        exit "$UAT_EXIT_OK"
    fi

    uat_resolve_range "$LAST_STEP"

    uat_banner "UAT walkthrough: comment2jira --file with attachments"
    printf '  guide  : attachments.md\n'
    printf '  env    : %s\n' "$UAT_ENV_FILE"
    printf '  steps  : %s\n' "$(uat_step_range)"

    [[ "$UAT_DO_SEED" -eq 1 ]] && uat_seed

    uat_run_steps

    # Step 5 is the cleanup. --cleanup repeats it, which is harmless: the probe
    # is idempotent and finds nothing the second time.
    [[ "$UAT_DO_CLEANUP" -eq 1 ]] && uat_cleanup

    uat_summary
}

main "$@"
