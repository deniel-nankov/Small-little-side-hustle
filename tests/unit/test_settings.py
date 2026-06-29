"""Unit tests for config/settings.py."""

from __future__ import annotations

import pytest
from config.settings import (
    AppEnv,
    DataSourceKind,
    MissingCredentialError,
    Settings,
)


def _settings(**overrides: object) -> Settings:
    """Build Settings ignoring any real .env so tests are hermetic."""
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


def test_defaults_are_development_fixture() -> None:
    cfg = _settings()
    assert cfg.app_env is AppEnv.development
    assert cfg.data_source is DataSourceKind.fixture
    assert cfg.is_production is False


def test_development_fixture_requires_no_credentials() -> None:
    # Should not raise — the whole point of the fixture profile.
    _settings().validate_for_runtime()


def test_factset_source_requires_factset_credentials() -> None:
    cfg = _settings(data_source="factset")
    with pytest.raises(MissingCredentialError, match="factset_client_id"):
        cfg.validate_for_runtime()


def test_production_requires_full_credential_set() -> None:
    cfg = _settings(app_env="production")
    with pytest.raises(MissingCredentialError) as exc:
        cfg.validate_for_runtime()
    assert "database_url" in str(exc.value)
    assert "quantconnect_api_token" in str(exc.value)


def test_require_raises_for_missing_named_setting() -> None:
    with pytest.raises(MissingCredentialError, match="slack_webhook_url"):
        _settings().require("slack_webhook_url")


def test_require_passes_when_present() -> None:
    cfg = _settings(slack_webhook_url="https://hooks.example/abc")
    cfg.require("slack_webhook_url")  # no raise


def test_secrets_are_masked_in_repr() -> None:
    cfg = _settings(factset_client_secret="super-secret-value")
    assert "super-secret-value" not in repr(cfg)
    assert cfg.factset_client_secret is not None
    assert cfg.factset_client_secret.get_secret_value() == "super-secret-value"
