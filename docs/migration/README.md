# Migration record

- Remote: https://github.com/FooIisher/almost-delicious.git (initially empty).
- Source: existing prototype-1.0 through prototype-1.3 directories.
- Original folders, ZIP backups, data, thesis material and running ES are unchanged.
- Tags reconstruct sanitized source snapshots; no original commit dates are invented.
- A separate baseline fix limits explicit ingredient emphasis before a new with-clause.
- Shared JEV modules are packaged under llm/jev; prior revisions were unavailable.
- API URLs and algorithm rules are retained. The new application has no top-level
  import-path shims and needs no sibling model/data folder.
- Unused legacy raster images and generated verification artifacts are excluded.
- The initial 1.3 baseline had 323 tests with one core-policy failure; the isolated
  fix brought that baseline to 323 passing tests before moving files. The packaged
  suite adds shared JEV tests plus configuration/installation regressions.
- Requirements are declared in pyproject.toml and resolved in uv.lock. Browser
  dependencies are locked separately in package-lock.json. Linux uses CPU PyTorch.

Publication remains pending owner confirmation that the original ES/Gateway
credentials have been rotated. See SECURITY.md. Migration logs/screenshots are
local verification artifacts rather than committed historical experiment results.
