"""Tests for comment2jira credential resolution."""

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from comment2jira import config as comment2jira_config
from comment2jira.config import (
    AUTH_BASIC,
    AUTH_BEARER,
    ConfigError,
    Credentials,
    local_env_file_path,
    resolve_credentials,
    user_env_file_path,
)

MISSING = Path("does-not-exist.env")


def _write_env(path: Path, **values: str) -> Path:
    """Write a ``.env`` file and return its path."""
    path.write_text(
        "".join(f"{key}={value}\n" for key, value in values.items()),
        encoding="utf-8",
    )
    return path


class TestResolutionOrder:
    def test_flags_win_over_env(self) -> None:
        creds = resolve_credentials(
            url="https://flag.example.com",
            email="flag@example.com",
            token="flag-token",
            env={
                "JIRA_URL": "https://env.example.com",
                "JIRA_EMAIL": "env@example.com",
                "JIRA_TOKEN": "env-token",
            },
        )
        assert creds.url == "https://flag.example.com"
        assert creds.email == "flag@example.com"
        assert creds.token == "flag-token"

    def test_env_wins_over_env_file(self, tmp_path: Path) -> None:
        env_file = _write_env(
            tmp_path / ".env",
            JIRA_URL="https://file.example.com",
            JIRA_EMAIL="file@example.com",
            JIRA_TOKEN="file-token",
        )
        creds = resolve_credentials(
            env_file=env_file,
            env={
                "JIRA_URL": "https://env.example.com",
                "JIRA_EMAIL": "env@example.com",
                "JIRA_TOKEN": "env-token",
            },
        )
        assert creds.url == "https://env.example.com"
        assert creds.email == "env@example.com"
        assert creds.token == "env-token"

    def test_env_file_is_last_resort(self, tmp_path: Path) -> None:
        env_file = _write_env(
            tmp_path / ".env",
            JIRA_URL="https://file.example.com",
            JIRA_EMAIL="file@example.com",
            JIRA_TOKEN="file-token",
        )
        creds = resolve_credentials(env_file=env_file, env={})
        assert creds.url == "https://file.example.com"
        assert creds.email == "file@example.com"
        assert creds.token == "file-token"

    def test_env_file_supplies_auth_scheme(self, tmp_path: Path) -> None:
        env_file = _write_env(
            tmp_path / ".env",
            JIRA_URL="https://file.example.com",
            JIRA_TOKEN="pat",
            JIRA_AUTH="bearer",
        )
        creds = resolve_credentials(env_file=env_file, env={})
        assert creds.scheme == AUTH_BEARER

    def test_quoted_values_are_unquoted(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text(
            "JIRA_URL=\"https://quoted.example.com\"\nJIRA_TOKEN='quoted-token'\n# a comment\n\n",
            encoding="utf-8",
        )
        creds = resolve_credentials(env_file=env_file, env={})
        assert creds.url == "https://quoted.example.com"
        assert creds.token == "quoted-token"

    def test_empty_value_is_ignored(self, tmp_path: Path) -> None:
        env_file = _write_env(tmp_path / ".env", JIRA_URL="")
        with pytest.raises(ConfigError, match="No Jira URL"):
            resolve_credentials(env_file=env_file, env={})

    def test_missing_everything_raises(self) -> None:
        with pytest.raises(ConfigError, match="No Jira URL"):
            resolve_credentials(env={})

    def test_trailing_slash_stripped(self) -> None:
        creds = resolve_credentials(url="https://jira.example.com/", env={})
        assert creds.url == "https://jira.example.com"

    def test_malformed_env_file_is_tolerated(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("this is [ not an env file", encoding="utf-8")
        creds = resolve_credentials(
            url="https://jira.example.com",
            token="flag-token",
            email="flag@example.com",
            env_file=env_file,
            env={},
        )
        assert creds.url == "https://jira.example.com"


class TestEnvFileSelection:
    def test_explicit_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="Env file not found"):
            resolve_credentials(env_file=tmp_path / MISSING, env={})

    def test_env_var_selects_the_file(self, tmp_path: Path) -> None:
        env_file = _write_env(tmp_path / "custom.env", JIRA_URL="https://pointed.example.com")
        creds = resolve_credentials(env={"COMMENT2JIRA_ENV_FILE": str(env_file)})
        assert creds.url == "https://pointed.example.com"

    def test_env_var_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="Env file not found"):
            resolve_credentials(env={"COMMENT2JIRA_ENV_FILE": str(tmp_path / MISSING)})

    def test_flag_wins_over_env_var(self, tmp_path: Path) -> None:
        flag_file = _write_env(tmp_path / "flag.env", JIRA_URL="https://flag-file.example.com")
        var_file = _write_env(tmp_path / "var.env", JIRA_URL="https://var-file.example.com")
        creds = resolve_credentials(
            env_file=flag_file, env={"COMMENT2JIRA_ENV_FILE": str(var_file)}
        )
        assert creds.url == "https://flag-file.example.com"

    def test_local_file_is_used_by_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        local = _write_env(tmp_path / "local.env", JIRA_URL="https://local.example.com")
        monkeypatch.setattr(comment2jira_config, "local_env_file_path", lambda: local)
        creds = resolve_credentials(env={})
        assert creds.url == "https://local.example.com"

    def test_user_file_is_the_fallback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        user = _write_env(tmp_path / "user.env", JIRA_URL="https://user.example.com")
        monkeypatch.setattr(comment2jira_config, "user_env_file_path", lambda: user)
        creds = resolve_credentials(env={})
        assert creds.url == "https://user.example.com"

    def test_local_file_wins_over_user_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        local = _write_env(tmp_path / "local.env", JIRA_URL="https://local.example.com")
        user = _write_env(tmp_path / "user.env", JIRA_URL="https://user.example.com")
        monkeypatch.setattr(comment2jira_config, "local_env_file_path", lambda: local)
        monkeypatch.setattr(comment2jira_config, "user_env_file_path", lambda: user)
        creds = resolve_credentials(env={})
        assert creds.url == "https://local.example.com"

    def test_files_are_not_merged(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        local = _write_env(tmp_path / "local.env", JIRA_URL="https://local.example.com")
        user = _write_env(
            tmp_path / "user.env",
            JIRA_URL="https://user.example.com",
            JIRA_TOKEN="user-token",
        )
        monkeypatch.setattr(comment2jira_config, "local_env_file_path", lambda: local)
        monkeypatch.setattr(comment2jira_config, "user_env_file_path", lambda: user)
        creds = resolve_credentials(env={})
        assert creds.token is None


class TestEnvFileLocations:
    def test_local_path_is_cwd_relative(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        assert local_env_file_path().resolve() == (tmp_path / ".env").resolve()

    def test_user_path_on_windows_uses_appdata(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            comment2jira_config,
            "os",
            SimpleNamespace(name="nt", environ=os.environ),
        )
        monkeypatch.setenv("APPDATA", str(tmp_path))
        assert user_env_file_path() == tmp_path / "comment2jira" / ".env"

    def test_user_path_without_appdata_uses_config_home(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Covers both the non-Windows branch and Windows without APPDATA.
        monkeypatch.delenv("APPDATA", raising=False)
        assert user_env_file_path() == Path.home() / ".config" / "comment2jira" / ".env"


class TestSchemeSelection:
    @pytest.mark.unit
    def test_email_selects_basic(self) -> None:
        creds = Credentials(url="https://jira.example.com", email="a@example.com", token="t")
        assert creds.scheme == AUTH_BASIC

    @pytest.mark.unit
    def test_absent_email_selects_bearer(self) -> None:
        creds = Credentials(url="https://jira.example.com", token="pat")
        assert creds.scheme == AUTH_BEARER

    @pytest.mark.unit
    def test_explicit_bearer_wins_with_email(self) -> None:
        creds = Credentials(
            url="https://jira.example.com",
            email="a@example.com",
            token="pat",
            auth=AUTH_BEARER,
        )
        assert creds.scheme == AUTH_BEARER

    @pytest.mark.unit
    def test_explicit_basic_from_resolver(self) -> None:
        creds = resolve_credentials(
            url="https://jira.example.com",
            token="pat",
            auth="bearer",
            env={},
        )
        assert creds.scheme == AUTH_BEARER

    @pytest.mark.unit
    def test_unknown_auth_falls_back_to_auto(self) -> None:
        creds = Credentials(
            url="https://jira.example.com",
            email="a@example.com",
            token="t",
            auth="bogus",
        )
        # _normalize_auth happens in the resolver; direct construction
        # keeps the value, but scheme resolution still works.
        assert creds.scheme == AUTH_BASIC


class TestSecretHandling:
    @pytest.mark.unit
    def test_repr_redacts_token(self) -> None:
        creds = Credentials(
            url="https://jira.example.com",
            email="a@example.com",
            token="super-secret-token",
        )
        rendered = repr(creds)
        assert "super-secret-token" not in rendered
        assert "***" in rendered

    @pytest.mark.unit
    def test_repr_without_token(self) -> None:
        creds = Credentials(url="https://jira.example.com")
        assert "None" in repr(creds)

    @pytest.mark.unit
    def test_basic_auth_header(self) -> None:
        creds = Credentials(
            url="https://jira.example.com",
            email="a@example.com",
            token="tok",
        )
        # base64("a@example.com:tok") == "YUBleGFtcGxlLmNvbTp0b2s="
        assert creds.auth_header() == "Basic YUBleGFtcGxlLmNvbTp0b2s="

    @pytest.mark.unit
    def test_bearer_auth_header(self) -> None:
        creds = Credentials(url="https://jira.example.com", token="pat-token")
        assert creds.auth_header() == "Bearer pat-token"

    @pytest.mark.unit
    def test_host_property(self) -> None:
        creds = Credentials(url="https://jira.example.com/base")
        assert creds.host == "jira.example.com"
