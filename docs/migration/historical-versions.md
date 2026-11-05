# Running historical versions

The original reconstructed tags `v1.0`, `v1.1`, `v1.2`, `v1.3` are immutable
archives. Their hashes have not moved. They were source snapshots, not complete
runnable releases: the shared JEV path, private configuration, dependencies and
excluded fallback photos needed compatibility work.

Runnable compatibility tags are `v1.0.1`, `v1.1.1`, `v1.2.1`, `v1.3.1`.
Each is a child of its own original snapshot, not of today's main branch.
The patches fix startup/configuration/assets and tests, not recipe algorithms.
Dependencies are newly locked to the verified runtime; they do not claim to
reconstruct the original unrecorded dependency versions.

## Switch in the same directory

Stop the current server first. Commit or stash any source edits before switching.
Ignored `.env` and `.venv` are not versioned; always sync after switching:

```bash
git switch --detach v1.1.1
uv sync --frozen
uv run python run_local.py --port 8001
```

Open http://127.0.0.1:8001/. Return to the current line:

```bash
git switch main
uv sync --frozen
uv run python run_local.py
```

Do not use the new packaged `recipe_search.api.app` import on the historical
flat-layout versions. Their `run_local.py` selects the appropriate old entry.

## Parallel worktrees

The migration has prepared these worktrees beside the repository:

- `almost-delicious-history/1.0` on `compat/1.0`
- `almost-delicious-history/1.1` on `compat/1.1`
- `almost-delicious-history/1.2` on `compat/1.2`
- `almost-delicious-history/1.3` on `compat/1.3`

Each can independently run `uv sync --frozen` and `uv run python run_local.py
--port PORT`. Alternatively, create a new detached worktree from a compatibility
tag with `git worktree add --detach PATH v1.1.1`.

## External configuration and data

Historical launchers read process environment, then `ENV_FILE` (absolute path;
default `~/.config/almost-delicious/.env`), then the checkout's ignored `.env`.
Process environment has highest priority. The current validated private config
has been copied to the external default once with permissions 0600. Future edits
to one file do not synchronize automatically; use `ENV_FILE` to choose one source.
No credentials or certificates are committed.

Use `ES_CA_CERTS` pointing to the existing external CA. `ES_URL`, `ES_INDEX` and
`EMBEDDING_MODEL` are respected. Optional image mapping/data uses explicit paths,
not old prototype folders. Missing old fallback photos use an explicitly labelled
SVG illustration at the old asset URL. Current ES data is shared; switching code
cannot reconstruct the old database or old model outputs.

`uv run python run_local.py --check` validates imports, resources and the existing
ES/index without embeddings or paid model calls. `--port` overrides APP_PORT;
without either, historical defaults are 8000/8001/8002/8003. Disable the historical
1.3 warmup with RECIPE_WARMUP=0 when required.

Publication still waits for credential rotation confirmation. Original tags and
compatibility tags will both be scanned before any push.

## Acceptance results

All four compatibility versions installed with `uv sync --frozen`, passed their
four startup compatibility tests, and served page/ES health/fallback assets and
a real BM25 search from /tmp. No paid model calls or index writes were made.
Full historical suites: 1.1 = 77 passing; 1.2 = 304 passing. 1.3 = 326 passing
and one known original core-policy failure, retained to preserve old behavior
(`test_named_dish_emphasis_sole_and_or_remain_distinct`); main already fixes it.
1.0 had no historical unit suite; its four new compatibility tests pass.
The complete Git history, including all eight tags, passes the secret scan.
