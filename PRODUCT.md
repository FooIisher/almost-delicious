# Recipe Search Lab

<!-- impeccable:product-schema 1 -->

## Platform
web

## Users
JL operates this research prototype for thesis evaluation and demonstrations to Mark Fenner. The user confirmed research demonstrations as the primary use on 2026-10-17.

## Product Purpose
Make recipe search understandable and observable: interpret English requests, review editable retrieval constraints, run lexical/vector retrieval, inspect fusion and preference ranking, then generate grounded recipe recommendations.

## Operating Context
Local Python service on port 8003; vanilla HTML, CSS and JavaScript. Prototype 1.1 remains a separate baseline. The user controls each stage; paid semantic checks occur only on Check candidates, and summaries only on Generate; handoff buttons only navigate. When local checks already meet the qualified-pool target, the backend completes Recipe Check without a model call and the retrieval handoff opens Generation directly.

## Capabilities and Constraints
- Four visible stages with completion states and server-reported execution times.
- Specific ingredient hard filters, soft preferences, category conditions and numeric constraints have distinct execution rules.
- BM25, Vector and Hybrid modes; existing retrieval parameters and ranking evidence remain editable/inspectable.
- Four generative model adapters and legacy Jev intent adapter; Jev does not have equivalent category extraction.
- Generated recommendations refer to displayed recipe IDs. Categories may be unknown; unknown is not proof of safety.
- Full ingredient data, recorded instructions, model input/output, diagnostics and comparison remain accessible.
- Backend retrieval and generation semantics are outside this visual redesign.

## Brand Commitments
The user approved the three generated screen proposals: warm-white research workspace, restrained green actions, compact header, explicit stages, concise summaries and progressively disclosed technical detail. Interface text remains English.

## Evidence on Hand
Existing implementation and tests. UI screenshots in .impeccable/review use synthetic test data and existing placeholder assets, not measured live model performance. Existing food images and fallback labels must not be represented as verified recipe photography.

## Product Principles
- Explain what will execute; distinguish recognized conditions from applied filters and ranking signals.
- Make the next action clear without hiding the research process.
- Preserve uncertainty and current-query isolation.
- Keep raw evidence and configuration accessible without dominating recipe content.

## Current layered constraints (v6)

BM25 required-only relaxation defaults to threshold 5, using the current stage count. Exclusions and all other hard filters remain; strict candidates are retained first. Meal/cuisine never automatically filter ES. Meal is explanation/ranking only; required cuisine is final-hard only without dish targets. All final hard conditions must pass before formal recommendation. Users can edit independent positive branch queries and Vector scope beta; technical execution is inspectable.


## Prototype 1.3 execution update
Strict retrieval defaults to 500 per branch. Fewer than 10 unique strict candidates may trigger up to three distinct relaxation directions, with a per-plan filter-range minimum of 3. Original final requirements remain binding. Recipe Check and Generation stay separate; close alternatives are grouped by actual deviations and never counted as formal recommendations.
