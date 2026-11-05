"""Convenient local entry point, matching runnable historical snapshots."""

import os
from pathlib import Path

from recipe_search.cli import main

if __name__ == "__main__":
    if not Path(".env").is_file():
        os.environ.setdefault("ENV_FILE", str(Path.home() / ".config/almost-delicious/.env"))
    main()
