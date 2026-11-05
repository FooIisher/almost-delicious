# JEV recipe intent test

Standalone Python 3.10+ experiment using the standard library. It classifies user intent and extracts candidate-based fields; it does not search recipes or answer the user's cooking question.

## Run

From the workspace root:

```bash
python3 project/model/jev_test.py
python3 project/model/jev_test.py --query 'I have beef and potatoes. Suggest a quick dinner.'
python3 project/model/jev_test.py --dry-run --query 'Taco Chicken'
```

The existing default key is used unless `AI_GATEWAY_API_KEY` is set. Interactive queries are independent. Enter `exit` to quit. `--dry-run` prints the request without model calls or simulated answers.

## Intent design

| Intent | Meaning |
| --- | --- |
| `recipe_search` | Find or recommend recipes; subtype `name_search` or `constraint_search` |
| `meal_planning` | Assemble a coordinated meal plan |
| `recipe_comparison` | Compare two or more recipes |
| `recipe_how_to` | Preparation steps, cooking technique, temperature |
| `recipe_question_answering` | Recipe ingredients, nutrition, servings, substitutions or missing ingredients |
| `unsupported_request` | Understandable request outside the recipe assistant's scope |
| `unknown` | Insufficient information to identify the user's goal |

A dish name or an ingredient alone defaults to search. Suggesting one dinner is search; planning two dinners is meal planning. The output separately reports `status`: `ready`, `needs_clarification`, or `unsupported`.

## Output

The design's canonical `constraints` object includes:

- `ingredients_available`: explicitly possessed ingredients.
- `ingredients_required`: explicitly required recipe ingredients.
- `ingredients_excluded`: forbidden ingredients or stated allergies.
- `dietary_restrictions`, `meal_type`, `number_of_recipes`, `planning_days`.
- `max_calories`, `min_protein_g`, `max_cooking_time_minutes`, `soft_preferences`.

The existing `fields.available_ingredients`, `fields.include_ingredients`, and `fields.exclude_ingredients` remain as compatibility output. Availability is independent from use requirements: the same ingredient may be available and required, or available and excluded. Possession alone does not require inclusion. A missing stock item is not automatically forbidden.

Other output includes `confidence`, `search_type`, `recipe_names`, `recipe_references`, `reference_type`, `unresolved_references`, `comparison_dimensions`, `question_type`, `needs_clarification`, `missing_fields`, `clarification_reasons`, `clarification_question`, `unsupported_reason`, raw `answers`, usage, and latency.

`quick` becomes a soft preference and, for search/planning without an explicit bound, a default 30-minute limit. `normalization` labels the source as `system_default`; change the default with `--quick-minutes`. Explicit limits take precedence. The time field uses total recipe time to match the current search API, despite the design's `max_cooking_time_minutes` name. Strict bounds remain separately represented in `strict_upper_bounds`; no downstream search is executed.

## Recipe references and session context

```bash
python3 project/model/jev_test.py \
  --context project/model/context.example.json \
  --query 'Which of those two beef soups has more protein?'
```

Context contains an ordered `recipes` list of `{ "id": "...", "name": "..." }` and an optional `selected_recipe_id` that must exist in the list. Use real search result IDs in integration; the supplied file is an example only. Selected context can resolve “this recipe”. Without enough context or named dishes, comparison/how-to/QA requests are routed to clarification. IDs are only selected from the supplied list, never generated. Model-based reference resolution still needs empirical evaluation.

## Clarification rules

In addition to model probability, the script checks missing targets, missing planning counts/day ranges, unresolved references, hard-constraint conflicts and uncertain fields. A comparison needs at least two targets. “Healthier” without concrete criteria requests clarification about calories, protein, etc. Unsupported requests do not trigger clarification. `confidence` is the model's selected-intent probability, not measured accuracy.

## Candidate extraction limits

JEV returns typed decisions, not arbitrary text. Local English dictionaries/regular expressions propose ingredients, numbers and recipe names; JEV validates their meaning. Supplied context provides reference candidates. Add missing candidates using repeated `--ingredient` or `--recipe-name` options:

```bash
python3 project/model/jev_test.py --ingredient broccoli --query 'What can I make with broccoli?'
python3 project/model/jev_test.py --recipe-name 'Chicken Fajitas' --query 'Can I omit cheese from Chicken Fajitas?'
```

Recipe-name extraction supports quoted names, bare names and several common English templates; arbitrary phrasing may need `--recipe-name`. Counts support digits and English one through seven; complex schedules and all nutritional units are not covered. The model cannot classify an ingredient absent from its candidate list. Empty fields are not proof that a constraint is absent. No implicit allergen/diet expansion, general translation, or open-ended entity generation is performed.

Default confidence threshold: `--threshold 0.8`. Default request timeout: `--timeout 30`. Additional questions increase request size and potentially latency. Live calls send the query and supplied context to AI Gateway and use the account's current pricing.

## Verification

```bash
python3 -m unittest discover -s project/model -p 'test_*.py' -v
```

Offline tests cover seven routes, ingredient roles, normalization, context validation, missing references, comparison criteria, planning counts, low confidence and conflicts. They use synthetic responses and do not establish live model accuracy.

API: [Vercel Evaluation](https://vercel.com/docs/ai-gateway/modalities/evaluation), `POST https://ai-gateway.vercel.sh/v1/evaluate`, model `typesafe-ai/jev`.
