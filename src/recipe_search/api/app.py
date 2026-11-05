"""Application assembly; no live connections are opened at import time."""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from recipe_search.api import search
from recipe_search.api.intent import router as intent_router
from recipe_search.api.content import create_router
from recipe_search.settings import PACKAGE_ROOT

app = FastAPI(title="Almost Delicious", version="1.3.0", lifespan=search.lifespan)
app.include_router(search.router)
app.include_router(intent_router)
app.include_router(create_router(lambda: search.get_client()))
app.mount("/assets", StaticFiles(directory=PACKAGE_ROOT / "web"), name="assets")
