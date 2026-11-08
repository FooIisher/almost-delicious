"""Environment-backed configuration. Secrets are never packaged or logged."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PACKAGE_ROOT = Path(__file__).resolve().parent
# Repository root when running from a source checkout (src/ layout).
PROJECT_ROOT = PACKAGE_ROOT.parents[1]


def is_source_checkout():
    return (PROJECT_ROOT / "pyproject.toml").is_file()


def default_data_dir():
    """The repository's data/ folder in a source checkout; None when installed."""
    candidate = PROJECT_ROOT / "data"
    if is_source_checkout() and candidate.is_dir():
        return candidate
    return None


def default_work_dir():
    """Generated files: <repo>/var in a checkout (git-ignored), else a user cache."""
    if is_source_checkout():
        return PROJECT_ROOT / "var"
    return Path.home() / ".cache" / "almost-delicious"


def missing_data_message(path):
    return (
        f"{path} not found. Put the data under the repository's data/ folder "
        "(see data/README.md), set DATA_DIR in .env to the absolute folder that "
        "contains it, or pass the path explicitly."
    )


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
    bm25_vocabulary: Path | None = None
    # Root for everything this project generates (vocabulary, derived data, caches,
    # outputs). Default <repo>/var, which git ignores.
    work_dir: Path | None = None
    output_dir: Path | None = None
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
        "es_ca_certs",
        "hf_home",
        "data_dir",
        "recipe_image_fallback_db",
        "bm25_vocabulary",
        "work_dir",
        mode="before",
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
            return None
        path = Path(value).expanduser()
        if not path.is_absolute():
            raise ValueError("OUTPUT_DIR must be absolute")
        return path

    @model_validator(mode="after")
    def default_generated_paths(self):
        if self.work_dir is None:
            self.work_dir = default_work_dir()
        if self.output_dir is None:
            self.output_dir = self.work_dir / "outputs"
        return self

    def credential(self, name):
        return getattr(self, name.lower()).get_secret_value().strip()

    @property
    def effective_data_dir(self):
        """DATA_DIR if set, otherwise the checkout's data/ folder."""
        return self.data_dir or default_data_dir()

    def data_file(self, relative, *, required=False):
        base = self.effective_data_dir
        if base is None:
            if required:
                raise ValueError(
                    "Set DATA_DIR to an absolute directory or supply an explicit input path"
                )
            return None
        return base / relative

    def require_data_file(self, relative):
        """Return DATA_DIR/relative, or raise with instructions when it is missing."""
        path = self.data_file(relative, required=True)
        if not path.exists():
            raise FileNotFoundError(missing_data_message(path))
        return path

    @property
    def vocabulary_file(self):
        """Generated matching vocabulary (WORK_DIR, never versioned)."""
        return self.bm25_vocabulary or self.work_dir / "bm25_vocabulary.json"

    @property
    def derived_dir(self):
        """Where the offline steps write derived data."""
        return self.work_dir / "derived"

    @property
    def cache_dir(self):
        return self.work_dir / "cache"

    def run_output(self, name, suffix=""):
        """A new, timestamped path under OUTPUT_DIR (var/outputs) for one run."""
        from datetime import datetime

        return self.output_dir / f"{name}-{datetime.now():%Y%m%d-%H%M%S}{suffix}"

    @property
    def model_cache_dir(self):
        """Hugging Face cache: HF_HOME if set, otherwise var/cache/huggingface."""
        return self.hf_home or self.cache_dir / "huggingface"

    def apply_model_cache(self):
        """Point Hugging Face at the project cache before a model is loaded."""
        path = self.model_cache_dir
        path.mkdir(parents=True, exist_ok=True)
        os.environ["HF_HOME"] = str(path)
        return path

    def derived_file(self, name):
        """Read location of a derived file: WORK_DIR/derived first, then the older
        DATA_DIR/derived; returns the WORK_DIR path when neither exists yet."""
        generated = self.derived_dir / name
        legacy = self.data_file(f"derived/{name}")
        if not generated.exists() and legacy is not None and legacy.exists():
            return legacy
        return generated

    @property
    def image_database(self):
        return self.recipe_image_fallback_db or self.derived_file("image_fallback_v2.sqlite")

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


def default_env_file():
    """The repository's .env in a checkout (any working directory), else ./.env."""
    return PROJECT_ROOT / ".env" if is_source_checkout() else Path(".env")


def get_settings():
    return Settings(_env_file=os.environ.get("ENV_FILE") or default_env_file())
