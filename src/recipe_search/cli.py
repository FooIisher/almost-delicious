"""Settings-aware local service entry point."""

import uvicorn

from recipe_search.settings import get_settings


def main():
    settings = get_settings()
    uvicorn.run("recipe_search.api.app:app", host=settings.app_host, port=settings.app_port)


if __name__ == "__main__":
    main()
