# Recipe Search Prototype 1.2

Independent runnable baseline copied from Prototype 1.1. Architecture documents remain in `docs/architecture/`.

## Run

Use the same installed Python dependencies and Elasticsearch configuration as 1.1:

```zsh
cd "/path/to/thesis/project/prototype-1.2"
python run_local.py
```

Open http://127.0.0.1:8002/ (API docs: http://127.0.0.1:8002/docs).
Prototype 1.1 can continue on port 8001. The existing recipe index is shared; this change does not reindex or rewrite data.

Set `OPENAI_API_KEY` and/or `DEEPSEEK_API_KEY` in the launching shell. The launcher accepts either provider key; if neither exists it prompts for OpenAI. Keys are not copied from another server process. To start without a key prompt (for retrieval-only use or JEV), use:

```zsh
python -m uvicorn recipe_search_api:app --host 127.0.0.1 --port 8002
```

DeepSeek uses the official direct endpoint; OpenAI and DeepSeek credentials are separate. JEV retains its legacy provider/configuration and does not support category classification.

## Ingredient classification

The four generative models share `recipe-extraction-v4`. Every extracted ingredient requires:

```json
{
  "name": "vegetable",
  "entity_type": "category",
  "role": "excluded",
  "evidence": "vegetables"
}
```

- `entity_type`: `specific` or `category`, classified by meaning rather than database availability.
- `role`: existing `available`, `required`, `excluded`, `prefer`, or `avoid`.
- Specific required/excluded ingredients populate editable include/exclude filters. Specific available/prefer/avoid ingredients populate existing ranking preferences.
- Categories retain roles and evidence. Positive roles (required/available/prefer) populate a separate BM25 keywords boost panel; excluded/avoid remain unapplied. Categories never populate ingredient hard filters or final preference controls, and keyword bonuses do not establish compliance.
- Automatic required-ingredient query construction uses specific ingredients only. Category words already in a positive dish name or search description can remain in the query; relevance does not establish constraint satisfaction.
- A category alone does not prevent recipe search or require clarification. Invalid evidence/schema still blocks automatic field filling.
- Each successful ready interpretation replaces automatic field values, including clearing previous values. Manual edits continue to use the existing field semantics.
- JEV uses the legacy schema/path with an explicit unsupported-capability notice; its old ingredient mapping is unchanged.

Examples: `must have beef, no vegetables` applies beef include and only displays the vegetable exclusion; `exclude onion and meat` applies onion exclusion and only displays meat exclusion. Categories are not expanded into invented specific ingredients.

## Preserved retrieval behavior

BM25 and vector initially use the same ES filters; BM25 may retry without ingredient filters below its fallback threshold; Hybrid supports parallel/serial execution, weighted RRF and recipe-ID deduplication. All included ingredients must match substrings, excluded ingredients must not match; manual Labels match any exact category/keyword. Numeric filters remain manually editable.

Hybrid defaults to 500 candidates per branch. RRF retains the top 100 unique recipes before preference reranking, then returns the requested result count:

`Final = Normalized RRF + preference_lambda × Preference Score + Rating bonus`

Rating 5/4/3 receives 1/0.8/0.6 times `rating_boost`; other ratings receive zero. Existing settings, defaults, candidate limits (2000 per branch), fallback images, diagnostic output and stage timings are preserved.

Content Generate now performs candidate category checking and grounded recommendation generation. It does not alter retrieval scores, automatically expand recall, substitute ingredients or generate cooking steps.

## Three-stage recipe RAG demo

Submit your English request to reveal **Intent Analysis**. Choose a parsing model and click Analyze intent, then open **Data Retrieval** to review/edit mapped fields. The Retrieval button is in the card header. Retrieved cards, timings and recipe details remain available in that stage. Open **Content Generate**, choose a generation model (default DeepSeek Flash), and click Generate.

Generation uses ordered retrieval candidate IDs (RRF Top 100 in Hybrid). With category required/excluded constraints, all candidates are checked sequentially in batches of 20 using ID, name and full recorded ingredients only. Passed candidates retain retrieval order; at most 20 are sent to the summary model. Unknown candidates are displayed separately and never included as confirmed recommendations. Without hard categories, the existing single-call generation path is retained. The default recommendation count is five; explicit requested counts remain supported within the existing limits. It independently reads stored recipe data by ID; hard-category checks and recommendation summaries use separate calls. Explicit required/excluded category violations are rejected from recommendations. Unknown hard-category candidates appear only in a separate Needs confirmation section; all candidate checks remain inspectable. No generated HTML is trusted. Upstream changes invalidate downstream results and late responses are ignored.

