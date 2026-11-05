"""Compatibility launcher for reconstructed snapshots; no recipe rules change."""

from __future__ import annotations
import argparse
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent


def prepare():
    config = Path(
        os.environ.get("ENV_FILE", Path.home() / ".config/almost-delicious/.env")
    ).expanduser()
    if not config.is_absolute():
        raise SystemExit("ENV_FILE must be an absolute path")
    load_dotenv(config, override=False)
    local = ROOT / ".env"
    if local != config:
        load_dotenv(local, override=False)
    return config


class LegacyAssets:
    """Old excluded raster assets get an explicit illustration, not a broken image."""

    def __init__(self, app):
        self.app = app

    def __getattr__(self, name):
        return getattr(self.app, name)

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if (
            scope["type"] == "http"
            and path.startswith("/assets/recipe-images/")
            and not (ROOT / "web" / path.removeprefix("/assets/")).is_file()
        ):
            from starlette.responses import FileResponse

            await FileResponse(ROOT / "web/legacy-placeholder.svg", media_type="image/svg+xml")(
                scope, receive, send
            )
            return
        await self.app(scope, receive, send)


def application():
    prepare()
    from recipe_search_api import app

    return LegacyAssets(app)


def main(default_port):
    parser = argparse.ArgumentParser(
        description="Run this historical snapshot using external configuration"
    )
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check routes, local resources, and ES without model calls",
    )
    args = parser.parse_args()
    config = prepare()
    if args.check:
        app = application()
        assert (ROOT / "web/index.html").is_file()
        assert "/health" in app.openapi()["paths"]
        from semantic_search import DEFAULT_ES_URL, DEFAULT_INDEX, connect_elasticsearch

        client = connect_elasticsearch(DEFAULT_ES_URL)
        try:
            if not client.indices.exists(index=DEFAULT_INDEX):
                raise SystemExit("Configured ES index is missing")
        finally:
            client.close()
        print("Snapshot imports, static files, ES and index: OK. No model calls made.")
        return
    import uvicorn

    uvicorn.run(
        application(),
        host=args.host or os.environ.get("APP_HOST", "127.0.0.1"),
        port=args.port or int(os.environ.get("APP_PORT", default_port)),
    )
