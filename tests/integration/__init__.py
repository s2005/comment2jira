"""Integration tests that talk to a live Jira instance.

Every test here is marked ``integration`` and is skipped unless pytest is
run with ``--jira-env-file PATH`` naming an env file that supplies credentials.
"""
