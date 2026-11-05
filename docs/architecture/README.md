For the current **1.2 implementation**, see [GENERATION_FLOW.md](GENERATION_FLOW.md) and `prototype-1.2-architecture.drawio`. The description below is the preserved 1.1 baseline.

# Prototype 1.1 — Current architecture

This is the implemented 1.1 baseline used to discuss Prototype 1.2, not a diagram of proposed 1.2 features.

Open `prototype-1.1-architecture.drawio` at https://app.diagrams.net/ using **File → Open From → Device**, then save to Google Drive if desired. All boxes, labels and connections remain editable. SVG and PNG are previews of the same content. Blue identifies browser/UI components, green identifies Python/backend work, amber identifies external model services and Elasticsearch, and gray identifies implementation notes.

The diagram follows the default Hybrid path. Intent parsing and retrieval are separate user-triggered operations. BM25-only and Vector-only modes bypass fusion and preference reranking. The ES node represents request execution and stored recipe data; branch-to-RRF connections carry the returned hits. Provider calls happen on the server, not directly in the browser.

Key implementation references:

- `prototype-1.1/web/intent-ui.js`: interpretation presentation, retrieval-content derivation and editable-field mapping.
- `prototype-1.1/gpt_intent_service.py` and `intent_service.py`: provider adapters and validation; JEV uses a separate extraction path.
- `prototype-1.1/recipe_search_api.py`: shared filters, lexical/vector requests, streamed responses and recipe details.
- `prototype-1.1/retrieval_execution.py`: parallel/serial scheduling, deadlines and degraded execution.
- `prototype-1.1/rrf.py` and `preference_ranking.py`: fusion, preference evidence, normalization and rating bonus.
- `prototype-1.1/semantic_search.py`: local BGE embedding; `recipe_display_image.py`: display-image fallback.

Current limitations are shown explicitly: no category semantic validation, automatic retrieval fallback, second LLM filtering pass or answer generation. Numeric constraints recognized by parsing are displayed but not automatically mapped into the numeric retrieval controls. Multiple included ingredients currently use all-of matching. Rating bonuses apply only at exact ratings 3, 4 and 5.

`build_architecture.py` regenerates the initial source and previews using Graphviz. Once the diagram is edited manually, treat the latest `.drawio` file as authoritative; regenerating would overwrite manual layout/content changes. Keep a copy before regeneration.
