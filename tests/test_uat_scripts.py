"""Guards for the guided UAT walkthrough scripts under tests/UAT.

These are cheap structural checks, not a run of the walkthroughs themselves:
the scripts need a live Jira instance and a filled-in ``test.env``, and the
paths they exercise already have automated coverage in ``tests/`` and
``tests/integration``. What is worth guarding here are the conventions specific
to a guided walkthrough - no ``set -e`` (several steps expect a non-zero exit),
one shared harness rather than copy-pasted plumbing, no real environment values
in a committed file, a ``--help`` that works with nothing provisioned, and the
exec bit the docs rely on when they invoke a script directly.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

UAT_DIR = Path(__file__).resolve().parent / "UAT"

SCRIPTS = sorted(UAT_DIR.glob("*.sh"))
LIBRARIES = {"common.sh", "project.sh"}
STEP_SCRIPTS = [path for path in SCRIPTS if path.name not in LIBRARIES]

# Names the harness owns. A step script must source them, never redefine them.
_HARNESS_FUNCTION = re.compile(r"^\s*(uat_[a-z_]+)\s*\(\)", re.MULTILINE)

# Shapes that would mean a real environment leaked into a committed file. The
# atlassian.net pattern is the one that matters most here: a read-back of a
# rewritten attachment reference prints the instance's own base URL, and it
# would be easy to paste that straight into a guide.
_LEAK_PATTERNS = {
    "a Jira Cloud site host": re.compile(r"\b[\w-]+\.atlassian\.net\b", re.IGNORECASE),
    "an internal hostname": re.compile(r"\b[\w.-]+\.(?:corp|internal|intra)\b", re.IGNORECASE),
    "a real-looking issue key": re.compile(r"\b(?!UAT-|UATNOPE-)[A-Z]{2,}-\d{1,}\b"),
}

# Values that legitimately match a pattern above. Every entry must be a
# synthetic fixture value published in tests/UAT/README.md.
_ALLOWED = frozenset({"UTF-8", "SIM-1", "MD-1"})

# Files that must NOT exist, because a guide step proves what happens when they
# are absent. Creating one would make that step pass for the wrong reason.
_MUST_BE_ABSENT = ("uat-gone.png", "uat-does-not-exist.env")


def _ids(path: Path) -> str:
    """pytest calls this once per parameter, so a script's id is just its name."""
    return path.name


def test_uat_scripts_are_discovered() -> None:
    """The globs below are only meaningful if they actually match something."""
    assert SCRIPTS, f"no *.sh scripts found under {UAT_DIR}"
    assert (UAT_DIR / "common.sh") in SCRIPTS
    assert STEP_SCRIPTS, "expected at least one per-guide walkthrough script"


