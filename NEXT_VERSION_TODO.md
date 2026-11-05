# Next-version TODO

## Candidate retrieval and semantic constraint validation

Recorded: 2026-10-15

Status: Proposal for discussion and evaluation only. Not approved for implementation. Prototype 1.1 behavior remains unchanged.

### Proposed direction

- [ ] Explore adding `entity_type: specific | category` to extracted ingredients, while preserving `role` and source evidence. Examples of categories include vegetable, meat, and seafood.
- [ ] Evaluate moving hard-constraint enforcement out of Elasticsearch and into post-retrieval processing to reduce false exclusions caused by extraction errors or incomplete ingredient data.
- [ ] Evaluate increasing retrieval candidates to 1000. Clarify whether this means per branch or after fusion; per-branch 1000 was suggested but not decided. Coordinate vector result count and kNN exploration settings.
- [ ] Explore a second model pass over retrieved candidates to judge category constraints and other semantically ambiguous ingredient requirements.
- [ ] Compare coverage, constraint compliance, result quality, latency, and API cost against the current implementation.

### Open design questions

- The original idea assigns score 0 to candidates that violate hard constraints. Evaluate the alternative of independent `pass`, `fail`, and `unknown` statuses: score 0 alone does not prevent display, and valid results can have negative preference-adjusted scores.
- Define violations explicitly: an unmet required condition or a matched excluded condition. Missing ingredient data should not automatically establish compliance.
- Determine which constraints can be checked deterministically and which need model validation.
- Consider preference presorting followed by bounded, batched semantic checks before final result truncation. Decide batch size, stopping criteria, timeout behavior, and treatment of unresolved candidates.
- Decide whether category-validation results also update preference scores and trigger a final reranking pass.
- Define handling when too few eligible results remain; do not silently relax explicit hard constraints.
- Consider caching semantic decisions by recipe content/version, category, model, and validation prompt version.
- Expose candidate counts, rule exclusions, model checks, unresolved cases, eligible results, and stage timings for evaluation.

Implementation should begin only after the proposal and evaluation scope are agreed.
