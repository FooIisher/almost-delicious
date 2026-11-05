"""Local launch defaults and explicit overrides; never starts a server."""

import os
import unittest
from unittest.mock import patch

from recipe_search import cli
from recipe_search.settings import Settings


class LauncherTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {}, clear=True)
        env.start()
        self.addCleanup(env.stop)

    def test_local_default_port(self):
        with (
            patch("sys.argv", ["run_local.py"]),
            patch.object(cli, "get_settings", return_value=Settings(_env_file=None)),
            patch.object(cli.uvicorn, "run") as run,
        ):
            cli.main()
        self.assertEqual(run.call_args.kwargs["port"], 8001)

    def test_explicit_port_overrides_configuration(self):
        with (
            patch("sys.argv", ["run_local.py", "--port", "8123"]),
            patch.object(cli, "get_settings", return_value=Settings(_env_file=None, app_port=8001)),
            patch.object(cli.uvicorn, "run") as run,
        ):
            cli.main()
        self.assertEqual(run.call_args.kwargs["port"], 8123)

    def test_invalid_port_does_not_start(self):
        with (
            patch("sys.argv", ["run_local.py", "--port", "0"]),
            patch.object(cli.uvicorn, "run") as run,
            patch("sys.stderr"),
            self.assertRaises(SystemExit),
        ):
            cli.main()
        run.assert_not_called()