@pytest.mark.parametrize("script", SCRIPTS, ids=_ids)
def test_script_is_clean_bash(script: Path) -> None:
    """LF endings, plain ASCII, a bash shebang, and syntactically valid."""
    raw = script.read_bytes()
    assert b"\r\n" not in raw, f"{script.name} has CRLF line endings"
    text = raw.decode("ascii")  # raises on any non-ASCII byte
    assert text.startswith("#!/usr/bin/env bash"), f"{script.name} lacks a bash shebang"

    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is not on PATH")
    result = subprocess.run([bash, "-n", str(script)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, f"{script.name} fails bash -n:\n{result.stderr}"


@pytest.mark.parametrize("script", SCRIPTS, ids=_ids)
def test_script_does_not_enable_errexit(script: Path) -> None:
    """``set -e`` would abort a walkthrough at its first intentional non-zero exit."""
    for number, line in enumerate(script.read_text(encoding="ascii").splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        assert not re.match(r"^set\s+-[a-z]*e", stripped), (
            f"{script.name}:{number} enables errexit: {stripped}"
        )


@pytest.mark.parametrize(
    "committed",
    sorted(UAT_DIR.glob("*.sh")) + sorted(UAT_DIR.glob("*.md")),
    ids=_ids,
)
def test_committed_file_carries_no_real_environment_values(committed: Path) -> None:
    """Only synthetic values belong in a committed guide or script.

    ``test.env`` is gitignored precisely so the real host, account and issue key
    stay out of the repository; a value pasted from a read-back would put one
    back in.
    """
    text = committed.read_text(encoding="utf-8")
    for what, pattern in _LEAK_PATTERNS.items():
        leaked = set(pattern.findall(text)) - _ALLOWED
        assert not leaked, f"{committed.name} names what looks like {what}: {sorted(leaked)}"


@pytest.mark.parametrize("script", STEP_SCRIPTS, ids=_ids)
def test_step_script_sources_the_shared_harness(script: Path) -> None:
    """One harness, sourced once - not plumbing copied per guide."""
    text = script.read_text(encoding="ascii")
    sourced = re.findall(r"^\s*(?:source|\.)\s+.*common\.sh", text, re.MULTILINE)
    assert len(sourced) == 1, (
        f"{script.name} should source common.sh exactly once, found {len(sourced)}"
    )


@pytest.mark.parametrize("script", STEP_SCRIPTS, ids=_ids)
def test_step_script_does_not_redefine_harness_functions(script: Path) -> None:
    """A redefined uat_* helper would silently diverge from the shared engine.

    ``project.sh`` is exempt: overriding ``uat_seed`` / ``uat_cleanup`` there is
    the documented way to attach a project's fixture, which is why it is in
    ``LIBRARIES`` rather than ``STEP_SCRIPTS``.
    """
    harness = set(_HARNESS_FUNCTION.findall((UAT_DIR / "common.sh").read_text(encoding="ascii")))
    redefined = sorted(
        harness.intersection(_HARNESS_FUNCTION.findall(script.read_text(encoding="ascii")))
    )
    assert not redefined, f"{script.name} redefines harness function(s): {redefined}"


@pytest.mark.parametrize("script", STEP_SCRIPTS, ids=_ids)
def test_every_guide_has_a_markdown_companion(script: Path) -> None:
    """A script is the guide's own commands - so the guide has to exist."""
    if script.name == "run-all.sh":
        pytest.skip("run-all.sh drives the roster; it is not a guide of its own")
    guide = script.with_suffix(".md")
    assert guide.is_file(), f"{script.name} has no companion {guide.name}"


@pytest.mark.parametrize("guide", sorted(UAT_DIR.glob("*.md")), ids=_ids)
def test_guide_carries_no_placeholders(guide: Path) -> None:
    """Every command in a guide must run exactly as written."""
    if guide.name == "README.md":
        return
    text = guide.read_text(encoding="utf-8")
    for pattern, what in (
        (r"<[A-Z][A-Z_0-9]{2,}>", "an angle-bracket placeholder"),
        (r"\bYOUR_[A-Z_]+\b", "a YOUR_* placeholder"),
        (r"\bTODO\b", "a TODO marker"),
        (r"\bTBD\b", "a TBD marker"),
        (r"\.{3}\s*$", "an elided command line"),
    ):
        found = re.findall(pattern, text, re.MULTILINE)
        assert not found, f"{guide.name} contains {what}: {sorted(set(found))}"


@pytest.mark.parametrize("name", _MUST_BE_ABSENT)
def test_deliberately_absent_fixture_stays_absent(name: str) -> None:
    """Two guide steps prove what happens when a named file is missing.

    Creating either would turn those steps into checks that pass for the wrong
    reason, so the absence is asserted here as well as in the guides' own
    preflights.
    """
    path = UAT_DIR / "fixtures" / name
    assert not path.exists(), (
        f"{path} must not exist: a UAT step proves the behaviour when it is missing"
    )


def test_common_sh_refuses_direct_execution() -> None:
    """common.sh is a library: running it must exit 2 rather than do nothing."""
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is not on PATH")
    result = subprocess.run(
        [bash, str(UAT_DIR / "common.sh")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2, f"expected exit 2, got {result.returncode}"
    assert "library" in result.stderr


def _index_mode(path: Path) -> str:
    """Return the file mode git records - what a Linux or macOS checkout gets.

    Windows checkouts run with ``core.filemode=false``, which makes the
    filesystem bit meaningless there: ``os.access(path, os.X_OK)`` answers yes
    for every file. Only the index mode is portable.
    """
    git = shutil.which("git")
    if git is None:
        pytest.skip("git is not on PATH")
    repo_root = Path(
        subprocess.run(
            [git, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
            cwd=UAT_DIR,
        ).stdout.strip()
    )
    result = subprocess.run(
        [git, "ls-files", "-s", "--", path.relative_to(repo_root).as_posix()],
        capture_output=True,
        text=True,
        check=False,
        cwd=repo_root,
    )
    if result.returncode != 0 or not result.stdout.strip():
        pytest.skip(f"{path.name} is not tracked by git")
    return result.stdout.split()[0]


@pytest.mark.parametrize("script", SCRIPTS, ids=_ids)
def test_script_is_executable(script: Path) -> None:
    """The guides invoke these directly - ``./text-mode.sh --auto``, no ``bash``
    prefix - so the exec bit has to travel with the file.

    ``common.sh`` is included deliberately: every script here carries the same
    mode, and the library's own guard - not its mode - is what refuses a direct
    run (see ``test_common_sh_refuses_direct_execution``).
    """
    assert _index_mode(script) == "100755", (
        f"{script.name} is not executable in the index, but the docs run it directly; "
        f"fix with: git update-index --chmod=+x tests/UAT/{script.name}"
    )


@pytest.mark.parametrize("script", STEP_SCRIPTS, ids=_ids)
def test_step_script_help_exits_zero(script: Path) -> None:
    """--help must work with no credentials, no network and no scratch issue."""
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is not on PATH")
    result = subprocess.run(
        [bash, str(script), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"{script.name} --help exited {result.returncode}:\n{result.stderr}"
    )
    assert "--auto" in result.stdout, f"{script.name} --help does not document --auto"


# ---------------------------------------------------------------------------
# Harness behavior
#
# The checks above are structural. These drive common.sh itself through
# throwaway fixture scripts, because the parts worth guarding are the ones a
# reader cannot confirm by eye: that a skip is honestly reported and never
# quietly turns a hollow run into a pass, that the step range a run announces
# matches the steps it will actually take, and that the newest-artifact lookup
# behaves when the glob matches nothing.
#
# The fixtures live in tmp_path, not UAT_DIR, so the structural checks above do
# not pick them up as guide scripts.
# ---------------------------------------------------------------------------


def _run_fixture(tmp_path: Path, body: str) -> subprocess.CompletedProcess[str]:
    """Source common.sh from a throwaway script and run it, returning the result."""
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is not on PATH")
    common = UAT_DIR.joinpath("common.sh").as_posix()
    script = tmp_path / "fixture.sh"
    script.write_text(
        f'#!/usr/bin/env bash\nset -uo pipefail\nsource "{common}"\nuat_init\n{body}\n',
        encoding="ascii",
        newline="\n",
    )
    return subprocess.run([bash, str(script)], capture_output=True, text=True, check=False)


def test_uat_skip_does_not_change_the_exit_code(tmp_path: Path) -> None:
    """A skipped step sits beside a passing one without costing the run its 0."""
    result = _run_fixture(
        tmp_path,
        'uat_step 1 "runs"\n'
        'uat_pass "a real assertion"\n'
        'uat_step 2 "skipped"\n'
        'uat_skip "an optional tool is absent"\n'
        "uat_summary\n"
        "exit $?\n",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "[SKIP] an optional tool is absent" in result.stdout
    assert "steps run     : 1" in result.stdout
    assert "steps skipped : 1" in result.stdout


def test_skip_only_run_exits_zero_and_says_so(tmp_path: Path) -> None:
    """A run where nothing actually happened must not read as a clean pass."""
    result = _run_fixture(
        tmp_path,
        'uat_step 1 "skipped"\nuat_skip "an optional tool is absent"\nuat_summary\nexit $?\n',
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "steps run     : 0" in result.stdout
    assert "steps skipped : 1" in result.stdout
    assert "RESULT: PASS (1 step(s) skipped)" in result.stdout


def test_skip_never_masks_a_failure(tmp_path: Path) -> None:
    """The qualified PASS line must not swallow a step that genuinely failed."""
    result = _run_fixture(
        tmp_path,
        'uat_step 1 "skipped"\n'
        'uat_skip "an optional tool is absent"\n'
        'uat_step 2 "fails"\n'
        'uat_fail "a real assertion failed"\n'
        "uat_summary\n"
        "exit $?\n",
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "RESULT: FAIL" in result.stdout


def test_uat_step_range_states_the_extent_once_on_a_full_run(tmp_path: Path) -> None:
    """An unfiltered run announces the guide once, not the same range twice.

    Steps are numbered from 0, so a guide whose last step is 6 has seven of
    them - which is why the count is spelled out here and the step heading names
    the numbering it belongs to rather than reading as "6 of 6 done".
    """
    result = _run_fixture(tmp_path, 'uat_resolve_range 6\nuat_step_range\nuat_step 6 "last"\n')
    assert result.returncode == 0, result.stdout + result.stderr
    assert "0..6 (7 steps)" in result.stdout
    assert "Step 6 of 0..6: last" in result.stdout


def test_uat_step_range_reports_a_filter_against_the_whole_walkthrough(tmp_path: Path) -> None:
    """A narrowed range keeps the guide's full extent in view."""
    ranged = _run_fixture(
        tmp_path, "uat_parse_common_args --from-step 3\nuat_resolve_range 6\nuat_step_range\n"
    )
    assert ranged.returncode == 0, ranged.stdout + ranged.stderr
    assert ranged.stdout.strip() == "3..6 of 0..6"

    single = _run_fixture(
        tmp_path, "uat_parse_common_args --only-step 3\nuat_resolve_range 6\nuat_step_range\n"
    )
    assert single.returncode == 0, single.stdout + single.stderr
    assert single.stdout.strip() == "3 of 0..6"


def test_uat_latest_file_returns_the_newest_match(tmp_path: Path) -> None:
    """The scripted form of a `ls -t ... | head -1` hand-off between guides."""
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    for index, name in enumerate(("out_a.json", "out_b.json", "out_c.json")):
        path = artifacts / name
        path.write_text("{}", encoding="ascii")
        os.utime(path, (1_700_000_000 + index * 60, 1_700_000_000 + index * 60))
    (artifacts / "unrelated.txt").write_text("x", encoding="ascii")

    result = _run_fixture(tmp_path, f'uat_latest_file "{artifacts.as_posix()}/out_*.json"\n')
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == f"{artifacts.as_posix()}/out_c.json"


def test_uat_latest_file_is_empty_when_nothing_matches(tmp_path: Path) -> None:
    """A no-match must yield empty output, never the literal glob pattern."""
    result = _run_fixture(tmp_path, f'uat_latest_file "{tmp_path.as_posix()}/nothing_*.json"\n')
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == ""


def test_uat_have_cmd_probes_without_exiting(tmp_path: Path) -> None:
    """The non-fatal counterpart to uat_require_cmd: report, never abort."""
    result = _run_fixture(
        tmp_path,
        'uat_have_cmd bash && echo "bash: yes"\n'
        'uat_have_cmd definitely-not-a-real-command-9z || echo "missing: no"\n'
        'echo "still running"\n',
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "bash: yes" in result.stdout
    assert "missing: no" in result.stdout
    assert "still running" in result.stdout
