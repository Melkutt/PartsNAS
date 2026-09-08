"""Runtime configuration.

All paths default to sensible values for local development and are overridden by
environment variables in the container (see docker-compose.yml). `DATA_DIR` holds
the SQLite database and the uploaded images; mount it as a volume on the NAS.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PARTSNAS_", env_file=".env", extra="ignore")

    data_dir: Path = Field(default=REPO_ROOT / "data")
    seed_dir: Path = Field(default=REPO_ROOT / "seed")
    frontend_dir: Path = Field(default=REPO_ROOT / "frontend")

    # Single-user, local. A bearer token gates the KiCad HTTP library and (later)
    # any write access when the app is reachable beyond localhost. Empty = open.
    api_token: str = ""

    default_currency: str = "SEK"
    default_vat_percent: float = 25.0

    @property
    def db_path(self) -> Path:
        return self.data_dir / "partsnas.db"

    @property
    def images_dir(self) -> Path:
        return self.data_dir / "images"

    @property
    def thumbs_dir(self) -> Path:
        return self.data_dir / "thumbs"

    def ensure_dirs(self) -> None:
        for p in (self.data_dir, self.images_dir, self.thumbs_dir):
            p.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    return s
