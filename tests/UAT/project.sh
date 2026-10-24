#!/usr/bin/env bash
#
# project.sh - the comment2jira half of the UAT harness.
#
# common.sh sources this file; it is never executed directly. Everything here
# is this project's business: where the credentials live, how a guide addresses
# the scratch issue, and how the suite removes its own writes afterwards.
# common.sh itself stays project-agnostic so it can be copied between
# repositories unchanged.
#
# Credentials: every guide runs against the live Jira instance named by
# test.env at the repository root - the same file tests/integration reads, and
# the same file its test.env.example documents. test.env is gitignored, so no
# real URL, account, token or issue key is ever committed: the guides name only
# the shell variable, and this file resolves it at run time.
#
# Nothing here echoes a credential. The env file is sourced, never printed, and
# the only value any guide displays is the deployment type (cloud or dc).

# ---------------------------------------------------------------------------
# Shared fixture values
#
# The fixture is a scratch Jira issue plus the committed Markdown and file
# fixtures under fixtures/. Every fixture file name starts with "uat-" and
# every fixture body carries the string "comment2jira-uat", which is how
# cleanup recognises this suite's own writes and leaves everything else on the
# issue alone.
# ---------------------------------------------------------------------------

# Issue keys the guides name directly. Both are synthetic and deliberately
# unresolvable - the real scratch issue key is never written down, it is read
# from test.env into UAT_ISSUE at run time.
readonly UAT_DRY_RUN_ISSUE="UAT-1"
readonly UAT_UNKNOWN_ISSUE="UATNOPE-999999"

# The marker every comment this suite posts contains, and the prefix every
# attachment it uploads carries. jira_probe.py matches on both when cleaning up.
readonly UAT_COMMENT_MARKER="comment2jira-uat"
readonly UAT_ATTACHMENT_PREFIX="uat-"

# uat_project_defaults
# Called at the end of uat_init, before any flag is parsed.
uat_project_defaults() {
    # Credentials file, overridable with --env-file. Relative to the checkout
    # root, which uat_init has already made the working directory.
    UAT_ENV_FILE="test.env"

    # Resolved lazily by _uat_load_env, so --only-step N works on its own.
    UAT_ISSUE=""
    UAT_DEPLOYMENT=""

    # This project's Python lives behind uv, so point the JSON assertion helper
    # at the same launcher every guide command uses.
    UAT_PYTHON_CMD=(uv run python)

    UAT_FIXTURES="tests/UAT/fixtures"

    _uat_project_compose
}

# Recompose everything derived from a value a flag can change. Called from
# uat_project_defaults and again from uat_project_after_args.
_uat_project_compose() {
    UAT_BASE_CMD=(uv run comment2jira)
    UAT_PROBE_CMD=(uv run python tests/UAT/jira_probe.py --env-file "$UAT_ENV_FILE")
}

# uat_project_parse_arg "$@"
# Claim --env-file; anything else falls through to UAT_REST.
uat_project_parse_arg() {
    case "$1" in
        --env-file)
            [[ $# -ge 2 ]] || uat_fatal "$UAT_EXIT_USAGE" "--env-file needs a file path"
            UAT_ENV_FILE="$2"
            UAT_ARG_CONSUMED=2
            ;;
    esac
}

# uat_project_after_args
uat_project_after_args() {
    _uat_project_compose
}

# ---------------------------------------------------------------------------
# Credential loading
# ---------------------------------------------------------------------------

# Load the env file into the environment and resolve the scratch issue key.
#
# This is the scripted form of the guides' own prerequisite line,
# `set -a; . ./test.env; set +a`, so the CLI reads JIRA_URL / JIRA_EMAIL /
# JIRA_TOKEN / JIRA_AUTH straight from the environment and $JIRA_TEST_ISSUE
# names the scratch issue. Sourcing prints nothing; do not run a guide from a
# shell with `set -x` enabled, which would echo every value as it is assigned.
#
# Called from each step that needs credentials rather than once in main, so a
# --only-step run still resolves them. Returns immediately once loaded.
_uat_load_env() {
    [[ -n "$UAT_ISSUE" ]] && return 0

    uat_require_file "$UAT_ENV_FILE" \
        "Copy test.env.example to test.env and fill it in, or pass --env-file PATH."

    set -a
    . "$UAT_ENV_FILE"
    set +a

    local missing=()
    [[ -n "${JIRA_URL:-}" ]] || missing+=("JIRA_URL")
    [[ -n "${JIRA_TOKEN:-}" ]] || missing+=("JIRA_TOKEN")
    [[ -n "${JIRA_TEST_ISSUE:-}" ]] || missing+=("JIRA_TEST_ISSUE")
    if [[ ${#missing[@]} -gt 0 ]]; then
        uat_fatal "$UAT_EXIT_PREREQ" \
            "$UAT_ENV_FILE is missing required key(s): ${missing[*]}. See test.env.example."
    fi

    UAT_ISSUE="$JIRA_TEST_ISSUE"
}

# Resolve and cache the deployment type (cloud or dc). Several expectations
# differ between the two - Cloud posts ADF through api/3 and answers an
# unauthenticated caller with 404 rather than 401 - so the guides branch on it
# rather than hard-coding one deployment's behaviour.
#
# Deliberately not routed through uat_run_quiet: that would overwrite UAT_OUT
# and UAT_RC, and a step may need the deployment after its own uat_run has
# already captured the output the assertions read.
_uat_deployment() {
    if [[ -z "$UAT_DEPLOYMENT" ]]; then
        _uat_load_env
        UAT_DEPLOYMENT="$("${UAT_PROBE_CMD[@]}" --action deployment 2>/dev/null | tr -d '[:space:]')"
        if [[ -z "$UAT_DEPLOYMENT" ]]; then
            uat_fatal "$UAT_EXIT_PREREQ" \
                "cannot reach the Jira instance named by $UAT_ENV_FILE; check JIRA_URL and JIRA_TOKEN"
        fi
    fi
    printf '%s' "$UAT_DEPLOYMENT"
}

# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

# The scratch issue is the fixture, and only its owner can create it - so
# seeding verifies it is reachable rather than pretending to provision it.
# Idempotent: it only reads.
uat_seed() {
    printf 'Checking the UAT fixture...\n'
    _uat_load_env
    if ! "${UAT_PROBE_CMD[@]}" --action comment-count >/dev/null; then
        uat_fatal "$UAT_EXIT_PREREQ" \
            "cannot read the scratch issue named by JIRA_TEST_ISSUE in $UAT_ENV_FILE.
    Point it at a throwaway issue you can comment on, then retry."
    fi
    printf 'Scratch issue is reachable; the committed fixtures under %s need no seeding.\n\n' \
        "$UAT_FIXTURES"
}

# Remove only what this suite wrote: comments carrying UAT_COMMENT_MARKER and
# attachments named UAT_ATTACHMENT_PREFIX*. Anything else already on the
# scratch issue is left alone. Idempotent, and never fatal - a cleanup failure
# after a completed walkthrough must not mask the run's own verdict.
uat_cleanup() {
    printf '\nRemoving the comments and attachments this suite posted...\n'
    _uat_load_env
    "${UAT_PROBE_CMD[@]}" --action cleanup ||
        printf '%swarning:%s cleanup failed; run it by hand:\n  %s --action cleanup\n' \
            "$UAT_YELLOW" "$UAT_NC" "${UAT_PROBE_CMD[*]}" >&2
}
