"""Allow running the package with `python -m comment2jira`."""

from comment2jira.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
