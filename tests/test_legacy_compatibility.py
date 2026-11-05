"""Only compatibility, no real ES/provider requests."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import legacy_runtime


class LegacyCompatibilityTests(unittest.TestCase):
    def test_external_environment_and_precedence(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Path(directory) / "private.env"
            env.write_text("ES_INDEX=from-file\n")
            with patch.dict(
                os.environ, {"ENV_FILE": str(env), "ES_INDEX": "from-process"}, clear=True
            ):
                self.assertEqual(legacy_runtime.prepare(), env)
                self.assertEqual(os.environ["ES_INDEX"], "from-process")
            with patch.dict(os.environ, {"ENV_FILE": str(env)}, clear=True):
                legacy_runtime.prepare()
                self.assertEqual(os.environ["ES_INDEX"], "from-file")

    def test_relative_configuration_rejected(self):
        with patch.dict(os.environ, {"ENV_FILE": "relative.env"}, clear=True):
            with self.assertRaises(SystemExit):
                legacy_runtime.prepare()

    def test_application_static_and_fallback(self):
        from fastapi.testclient import TestClient

        with (
            patch.dict(os.environ, {"RECIPE_WARMUP": "0"}),
            patch.object(legacy_runtime, "prepare"),
        ):
            app = legacy_runtime.application()
        client = TestClient(app)
        self.assertEqual(client.get("/").status_code, 200)
        image = client.get("/assets/recipe-images/missing-1.png")
        self.assertEqual(image.status_code, 200)
        self.assertIn("image/svg+xml", image.headers["content-type"])
        self.assertIn("original photo unavailable", image.text)
        self.assertIn("/health", app.openapi()["paths"])

    def test_jev_modules_are_self_contained(self):
        if not (legacy_runtime.ROOT / "intent_service.py").exists():
            return
        import intent_service

        self.assertEqual(intent_service.MODEL_DIR, legacy_runtime.ROOT / "model")
        self.assertTrue(Path(intent_service.jev.__file__).is_relative_to(legacy_runtime.ROOT))
