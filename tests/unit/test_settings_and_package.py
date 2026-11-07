"""Packaging/configuration regressions; no ES or model calls."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from recipe_search.settings import PACKAGE_ROOT, Settings, get_settings


class SettingsTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {}, clear=True)
        env.start()
        self.addCleanup(env.stop)

    def test_defaults_and_keys_never_in_repr(self):
        settings = Settings(
            _env_file=None,
            es_username="elastic",
            es_password="unit-secret",
            openai_api_key="unit-api-key",
        )
        self.assertEqual(settings.app_port, 8001)
        self.assertNotIn("unit-secret", repr(settings))
        self.assertNotIn("unit-api-key", repr(settings))
        self.assertTrue(settings.es_options("https://localhost:19200")["verify_certs"])

    def test_environment_file_and_environment_precedence(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / ".env"
            file.write_text("APP_PORT=8123\nES_INDEX=fixture\n")
            with patch.dict(os.environ, {"ENV_FILE": str(file), "APP_PORT": "8124"}):
                s = get_settings()
                self.assertEqual(s.app_port, 8124)
                self.assertEqual(s.es_index, "fixture")

    def test_missing_and_relative_data_are_explicit(self):
        s = Settings(_env_file=None)
        self.assertIsNone(s.image_database)
        with self.assertRaisesRegex(ValueError, "DATA_DIR"):
            s.data_file("recipes.parquet", required=True)
        with self.assertRaises(ValidationError):
            Settings(_env_file=None, data_dir="../data")

    def test_external_paths_and_absent_mapping(self):
        s = Settings(_env_file=None, data_dir="/external/recipes")
        self.assertEqual(
            s.image_database, Path("/external/recipes/derived/image_fallback_v2.sqlite")
        )
        s = Settings(_env_file=None, recipe_image_fallback_db="/external/map.sqlite")
        self.assertEqual(s.image_database, Path("/external/map.sqlite"))

    def test_incomplete_auth_is_rejected(self):
        for values in [dict(es_username="elastic"), dict(es_password="unit-password")]:
            with self.assertRaisesRegex(ValueError, "supplied together"):
                Settings(_env_file=None, **values).es_options("https://localhost:19200")

    def test_blank_optional_paths(self):
        s = Settings(_env_file=None, data_dir="", es_ca_certs="", output_dir="")
        self.assertIsNone(s.data_dir)
        self.assertIsNone(s.es_ca_certs)
        self.assertTrue(s.output_dir.is_absolute())

    def test_shipped_assets_present(self):
        for path in [
            "web/index.html",
            "web/recipe-icons/soup.svg",
            "config/preference_rules.json",
            "llm/jev/intent_schema.py",
        ]:
            self.assertTrue((PACKAGE_ROOT / path).is_file(), path)

    def test_installed_package_import_outside_repository(self):
        env = {**os.environ, "RECIPE_WARMUP": "0"}
        env.pop("PYTHONPATH", None)
        with tempfile.TemporaryDirectory() as folder:
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    'from recipe_search.api.app import app; assert app.title == "Almost Delicious"',
                ],
                cwd=folder,
                env=env,
                text=True,
                capture_output=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_ingest_requires_explicit_source_without_data_dir(self):
        result = subprocess.run(
            [sys.executable, "-m", "recipe_search.ingest.ingest_recipes"],
            env={**os.environ},
            text=True,
            capture_output=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Supply --source-url or set DATA_DIR", result.stderr)


if __name__ == "__main__":
    unittest.main()
