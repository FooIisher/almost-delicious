# Runnable compatibility version 1.3

This runnable v1.3 supersedes the initial source-only tag and temporary v1.3.1 name.
The compatibility changes fix only startup,
configuration and missing external assets; it does not redesign retrieval rules.
Shared JEV is the available reconstructed copy, not an independently recovered
historical model revision. ES data remains external and current, not versioned.

```bash
uv sync --frozen
uv run python run_local.py --port 8001
```

Configuration: process environment first, then `ENV_FILE` (absolute path; default
`~/.config/almost-delicious/.env`), then this checkout's ignored `.env`.
Copy `.env.example` to the external location and set credentials and absolute CA
path. No automatic key prompt, no paid calls at startup. A configured APP_PORT
overrides the shared local default 8001; --port overrides both.

```bash
uv run python run_local.py --check
```

The check imports the complete app, checks static resources and performs read-only
ES/index checks; no embeddings, ingest, or paid model calls. Startup warmup in
1.3 remains governed by RECIPE_WARMUP. Set RECIPE_WARMUP=0 to skip it.

Old raster fallback photos are not redistributed. When unavailable, an explicitly
labelled SVG illustration is served at the old URL. Optional image SQLite is
read from RECIPE_IMAGE_FALLBACK_DB or DATA_DIR, never a sibling prototype.

Use this snapshot in a Git worktree or switch to its .1 tag. No original project
folder is required. Return to main with `git switch main`.

## Verification

Live page, ES health and fallback assets passed when launched from /tmp.
327 tests ran: 326 passed; the original test_named_dish_emphasis_sole_and_or_remain_distinct failure remains. This is the previously recorded core-policy behavior, not a startup regression. It is fixed on main and deliberately not changed in this archival compatibility patch.
