from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field


class ConfigError(RuntimeError):
    pass


class AppConfig(BaseModel):
    api_id: int = Field(gt=0)
    api_hash: str = Field(min_length=1)
    phone: str | None = None
    session: Path = Path(".sessions/default")
    timezone: str | None = None

    @classmethod
    def from_env(
        cls,
        *,
        env_file: Path | None = Path(".env"),
        api_id: int | None = None,
        api_hash: str | None = None,
        phone: str | None = None,
        session: Path | None = None,
        timezone: str | None = None,
    ) -> AppConfig:
        if env_file and env_file.exists():
            load_dotenv(env_file)

        raw_api_id = api_id if api_id is not None else os.getenv("TG_API_ID")
        raw_api_hash = api_hash if api_hash is not None else os.getenv("TG_API_HASH")
        raw_phone = phone if phone is not None else os.getenv("TG_PHONE")
        raw_session = (
            session if session is not None else Path(os.getenv("TG_SESSION", ".sessions/default"))
        )
        raw_timezone = timezone if timezone is not None else os.getenv("TG_TIMEZONE")

        if raw_api_id is None:
            raise ConfigError("Missing TG_API_ID")
        if not raw_api_hash:
            raise ConfigError("Missing TG_API_HASH")

        try:
            parsed_api_id = int(raw_api_id)
        except ValueError as exc:
            raise ConfigError("TG_API_ID must be an integer") from exc

        cfg = cls(
            api_id=parsed_api_id,
            api_hash=str(raw_api_hash),
            phone=raw_phone,
            session=Path(raw_session),
            timezone=raw_timezone,
        )
        cfg.session.parent.mkdir(parents=True, exist_ok=True)
        return cfg

    @property
    def session_arg(self) -> str:
        return str(self.session)