The API is `POST /content/generate/{model_key}` for `gpt41-mini`, `gpt41-nano`, `gpt6` and `deepseek-flash`. Request fields: `query`, `intent_snapshot` (the parsing response), `retrieval_snapshot` (actual search request), and `recipe_ids` (ordered generation candidate IDs, at most 100). Response includes summary, recommendations, complete category assessments, compact stored recipe data, warnings, model/schema/prompt versions, timings and usage. The backend allows two concurrent generation calls, a 60-second provider timeout, no automatic retries and a 120,000-character input budget. Missing records are omitted with warnings; no usable records, invalid context, failed generation or invalid output never produce a successful recommendation payload.

See `docs/architecture/GENERATION_FLOW.md` and the new `prototype-1.2-architecture.drawio` for implemented information flow. Existing online diagrams are unchanged. Browser workflow checks use mocked provider/retrieval responses and do not measure live model quality or cost.

## BM25 matching boosts

The editable BM25 matching panel receives dish name/type, cuisine and positive ingredient categories from parsing. The original lexical `must` and all hard filters remain unchanged; optional constant-score bonuses use outer `minimum_should_match: 0`, so they cannot independently qualify a document. Top-N membership can change after scoring. Dish name uses `match_phrase` on `name` (+12), replacing the old whole-query phrase boost; with no dish name it falls back to Query. Dish type (+5) and cuisine (+2) match either keywords or category, rewarded once each. Specific required ingredients get +2 for exact ingredients terms. Each positive category gets +2 for an exact keywords term only; vegetables/Vegetabels/vegatable normalize to vegetable and duplicate canonical categories count once. Category excluded/avoid roles are not auto-filled into this positive-only panel. Vector input/filtering and final preference formula are unchanged. Matched query names are exposed per result for explanation. These are retrieval bonuses, not category compliance checks.

## BM25 singular/plural compatibility

Optional BM25 rewards now use `terms` alternatives for required specific ingredients, positive ingredient categories and dish-type tags. English suffix rules and explicit irregular/invariant exceptions generate candidate forms; a field-specific vocabulary snapshot keeps only forms present in that field. Unknown forms fall back to the original normalized input. Cuisine exact matching and dish-name phrase matching are unchanged. Each wordform group is a single constant-score reward, including when both forms are present or supplied twice. Hard ingredient filters, the required lexical query, Vector retrieval and final preference reranking remain unchanged.

The bundled `config/bm25_vocabulary.json` is derived from the local 522,517-recipe parquet using current ingestion/tag normalization rules. It is not a live ES dictionary. If ES ingredient/tag values are modified independently, refresh the source/snapshot accordingly. To rebuild without writing to ES:

```zsh
python scripts/build_bm25_vocabulary.py
```

This is conservative grammatical matching, not semantic category expansion. It does not equate broccoli with vegetable, fix arbitrary spelling mistakes or guarantee all English inflections.

## Numeric constraints

Parsed numeric bounds appear in an editable **Numeric constraints** section. Comparisons preserve strictness: under/less than → `<`; within/at most → `≤`; over → `>`; at least → `≥`. Model extraction normalizes hours to minutes and dietary calories/cal to kcal; schema/unit validation runs before filling the controls.

Each bound carries `basis`: time uses `not_applicable`; nutrition uses `per_serving`, `whole_recipe`, `per_day`, or `unspecified`. Only explicit per-serving nutrition is enabled automatically. Other nutrition bounds stay unchecked with a warning. Users must confirm and, if needed, edit a per-serving value before enabling; the application does not divide whole-recipe/day values automatically. Recipe calorie/protein values use the prototype's existing per-serving data convention, not newly verified source metadata.

The search API accepts `numeric_filters`: a list of `{field, operator, value, basis}`. Supported fields are `total_time`, `calories`, `protein`; operators are `lt`, `lte`, `gt`, `gte`, `eq`. Time maps to `total_time_minutes`, protein to `proteincontent`. Nutrition must declare `per_serving`; unresolved bases are rejected. Multiple bounds are combined with AND, missing values fail active range conditions, and identical filters apply to BM25 and Vector. `eq` uses equal lower/upper bounds. Legacy maximum controls remain inclusive and combine with these filters if manually populated.

Successful ready parsing clears old automatic numeric conditions and legacy time/calorie controls before filling the new ones. Results show active numeric filters. Parsing alone does not execute retrieval.

