"""Centralized configuration — the ONLY place environment variables are read.

Every other module imports settings from here (PRINCIPLES.md Rule 4: no module reads
``os.environ`` directly). Credentials are stored as :class:`~pydantic.SecretStr` so they
cannot be accidentally logged (SECURITY.md: never log credential values).

Validation strategy
-------------------
Loading ``Settings`` never raises just because a credential is absent — that would make
the platform impossible to build or test against the fixture data source with no API
access. Instead:

* :meth:`Settings.validate_for_runtime` checks the credentials *required by the active
  runtime profile* (``app_env`` + ``data_source``) and raises a single, aggregated
  :class:`MissingCredentialError` listing everything missing. Entry points call this on
  startup so production fails loudly and immediately.
* :meth:`Settings.require` lets an individual module assert the specific credentials it
  needs at the moment it needs them.
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppEnv(str, Enum):
    """Deployment profile. Controls log format and which credentials are mandatory."""

    development = "development"
    production = "production"


class DataSourceKind(str, Enum):
    """Which :class:`~src.data.source.base.DataSource` implementation backs ingestion."""

    fixture = "fixture"
    factset = "factset"


class MissingCredentialError(RuntimeError):
    """Raised when a credential required by the active runtime profile is absent."""


class Settings(BaseSettings):
    """All runtime configuration, loaded from environment / ``.env``.

    Attributes mirror ``.env.example``. Secrets are :class:`~pydantic.SecretStr`; access
    their value with ``.get_secret_value()`` only at the point of use.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- Runtime ----
    app_env: AppEnv = AppEnv.development
    data_source: DataSourceKind = DataSourceKind.fixture
    log_level: str = "INFO"

    # ---- FactSet ----
    factset_client_id: SecretStr | None = None
    factset_client_secret: SecretStr | None = None

    # ---- LLM / agent providers ----
    nvidia_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    google_api_key: SecretStr | None = None

    # ---- QuantConnect ----
    quantconnect_user_id: str | None = None
    quantconnect_api_token: SecretStr | None = None

    # ---- Interactive Brokers ----
    ib_account_id: str | None = None
    ib_host: str = "127.0.0.1"
    ib_port: int = 7497
    ib_client_id: int = 1

    # ---- Infrastructure ----
    database_url: SecretStr | None = None
    slack_webhook_url: SecretStr | None = None

    # ------------------------------------------------------------------ helpers
    @property
    def is_production(self) -> bool:
        """True when running under the production profile."""
        return self.app_env is AppEnv.production

    def required_for_runtime(self) -> list[str]:
        """Return the attribute names that must be set for the active profile.

        Returns:
            Ordered, de-duplicated list of required setting attribute names.
        """
        required: list[str] = []
        if self.data_source is DataSourceKind.factset:
            required += ["factset_client_id", "factset_client_secret"]
        if self.is_production:
            required += [
                "factset_client_id",
                "factset_client_secret",
                "nvidia_api_key",
                "openai_api_key",
                "anthropic_api_key",
                "google_api_key",
                "quantconnect_user_id",
                "quantconnect_api_token",
                "ib_account_id",
                "database_url",
            ]
        # de-duplicate, preserve order
        seen: set[str] = set()
        deduped: list[str] = []
        for name in required:
            if name not in seen:
                seen.add(name)
                deduped.append(name)
        return deduped

    def validate_for_runtime(self) -> Settings:
        """Assert every credential required by the active profile is present.

        Returns:
            ``self`` (so callers can chain), when all required values are set.

        Raises:
            MissingCredentialError: if any required value is missing, listing all of them.
        """
        missing = [name for name in self.required_for_runtime() if not getattr(self, name)]
        if missing:
            raise MissingCredentialError(
                "Missing required configuration for "
                f"app_env={self.app_env.value}, data_source={self.data_source.value}: "
                + ", ".join(sorted(set(missing)))
                + ". Add them to your .env (see .env.example)."
            )
        return self

    def require(self, *names: str) -> None:
        """Assert that specific named settings are present.

        Args:
            *names: Attribute names a caller depends on, e.g. ``"slack_webhook_url"``.

        Raises:
            MissingCredentialError: if any named value is missing.
        """
        missing = [n for n in names if not getattr(self, n, None)]
        if missing:
            raise MissingCredentialError(
                "This operation requires: "
                + ", ".join(missing)
                + " — not set in the environment (see .env.example)."
            )


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide :class:`Settings` singleton (cached).

    Tests that need a different environment should construct ``Settings(...)`` directly,
    or call ``get_settings.cache_clear()`` after patching the environment.
    """
    return Settings()


# Convenience singleton for application code: ``from config.settings import settings``.
settings = get_settings()
