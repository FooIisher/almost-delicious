"""Packaging/configuration regressions; no ES or model calls."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from recipe_search import settings as settings_module
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

    def test_default_data_dir_is_checkout_data_folder(self):
        s = Settings(_env_file=None)
        if settings_module.default_data_dir() is not None:
            self.assertEqual(s.effective_data_dir, settings_module.PROJECT_ROOT / "data")
        explicit = Settings(_env_file=None, data_dir="/external/recipes")
        self.assertEqual(explicit.effective_data_dir, Path("/external/recipes"))

    def test_require_data_file_explains_missing_data(self):
        s = Settings(_env_file=None, data_dir="/nonexistent/recipes")
        with self.assertRaisesRegex(FileNotFoundError, "data/README.md"):
            s.require_data_file("recipes.parquet")

    @patch.object(settings_module, "default_data_dir", return_value=None)
    def test_missing_and_relative_data_are_explicit(self, _default):
        s = Settings(_env_file=None)
        with self.assertRaisesRegex(ValueError, "DATA_DIR"):
            s.data_file("recipes.parquet", required=True)
        with self.assertRaises(ValidationError):
            Settings(_env_file=None, data_dir="../data")

    def test_generated_files_live_under_work_dir(self):
        with tempfile.TemporaryDirectory() as folder:
            s = Settings(_env_file=None, work_dir=folder, data_dir="/external/recipes")
            work = Path(folder)
            self.assertEqual(s.output_dir, work / "outputs")
            self.assertEqual(s.vocabulary_file, work / "bm25_vocabulary.json")
            self.assertEqual(s.image_database, work / "derived/image_fallback_v2.sqlite")
        default = Settings(_env_file=None)
        if settings_module.is_source_checkout():
            self.assertEqual(default.work_dir, settings_module.PROJECT_ROOT / "var")

    def test_derived_reads_fall_back_to_data_dir(self):
        with tempfile.TemporaryDirectory() as work, tempfile.TemporaryDirectory() as data:
            legacy = Path(data) / "derived/image_fallback_v2.sqlite"
            legacy.parent.mkdir()
            legacy.touch()
            s = Settings(_env_file=None, work_dir=work, data_dir=data)
            self.assertEqual(s.image_database, legacy)
            generated = Path(work) / "derived/image_fallback_v2.sqlite"
            generated.parent.mkdir()
            generated.touch()
            self.assertEqual(s.image_database, generated)
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

    def test_ingest_explains_missing_source_data(self):
        result = subprocess.run(
            [sys.executable, "-m", "recipe_search.ingest.ingest_recipes"],
            env={**os.environ},
            text=True,
            capture_output=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DATA_DIR", result.stderr)


if __name__ == "__main__":
    unittest.main()