## Verification

```zsh
python -m unittest discover -s tests
node tests/test_ingredient_categories_ui.cjs
node tests/test_numeric_bounds_ui.cjs
```

Python tests mock provider responses and cover shared schemas, category presentation, evidence rejection and unchanged search/ranking behavior. The dependency-free Node test exercises the actual intent UI and search form request builder, including field clearing and manual edits.

`tests/browser_workflow.mjs` runs the real UI with Playwright/Chrome against a running local server (default port 8003; override `WORKFLOW_TEST_URL`). It intercepts model, search, health and detail requests with synthetic responses, verifies error/retry and stale response rejection, and saves desktop/mobile screenshots under `/tmp`. Install/use Playwright separately, or set `PLAYWRIGHT_MODULE` to an available module entrypoint. It never calls a paid model.

`tests/fixtures/legacy-gpt-intent.json` is an unchanged copy of the historical fixture; tests adapt it in memory. Historical evaluations and failure records remain in 1.1 and were not migrated or modified. Live runs must record the new schema/prompt versions independently.

## Top 100 semantic checks (generation-v4)

Search returns `generation_candidate_ids` independently of displayed Results. Generate accepts up to 100 unique IDs and refetches stored records. `POST /content/generate/{model_key}?stream=true` streams progress, result or error events; the JSON endpoint remains available. A category hard constraint enables sequential batches of 20, then one pass-only summary call with up to 20 recipes. Each provider call has a 60-second timeout, no automatic retry; the browser allows 420 seconds for five batches plus summary. Disconnect prevents subsequent calls after the active call completes.

Responses include `constraint_counts`, `pending_recipe_ids`, `category_check_ms`, `summary_ms`, aggregate usage, and `model_calls` with per-call input/output, timing, usage and prompt version. A failed batch stops the workflow and exposes completed diagnostics, never partial recommendations. Input ingredient data is never silently truncated. Cooking steps are displayed from stored records, never generated. Missing records are warned and omitted; no records means no model call. Real-model quality/cost acceptance remains separate from mocked regression tests.

## Intent token usage and cost

Intent responses retain raw `usage` and add normalized `token_usage` (input, output, total, cached input) and `cost_estimate` in USD. Only provider token counts are used; missing usage or unknown model pricing is unavailable, never assumed free. The UI shows the values in the intent overview and full interpretation, including schema-validation failures after a provider response.

The pricing snapshot is versioned `2026-10-18` in `intent_usage.py`, with official model-page sources. OpenAI estimates use standard text-token rates and subtract cached input before charging uncached input. Unreported cache use produces a range. DeepSeek estimates span official off-peak/peak rates rather than infer public holidays or invoice time bands. Discounts, credits, taxes, separate cache writes and unreported fees are excluded. Unknown models/unsupported service tiers retain token counts but no cost estimate. JEV has no configured price. This is a per-request estimate, not a billing ledger or actual account deduction.

## Generation usage and estimated cost

Generation adds the same normalized `token_usage` and `cost_estimate` as intent parsing, at workflow total, `phase_usage` (category checks / summary) and individual `model_calls` levels. Costs are computed for each actual response before summing, retaining cache discounts and DeepSeek price ranges. Partial/unknown pricing is explicitly incomplete, never counted as free. Invalid model output still records provider-reported usage; request failures without a response cannot establish the provider's actual charge. The Generate card shows totals above recommendations; expanded research details retain each call's input/output, usage and estimate.

## Early ingredient conflict clarification

The shared generative intent prompt now checks dish identity / required ingredients against exclusions, including category relationships. Vegetable soup with no vegetables, or beef soup with no meat, should request clarification while retaining both original constraints and evidence. Explicit broth-versus-pieces distinctions must not become a blanket category exclusion; scoped restrictions remain visible rather than falsely claimed as enforced.

After schema/evidence validation, Python adds a deterministic clarification for identical normalized required/excluded ingredient names, even if the model omits it. Name comparison folds case/whitespace and explicitly aliases category vegetables to vegetable; it does not infer memberships or remove arbitrary plural suffixes. Available/prefer/avoid overlaps do not trigger this rule. The output schema remains recipe-extraction-v4; the shared prompt hash changes. JEV retains its legacy behavior.

Needs clarification opens the full interpretation, blocks downstream stages and preserves the questions and usage/cost statistics. New input or analysis invalidates previous retrieval/generation; non-ready results never auto-fill retrieval fields. Existing model questions are retained, and identical normalized fallback questions are not appended again. Model semantic recognition still needs live evaluation; mocked tests verify integration and deterministic fallback without extra calls or overwriting historical experiments.

