"""
Application settings.

Values are read from environment variables, falling back to the "backend/.env"
file. Nothing sensitive is hardcoded here - the real DATABASE_URL lives in
".env", which is git-ignored. See ".env.example" for the expected format.
"""

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed settings object. Pydantic validates and converts the values."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "employee-platform-backend"
    app_env: str = "local"

    # Example:
    # postgresql+psycopg://username:password@localhost:5432/employee_platform
    database_url: str

    # SQLAlchemy prints every SQL statement when this is True.
    # Handy while learning; noisy in normal use.
    db_echo: bool = False

    # How long a login stays valid. 480 minutes = 8 hours, i.e. a working day.
    auth_token_expire_minutes: int = 480

    # Browsers refuse cross-origin calls unless the server names the origin.
    # Only the local Vite dev server is listed - never "*", which browsers
    # reject anyway once credentials are involved.
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    @field_validator("database_url")
    @classmethod
    def _check_database_url(cls, value: str) -> str:
        """
        Catch the most common DATABASE_URL mistake and explain it clearly.

        In a URL, "@" separates the credentials from the host. So a password
        that itself contains "@" silently splits in the wrong place and the
        host name ends up wrong - which surfaces much later as a confusing
        "getaddrinfo failed" error. Percent-encoding fixes it.
        """
        from sqlalchemy.engine import make_url  # local import: keeps startup light

        try:
            url = make_url(value)
        except Exception as exc:  # noqa: BLE001 - re-raised with a clearer message
            raise ValueError(f"DATABASE_URL is not a valid connection URL: {exc}") from exc

        if url.host and "@" in url.host:
            raise ValueError(
                "DATABASE_URL looks wrong: the host was read as "
                f"'{url.host}', which means your password contains an "
                "unescaped special character. Percent-encode it in .env "
                "(@ -> %40, : -> %3A, / -> %2F, # -> %23, % -> %25)."
            )
        return value


# One shared settings instance imported by the rest of the application.
settings = Settings()
