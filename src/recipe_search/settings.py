"""Environment-backed configuration. Secrets are never packaged or logged."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PACKAGE_ROOT = Path(__file__).resolve().parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )
    es_url: str = "https://localhost:19200"
    es_username: str = ""
    es_password: SecretStr = Field(default=SecretStr(""), repr=False)
    es_ca_certs: Path | None = None
    es_index: str = "recipes_clean"
    embedding_model: str = "BAAI/bge-base-en-v1.5"
    hf_home: Path | None = None
    data_dir: Path | None = None
    recipe_image_fallback_db: Path | None = None
    output_dir: Path = Path.home() / ".cache/almost-delicious/outputs"
    app_host: str = "127.0.0.1"
    app_port: int = Field(default=8001, ge=1, le=65535)
    recipe_warmup: bool = True
    openai_api_key: SecretStr = Field(default=SecretStr(""), repr=False)
    deepseek_api_key: SecretStr = Field(default=SecretStr(""), repr=False)
    ai_gateway_api_key: SecretStr = Field(default=SecretStr(""), repr=False)
    jev_api_key: SecretStr = Field(default=SecretStr(""), repr=False)
    openai_endpoint: str = "https://api.openai.com/v1/responses"
    deepseek_endpoint: str = "https://api.deepseek.com/chat/completions"
    jev_endpoint: str = "https://ai-gateway.vercel.sh/v1/evaluate"

    @field_validator(
        "es_ca_certs", "hf_home", "data_dir", "recipe_image_fallback_db", mode="before"
    )
    @classmethod
    def external_path(cls, value):
        if value is None or value == "":
            return None
        path = Path(value).expanduser()
        if not path.is_absolute():
            raise ValueError("Use an absolute path for external files")
        return path

    @field_validator("output_dir", mode="before")
    @classmethod
    def output_path(cls, value):
        if value is None or value == "":
            return Path.home() / ".cache/almost-delicious/outputs"
        path = Path(value).expanduser()
        if not path.is_absolute():
            raise ValueError("OUTPUT_DIR must be absolute")
        return path

    def credential(self, name):
        return getattr(self, name.lower()).get_secret_value().strip()

    def data_file(self, relative, *, required=False):
        if self.data_dir is None:
            if required:
                raise ValueError(
                    "Set DATA_DIR to an absolute directory or supply an explicit input path"
                )
            return None
        return self.data_dir / relative

    @property
    def image_database(self):
        return self.recipe_image_fallback_db or self.data_file("derived/image_fallback_v2.sqlite")

    def es_options(self, url):
        password = self.es_password.get_secret_value()
        if bool(self.es_username) != bool(password):
            raise ValueError("ES_USERNAME and ES_PASSWORD must be supplied together")
        options = {"verify_certs": True}
        if self.es_username:
            options["basic_auth"] = (self.es_username, password)
        if url.lower().startswith("https://") and self.es_ca_certs:
            options["ca_certs"] = str(self.es_ca_certs)
        return options


def get_settings():
    return Settings(_env_file=os.environ.get("ENV_FILE", ".env"))