## Generated recipe detail fallback

Generated and pending recipe titles/images first request live recipe detail by ID. If live reads fail, the modal can display that same ID's saved generation record, prominently marked as a saved snapshot. Missing fields stay missing; it never substitutes another recipe or model-authored steps. Retrieval-only cards without a generation snapshot continue to show a load error. Closing or opening another detail prevents stale responses from reopening/overwriting the modal. Snapshot display does not establish category compliance or repair semantic classification errors. Full candidate-check headings include IDs to trace classification decisions to summary inputs.

## Final category recheck

The recommendation-summary call retains the original category constraints and prior per-recipe assessments. Its returned checks are validated again; a recipe changed to fail or unknown cannot be recommended even with a disclaimer. Rechecked decisions update the full candidate counts/pending list. No additional model call is introduced. This is defense in depth against inconsistent model classifications, not a guarantee of semantic truth; per-call outputs and candidate IDs remain the evidence for diagnosing a specific run.

## Semantic membership and empty recommendation handling

Category prompts explicitly classify provided ingredient names using ordinary culinary knowledge: onion is a vegetable even if the literal category word is absent. Prior decisions based only on missing category words must be reassessed. The prompt version changes; schema stays v4.

A well-formed summary assessment that flags a selected recipe fail/unknown now causes that recommendation to be removed, not a generation-wide error. Counts and pending candidates are updated; if removals occur, the model's original summary is replaced with a safe summary so it cannot keep promoting removed recipes. `filtered_recommendations` and selection counts preserve the audit trail. All rejected selections yield a successful empty result with no automatic extra model call. Structural errors, unknown/duplicate IDs, incomplete check coverage or invalid ingredient evidence still fail validation. Live model accuracy must be assessed separately; prompt rules cannot guarantee semantic correctness.

## Label-scope retrieval

When a ready interpretation has neither dish_name nor dish_type but includes meal_type or cuisine, the UI automatically selects `label_scope`. Search description remains the editable Vector semantic query; it is not deleted or used as a BM25 text requirement. Requests with a dish target retain the existing text strategy. Users can switch strategies and edit scope fields. Reanalysis replaces/clears the automatic scope fields.

SearchRequest adds `retrieval_strategy: text | label_scope` (default text), `scope_meal_types`, `scope_cuisines`, and `bm25_available_boost` (default 2, 0 disables). Every nonempty scope group must match either keywords or recipecategory, case-insensitively. Groups combine with AND; values within a group combine with OR. At least one scope group is required. Scope fields are rejected in text mode. Manual Labels remain a separate any-label filter.

Both branches use the scope alongside existing concrete ingredient/numeric filters. BM25 scope uses match_all within these filters, with no multi_match or title-phrase query. Optional Available ingredients use literal substring matching and vocabulary-backed singular/plural variants, with one constant bonus per ingredient group; they do not qualify recipes outside the scope or become must-include conditions. This is not semantic synonym/category expansion. Ties sort by recipeid for stable scope candidate ordering. These recall bonuses are separate from the existing post-RRF Available preference weight.

Vector still embeds Query and applies the same scope. Empty Query is allowed only for BM25-only label scope. BM25 ingredient fallback retains all scope/numeric/manual-label conditions. Existing 500-per-branch defaults, RRF Top 100 and final Results count are unchanged. Responses identify retrieval_strategy, query_role and actual scope filters; the diagram and result chips expose the range used. Untagged otherwise-relevant recipes can be excluded; scope is never silently relaxed. Generation receives the actual edited scope snapshot.

### Generation context budget
Summary calls consider at most 20 ranked eligible recipes, including when no hard ingredient categories are present. Complete ingredient lists are preserved; full source instructions remain in returned page data and are not sent to the summary model. If necessary, lower-ranked summary candidates are removed to fit the local 120,000-character payload limit, with an explicit warning. Hard-category batch checks still cover the full candidate set. An oversized single/batch input stops before dispatch; diagnostics retain the prepared provider body, identify the context phase, and distinguish it from an ES fetch failure.

### Independent branch queries
The browser exposes editable BM25 query and Vector semantic query fields. Both initially receive derived positive retrieval content; subsequent edits are independent. Search requests send bm25_query and vector_query, and legacy query-only clients remain supported (omitted branch values inherit query; explicitly empty active queries are rejected). Label scope skips BM25 text matching; inactive query controls preserve their values. Inspector snapshots record the executed BM25 lexical query and the actual Vector embedding text. Retrieval and generation snapshots preserve both branch fields.

