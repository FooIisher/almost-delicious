# Engineering review follow-up — 2026-11-05

## Addressed

- Images are no longer globally ignored by extension. Generated verification,
  outputs and Playwright directories remain ignored; docs PNG/JPEG can be tracked.
- Experiments use `uv run python`; their output location follows OUTPUT_DIR.
- Read-only image mapping SQLite retains thread-local reuse, with explicit close
  at application shutdown and finalization when the owning thread exits. Tests
  release connections and temporary directories explicitly.
- The temporary `ad-review.bundle` was deleted from the thesis workspace.

## Next refactoring pass

Do not split files merely to lower line counts; Ruff wrapping exposed existing
responsibilities. Preserve API URLs, snapshots, algorithms and diagnostic output.

1. `api/search.py`: isolate request/response models, search orchestration and
   response/flow-trace assembly. Keep the router thin and retain branch comparison,
   relaxation provenance and strict-first merging behavior.
2. `llm/content_generation.py`: isolate candidate preparation, eligibility
   execution/cache/retry orchestration, provider calls and summary validation.
   Retain independent Recipe Check/Generation and the existing source evidence
   rules. Migrate test patch targets alongside each extraction.
3. Extract one responsibility per reviewable commit. Run mock backend and browser
   regressions before the next extraction; do not combine with algorithm changes.

## Optional space cleanup — not executed

All historical worktrees, original prototypes, ZIP backups and Whisper cache are
retained. Tags alone do not preserve ignored private config, data or caches.
Review any local work and stop its server before removing a worktree. Use Git's
worktree command, not direct directory deletion:

```bash
git worktree list
git -C ../almost-delicious-history/1.1 status --short
git worktree remove ../almost-delicious-history/1.1
```

Git refuses a non-clean worktree; do not add --force to bypass this review.
A worktree can be recreated from v1.1 with `git worktree add --detach PATH v1.1`.
Deleting old project/data/ZIP/model-cache folders is a separate owner decision,
not part of this maintenance change.