## Current constraint semantics (2026-10-21, v5)
The current rules supersede earlier category-only validation and replacement-style BM25 fallback notes above. See [unified information flow](docs/architecture/GENERATION_FLOW.md): editable required AND/OR groups, safe ES projection, original→any→none required-only supplemental recall, immutable original final standards, local plus pending semantic eligibility, adaptive 20-item batches and explicit not_checked records. Extraction/generation schemas are v5. Restart the service and reload the browser together. No reindex is needed and historical experiments remain unchanged.

## Current execution policy — v6 (supersedes earlier scope descriptions)

Meal/cuisine are recall boosts in both branches, never automatic ES filters. Generate ignores meal type as a hard condition; broad requests without either dish target enforce required cuisine, while preferred or dish-associated cuisine remains soft. Only fully passing hard conditions can be recommended. Editable backend-built positive queries include a Vector scope query and beta=0.30. Legacy label_scope requests are rejected; manual Labels still filter.

All retrieval modes default to 500 per active branch, retain Top 100, and support optional preference/rating reranking. BM25 required-only fallback uses each current stage count and retains strict candidates. Rating 3–5 uses rating/5; meal mappings take the highest match. See [current architecture and generation rules](docs/architecture/GENERATION_FLOW.md). Historical experiment outputs remain unchanged.

## Retrieved recipes: independent branch tabs

BM25 and Vector tabs show raw recall order, before fusion/preference reranking. Each can be edited and run independently. Hybrid Refresh always runs both branches with the latest fields, then RRF and the enabled preference rerank. Shared constraints apply to both; changed branch fields invalidate that branch and Hybrid, while fusion-only edits leave raw branch snapshots usable. Switching tabs does not issue requests. Hybrid responses include `branch_results` with raw displayed lists/counts and raw Top 100 IDs, without extra ES queries. Existing Generate remains available for the selected valid snapshot; switching candidate basis invalidates previous generation output. Old responses are discarded after edits, new intent or interrupted requests.

Restart the backend to expose `branch_results`; refreshing frontend assets alone cannot add the backend response fields.

## Excluded ingredients: recorded-list absence default

With a nonempty recorded ingredient list, an unlisted excluded specific ingredient passes locally. For excluded categories, semantic membership is still checked (broccoli can violate no vegetables); when no member can be identified, including uncertain blend components, assume absence rather than filtering. Checks record `assumed_absent=true` and describe the assumption as “not listed”, not verified ingredient-free/allergy-safe. Positive recorded matches still fail exclusions. Required conditions keep their existing unknown behavior. Entirely missing/empty ingredient lists remain unknown. Shared generation/check prompts and their hashes reflect this policy; historical runs are unchanged.


## Recipe Check / Generation split (2026-10-23)

Restart the Python backend and reload the page for the four-stage flow. Retrieval performs an automatic, key-free local preview; Check candidates runs paid semantic checks only when needed. Continue to generation only navigates; Generate invokes the independently selected summary model. Both models default to DeepSeek Flash. Generation settings contain the default-on semantic recheck toggle.

The new eligibility endpoint and eligibility_id summary request are documented in docs/architecture/GENERATION_FLOW.md. Existing generate request bodies remain supported by a serial-check compatibility wrapper. Split checking may dispatch two batches at once, so an already-issued second batch can increase calls/cost relative to serial. No performance improvement is promised. Pools are in-memory (20 LRU entries / 30 minutes); expired or restarted-server IDs require a manual re-check. Cache reuse reports current-call cost separately from prior check usage. The supplement data is not used for new eligibility rules in this release.


## Instruction-extracted ingredient matching (2026-10-23)

The current implementation uses extract_ingredients together with ingredients for ES filtering/rewards, preference reranking, local/semantic checks and summary rechecks. Same-target matches across both fields earn one bonus. This supersedes the earlier split-release boundary about supplement fields: full extract_ingredients now participates, while extract_ingredients_firm / extract_evidence-based policy is not added. Arrays are kept separate in source displays, with Mentioned in instructions provenance in check/generated details. Model schema is recipe-generation-v7 and frontend is 1.2.54; restart backend and reload the page.

The local vocabulary was refreshed from current ES. After later data updates, run `python scripts/refresh_extracted_vocabulary.py` and restart the service. This reads ES and updates only the local vocabulary, not index documents or embeddings.


### Result clarity and retrieval payload update (2026-10-25)
Dish identity excludes spicy/easy/quick/healthy/fast modifiers (quick bread is preserved); original evidence remains unchanged. Flavor is an editable ranking preference with recorded title/tag evidence. Instructions may ground dish identity using a continuous verbatim excerpt, canonicalized to the original full step; other fields still require complete values.
Retrieval defaults to 500 per branch, Top 100 unchanged. Full instructions and instruction extraction evidence are excluded from recall responses; Check, Generation and Detail independently fetch source records. Research details collect flow, advanced parameters, comparisons and timings after the result list. Shared constraints start open. Recommendation ingredients and instructions start collapsed. Only backend eligibility states group candidates; sole-core relaxation provides a current-candidate notice, not a claim about the entire library.


### Symbolic dish-form fallback images (2026-10-25)
Fallback selection evaluates name, then keywords/category, then ingredients. Each tier uses word-boundary patterns for dish forms; specific forms precede broad baked/dessert terms. Main proteins do not select a fallback. Nine dish forms plus a neutral Recipe icon use one local SVG each, with an explicit category caption. Original HTTP(S) photos remain unchanged. Missing/failed photos use compact icon layouts in Retrieval, Generation and Detail; original photos retain their photo layout. No ES writes or reindexing; legacy raster assets are no longer selected. UI assets: 1.2.80.

Image alignment refinement (assets 1.2.81): fallback icons now use the original image slot dimensions in retrieval, generation and detail. Category labels are contained inside the image frame. This supersedes the earlier compact missing-image layout. No backend or index change.

### Ranked-prefix qualification (2026-10-25)
Qualification stops only when every candidate up to the target-th pass has a concluded eligibility state. The ranked frontier is recomputed after each wave; only unresolved candidates within that frontier are submitted, at most 20 per batch and two in parallel. Without enough passes the frontier covers remaining candidates, subject to the existing relaxed-layer near-miss stop. Final unknown is a conclusion, not pass; failed or unsent required checks remain not_checked. Local auto-completion follows the same prefix rule. Stats expose selection policy, frontier rank, completion and pending-prefix IDs. Cache keys include the selection policy.
Generation retains model selection and order, exposing recommendation_order with model/retrieval orders, original ranks and reordered flag; the server logs the same record. No claim of guaranteed cost or latency reduction.

### Demo readiness (2026-10-25)
Startup now waits for one fixed local embedding and a bounded ES Vector query (5 results, num_candidates 100). No paid model calls. Logs and /health.retrieval_warmup report completion/failure, timings and failure type. Failure is nonfatal; set RECIPE_WARMUP=0 to disable. This shifts initialization into startup, without guaranteeing every later query is warm or promising a latency reduction.

Recipe Check uses a consolidated 431-word prompt in General / Ingredients & categories / Dish identity / Cuisine / Evidence sections. Full ingredient/name/tag values remain required; dish identity may quote one continuous instruction excerpt. Original semantic rules and per-recipe pending lists remain in force. Prompt version/cache fingerprints update automatically.

Checked sole-core ingredient notices now appear in Recipe Check and the generated summary, using actual checked strict candidates and dish-failure counts only, not library-wide claims. Confirmed recorded absence reads “No X in the recorded preparation ingredients.” Unknowns remain unknown. Symbolic fallback images use 112px desktop / 88px mobile banners; originals retain their photo layout. Matching details use a labeled “Why this recipe” checklist control. Assets 1.2.82.

### Distinct recommendations and presentation copy (2026-10-25)
Near-duplicate candidates require BOTH name similarity >=0.90 and preparation-ingredient Jaccard >=0.85; missing ingredient evidence never merges candidates. Names use repaired, normalized full/title-token-order similarity. The highest input rank wins. Config: config/recommendation_dedup.json. Ranked-prefix qualification now counts distinct passes; it still resolves pending candidates before that distinct frontier. Final groups and Check decisions remain intact; summary_deduplication records removed/kept IDs, scores and thresholds. No extra retrieval or invented quota fillers.

Source text is repaired only in response/display copies via HTML unescape and ftfy. Known damaged contractions are repaired conservatively; unrecoverable replacement characters remain visible. Stored ES/source evidence and historical experiments are not rewritten. ftfy is included in requirements.txt.

Semantic category checks are labeled Recipe Check. Exclusion violations read Contains X. not_checked remains the API state; UI says not needed (target reached) only for a confirmed complete prefix, otherwise pending/failure wording remains. Unsupported intents do not instruct users to run Retrieval. Assets 1.2.83.
