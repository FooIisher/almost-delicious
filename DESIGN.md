---
name: Recipe Search Lab
description: A restrained research workspace for observable recipe search.
colors:
  paper: "#fafbf9"
  panel: "#fff"
  ink: "#1f2928"
  muted: "#596760"
  line: "#dce3df"
  lime: "#dcebe2"
  accent: "#246347"
  warning: "#825013"
  warning-bg: "#fff4df"
typography:
  body:
    fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif"
    fontSize: "15px"
    lineHeight: 1.55
  title:
    fontSize: "26px"
    fontWeight: 700
    lineHeight: 1.3
    letterSpacing: "-.025em"
  label:
    fontSize: "13px"
rounded:
  control: "7px"
  panel: "8px"
  composer: "12px"
spacing:
  group: "24px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.panel}"
    rounded: "{rounded.control}"
    padding: "10px 18px"
  detail-panel:
    backgroundColor: "{colors.panel}"
    rounded: "{rounded.panel}"
---

# Design System: Recipe Search Lab

## Overview

A warm-white research workspace with restrained forest-green actions. The approved direction is implemented as a compact header, explicit stages, concise summaries and progressively disclosed technical detail. No additional named creative metaphor was confirmed.

**Key Characteristics:**
- Clear stage progression and backend timing.
- Flat recipe rows and readable answer content.
- Inspectable evidence without overwhelming the primary task.

## Colors

Forest green marks primary actions, completion and focus. Paper, panel, ink, muted and line supply the neutral reading structure. Pale green distinguishes active steps and handoffs. Warning amber distinguishes category uncertainty; exclusion chips use muted red. Color accompanies explicit labels rather than carrying execution meaning alone.

**The Execution Meaning Rule.** Required ingredients, excluded ingredients, preferences and category conditions retain distinct labels; decorative color cannot merge their meanings.

## Typography

The effective body stack comes from `web/styles.css`: Inter with UI/system sans-serif fallbacks. The Arial stack declared on the root in `research.css` does not override the body's own font-family. Font availability was not verified in a live browser.

Stage titles use the title role; the compact header is smaller (22px, line-height 1.25). Retrieval titles are 17px and generated recipe titles 20px. Supporting metadata is generally 12–13px. Generated introductory copy is 16px with 1.7 line-height and a 78ch maximum. Numeric timings use tabular figures. Preserve readable paragraph and list structure rather than turning explanations into badges.

## Layout

A centered shell caps at 1280px with desktop padding of 24px 36px 64px. Stage navigation spans the workspace. Intent summaries form two columns; retrieval uses rows with a 120px image column and 20px gap. Generated recipes use a 180px visual column and 24px gap. Technical controls and evidence remain available through native disclosure panels.

At 900px, shell side padding becomes 24px and heading actions wrap. At 650px, side padding becomes 16px, all three stage controls remain in a horizontal row with vertically stacked contents, retrieval images become 86px wide, and generated visuals become 110px wide. At 420px, intent summaries, generated recipes and controls use one column. Earlier styles also contain a 720px breakpoint; inspect the full cascade when extending layouts. Comparison tables and long diagnostics must remain usable in narrow viewports.

## Elevation & Depth

The main workspace is flat. The composer, stage cards, search panel and result rows remove decorative shadows. Borders, tinted active surfaces and an inset accent underline communicate grouping and current state. Filled retrieval fields use an inset left accent. Recipe detail overlays inherit the existing modal treatment; do not infer a new global shadow scale from them.

## Shapes

Controls have modest curves, disclosures and images gently rounded corners, and the composer slightly broader corners. Retrieval rows are square, divided by fine horizontal lines. Chips have small rounded rectangles. Preserve this distinction between rows, interactive controls and contained configuration.

## Components

### Buttons and fields

Primary actions use forest green, white text and compact padding. Stage actions and model selectors have a 44px minimum height. Buttons darken on hover through brightness filtering; the handoff action also has a deeper-green hover background. Disabled buttons communicate unavailable actions through native disabled state, opacity and a prohibited cursor. Populated retrieval fields receive a pale-green fill and left accent.

### Workflow navigation

Three numbered buttons represent understanding, retrieval and generation. The current stage has a pale-green surface and accent underline; completion fills the number circle. All three controls remain visible after request submission, with unavailable future stages disabled. The initial navigation is hidden until submission. Status text and timing labels distinguish not run, processing, complete, review required and failed states. Timing tooltips explain backend boundaries and exclude network/browser round trips.

### Summaries, chips and disclosures

The default intent view identifies the search target, hard inclusion/exclusion, soft ranking signals, numeric conditions and category conditions. Full interpretation collapses after a ready response. Retrieval configuration is initially open and collapses while retrieval runs. Recipe/ranking evidence, category checks and model diagnostics use native details/summary elements. The retrieval summary reflects the actual submitted fields.

### Recipe rows and generated answers

Retrieval rows combine a compact image, title button, metadata and match explanation. Full recipe and ranking details remain expandable. Generation presents an introductory answer, grounded recipe titles, compact visuals, ingredient summaries, ordered preparation steps and a comparison table. Candidate checks and raw diagnostics follow the answer. Existing fallback imagery is labeled illustrative; no new raster assets were created for this implementation.

### Interaction and accessibility

Stage headings accept focus on handoff; navigation uses aria-current and stages expose aria-busy. Generation status is a polite live region. Buttons, links and summaries have a 2px forest-green focus outline with 4px offset. Native disclosures and labeled controls preserve keyboard operation. The recipe detail dialog has an accessible name and close control. These are implementation facts, not a completed accessibility audit; verify focus containment, text/input focus contrast and narrow-table behavior in a real browser. Reduced-motion preferences disable animations, transitions and smooth scrolling.

## Do's and Don'ts

### Do:
- **Do** keep technical evidence accessible alongside concise readable summaries.
- **Do** retain explicit labels for execution semantics and unknown category results.
- **Do** preserve disabled future stages and visible backend timing after submission.
- **Do** label illustrative imagery and keep recommendation IDs grounded in current retrieval.

### Don't:
- **Don't** imply category recognition is a hard retrieval filter or proof of safety.
- **Don't** replace readable recipe content with a dashboard of decorative cards.
- **Don't** present synthetic review fixtures as measured live model performance.

### Retrieval recipe information refinement
Descriptions, all recorded Category labels and all Keywords are visible by default in separate labeled wrapping rows. Ingredient lists and scoring evidence remain in the disclosure. Result rank is an accessible forest-green badge at the image top-left, outside the metadata line. No source tags are silently truncated.

### Generated answer stream refinement
Generation content is a centered 860px reading surface: summary, numbered recipe title, clickable image, metadata, reason, ingredient bullets, then short numbered instructions. Photos are contained within a 640px maximum; sources below 400px natural width use a 320px maximum to avoid unnecessary enlargement. Comparison tables stay in the answer. Candidate checks, provider input, selection counts, warnings/metadata and raw diagnostics are grouped in one closed-by-default Research details disclosure below it. Per-recipe unresolved hard constraints remain visible in the answer.

### Icon action buttons
Primary workflow triggers use a consistent local 24px outline SVG vocabulary from web/action-icons.js: submit arrow, analysis/check cycle, search, forward handoff, generation sparkle, and download. The helper preserves an English aria-label, native title tooltip, 44px target, disabled semantics and aria-busy; running calls show a spinner, static under reduced motion. Navigation labels and recipe titles remain readable content. No external icon dependency or runtime network request is used.

### Retrieval flow subgraph
After retrieval starts, a live diagram above the recipe list shows BM25/Vector server timing, branch candidate counts, RRF timing and exact pre-rerank fusion count (`candidate_counts.rrf`), separately from the number displayed. Timings come from backend progress/final payloads, not browser clocks. Inactive single-mode branches and RRF are labeled not used; timeout/failure and degraded retrieval remain explicit. New requests invalidate/hide the prior graph. Mobile arranges merge/output below the two branches.

### Retrieval flow motion
Responsive SVG paths are measured from actual node bounds. Arrowheads persist when static; running edges display directed moving dashes and executing nodes gently change background. Completion/failure stops motion. Skipped branches are not linked; single-mode candidates connect directly to output. Narrow-screen merge paths route around nodes through the diagram gutter. ResizeObserver updates connectors without a continuous JavaScript animation loop. Reduced motion removes particles and node animations, keeping arrows and text states.

### Conditional BM25 low-recall fallback
BM25 shows the requested Must include/exclude values. With ingredient constraints present, a successful first recall below the configurable threshold (default 5, 0 disables) triggers exactly one BM25 retry with only those two lists cleared. Other filters stay intact and Vector retains the original filters. Retry candidates replace the first BM25 list in fusion. A failed retry retains the successful constrained recall when the branch deadline permits. The original-call and retry counts/timings are separate in the expanded graph, while the ordinary BM25 branch timing covers the whole branch. Amber fallback node and visible warnings explain relaxed constraints; fallback trace/actual branch filters are included in generation input. Unknown/relaxed is never represented as satisfied.

### Executed query inspector
BM25, Vector and retry nodes expose local code-icon buttons. A single panel below the graph follows the selected node, with Overview and Raw DSL tabs, branch switching and an initial/retry selector. Request bodies are captured immediately before ES dispatch. Full-copy includes the unabridged query vector; the visible JSON abbreviates it with a separately expandable vector. State clears on new retrieval. Missing snapshots explicitly report unavailable rather than reconstructing a request from current form values.

### Guided workflow actions
Primary workflow actions now combine the existing SVG vocabulary with concise visible labels. Submit opens analysis as Start analysis; run buttons state Analyze intent, Retrieve recipes and Generate recommendations. Completed stages demote their rerun action to a white outlined button (Analyze again / Retrieve again / Generate again), while the stage handoff retains the forest-green emphasis and right arrow. Generation handoff identifies the currently selected provider/model and continues to execute generation on click. Busy actions show a spinner and operation label. Handoffs focus and scroll to the destination heading; stages enter with a restrained 180ms transition disabled under reduced motion. Download remains icon-only. This supersedes the earlier icon-only rule for workflow triggers.

### Primary information first
After retrieval starts, configuration and the executed-condition overview close automatically. Retrieval flow precedes the closed Executed queries & conditions and Detailed retrieval timings disclosures, followed by recipe results. Each new run resets these disclosures to closed. Generation begins with the answer; aggregate and phase token/cache/cost statistics live in a separate closed Token usage & estimated cost disclosure at the very bottom, after Research details. Pending hard-constraint warnings remain visible.

### Required logic and final eligibility (v5)
The retrieval editor exposes a parenthesized Required ingredient logic field, with AND/OR help and validation; specific includes, required/excluded categories and hard dish targets remain editable. Intent and executed-condition summaries show the same expression. OR alternatives are not all concatenated into the BM25 base text. The graph keeps short primary node labels; the per-stage filter/time/returned/new/used table is closed below it, and the DSL attempt selector labels Original groups / Any required / No required. Formal recommendations, Needs confirmation, Filtered recipes and Not checked remain distinct; no unchecked candidate is visually promoted as qualified.

## Layered constraints v6

Operate-mode refinement preserves the existing research workspace. Three editable query fields distinguish BM25 content, Vector meaning and Vector scope. The meal/cuisine execution section labels meal explanation-only and dynamically states whether cuisine is a final requirement. No automatic label-scope controls are exposed. Secondary settings/DSL/usage stay expandable; exact recorded context matches appear next to generated recipe explanations. Single-mode ranking controls remain available. Manual Labels keep their explicit hard-filter label.

## Retrieval branch workbench

BM25 / Vector / Hybrid use accessible, keyboard-switchable tabs in Operate mode. BM25 and Vector show editable branch-specific parameters above their raw recall lists. Hybrid places those same live parameter controls side by side, followed by fusion settings and fused/reranked results. Shared constraints and recommendation preferences remain a single collapsed editor. Branch flow/DSL is secondary disclosure; Hybrid retains the primary flow diagram. Tabs show not-run, running, ready, stale or failed state. Switching is read-only; refresh invokes the corresponding branch or both for Hybrid. Mobile stacks the parameter cards, keeps actions labeled and preserves tab focus order.

### Saved retrieval comparison
A quiet Compare runs panel follows the retrieval workbench. Save as baseline freezes the visible run; the next successful run is shown alongside it. Parameter changes remain in a native disclosure. Rank movements use text/arrows, never color alone. Stale current results are withheld; the baseline persists until explicitly replaced, cleared or the page reloads. Mobile stacks the two labeled columns.


## Recipe Check and Generation split
Four visible stages in Operate mode: Understand request / Retrieve recipes / Check recipes / Generate recommendations. Recipe Check has a Check model selector and an explicit Check candidates action; Generation keeps its independent selector and Generate action. Handoffs navigate only and never dispatch paid work. Retrieval automatically shows local-only counts. Complete checks open the next action, while fail/unknown/not_checked remain separate from qualified. Per-stage technical usage/diagnostics are folded; mobile lays four workflow steps in a two-column grid. A summary-model or semantic-recheck change clears only the generated answer. Upstream or check-model edits invalidate the pool and answer. Browser reload clears client workflow state; server pool IDs remain valid only within their 30-minute process cache lifetime.


### Recipe Check outcome disclosures
Four independently expandable native details group qualified, not eligible, unconfirmed and not checked recipes. Summaries retain counts and remain keyboard accessible even at zero. Within each group, recipe detail links and IDs precede concrete condition verdicts, reasons, evidence and provenance. Unchecked semantic work is labeled pending with its stop explanation; OR alternatives are not mislabeled as failures. New results reset groups to collapsed. Technical model JSON remains in the separate research disclosure.


### Ingredient evidence provenance
Recipe Check and generated recommendations distinguish ingredient-list evidence from instruction-extracted mentions. Use explicit text (mentioned in instructions · extracted), separate from Local check / Model check provenance. Display matching extracted terms near recommendation reasons; keep the original ingredient list unchanged and add a separate Mentioned in instructions section. Preserve provenance in filtered, pending and ranking evidence. No invented instruction quotation or quantities are shown.

## Generation reading surface and evidence margin (2026-10-23)

Mode: Operate / Read. Generation now separates the narrative reading path from inspection. A single outlined white surface holds the opening summary, recipe titles, source photographs, introductions, short recommendation reasons, original instructions and closing comparison. Source ingredient names remain accessible in matching details and full Recipe Detail.

On desktop, a 260px evidence margin sits 28px to the right of the reading surface. The qualification/run overview anchors at the upper right without pushing down the opening recipe. Per-recipe bubbles and hard-condition disclosures align with each recommendation reason using CSS subgrid. There is no additional model request when opening explanations.

At 900px and below, the overview follows the opening summary; recipe evidence flows between the reason and instructions. Source food content stays unchanged. Research details and token/cost disclosures sit outside the reading surface in a separate tinted panel below it, separated by a 24px gap, and start collapsed. Unconfirmed, filtered and unchecked candidate inspection stays under Research details. Instruction-extracted terms appear only as matched provenance in the matching disclosure, never as a second standalone ingredient list.

Generation layout rules are isolated in `web/generation.css`; established colors, source-photo fallbacks, model controls and the four-stage workflow are retained.

## Recipe Check density (2026-10-23)

Outcome groups open to compact recipe cards with name/detail link, ID and a two-line decision preview. Each card has a closed native condition-details disclosure containing reasons, evidence and local/model provenance. Cards use 8px gaps and 12px vertical padding; condition rows use separators rather than nested tinted boxes. Mobile headers stack without horizontal overflow.

Generation source Ingredients are visible again inside the narrative card, before Instructions. Six or more names use two columns on desktop and one on small screens. Original names and missing-data messages remain unchanged; instruction-extracted matching provenance stays in the evidence margin.

Ingredient density: omit the quantities disclaimer in generated content. Six or more source ingredient names use a compact three-column list; narrow content containers use two columns, small phones one. Use 13px text, 1.5 line height, 2px row gaps and 16px spacing before Instructions.

## Unified recall relaxation (2026-10-24)

Operate mode: a shared Strict candidate check and Relaxation decision connect both original branches to supplemental branches and a strict-first merge. Inspect decision opens an inline panel with protected ingredients, complete plan ranges/counts, cost and selection reasons; selected rows use a restrained green fill. Filter-range statistics and actual recall counts are explicitly separated. A two-column narrow-screen graph and local table scrolling prevent document overflow. Native disclosures keep raw snapshots folded; Copy decision JSON preserves inspection. Near misses are a separate Check group and a Close alternatives section, with deviations adjacent to source recipe content, never counted as formal recommendations.


## Core status and relaxed-branch inspection (2026-10-24)

Ingredient interpretation and qualification details show Core: yes/no as text, with original evidence preserved. A sole required specific ingredient may be relaxed for recall only. Its original requirement remains in qualification, and alternatives missing it are clearly separated as near misses. Grouped core ingredients keep their protection.

The flow uses vertically stacked stage cards. Initial retrieval and Additional retrieval each contain BM25 and Vector side by side on desktop, explicitly labeled Parallel or Sequential; mobile stacks branches inside the same stage card. Preparation, decision, fusion and output remain separate compact cards, connected only downward. Candidate counts belong to their branch. Status markers show rotating rings, completion checks or errors; inspection controls retain 44px targets.

Stage cards and branch nodes are mounted only when real backend events reach them. Start mounts only Preparing retrieval. Early filter statistics are buffered. A relaxation decision is mounted only after insufficient strict candidates are known; strict-sufficient runs never mount it. Selecting a plan does not mount additional retrieval: actual branch-start events do. Merge, RRF and output follow their own events. No future placeholders or artificial replay delays appear. Final-only snapshots render their completed state immediately. Reset detaches previous cards. Reduced motion removes reveal/rotation while preserving text and aria-busy; continuous animation pauses offscreen or in hidden documents.

Technical inspection remains folded until requested; pending controls stay disabled until an actual execution snapshot exists. Backend progress now includes strict and relaxed branch counts (plus newly added counts), an explicit merge event and fused count. The existing stream is reused; no polling endpoint or extra retrieval/model call is introduced. Timings remain server values. The optional Impeccable detector engine remains unavailable; source, rendered geometry, lifecycle and desktop/mobile visual checks cover this surface.

## Hard-condition fixes (2026-10-24)

Recall relaxation never waives formal ingredient requirements, including a sole core ingredient. Close alternatives remain a separate group and can proceed to Generation without formal pass candidates. Strictly recalled recipes that match the core ingredient but not the dish are available in their own disclosure; the wording describes the inspected candidates, never a whole-library absence. Relaxation summaries distinguish strict and additional unique candidates. Time relaxation labels round upward for compact reading; executed DSL retains exact values. Zero total time is unknown, not a valid fast recipe.

## Horizontal retrieval dependencies (2026-10-24)

The retrieval diagram reads left to right on desktop: two vertically stacked parallel branches in Initial retrieval converge on a separate Strict candidate check. Insufficient strict recall reveals Relaxation decision; only real supplemental start events reveal Additional retrieval, with its own parallel branches. A decision without a usable plan connects directly to strict-first merge and RRF. Sufficient strict recall bypasses the decision entirely. The diagram uses compact cards, orthogonal forward connectors and existing server-driven progressive state. Narrow screens switch to vertical stage cards; intermediate widths scroll inside the diagram rather than overflow the page. The top-left Retrieval flow heading is a keyboard-accessible collapse button; collapse hides presentation only, not execution or results.

## Check handoff and alternative summaries (2026-10-24)

After a successful Recipe Check the qualification counts and Continue to generation handoff appear immediately below the Check again header action, ahead of outcome details. Generated alternatives remain visibly distinguished by qualification/deviation notes, without a separate Close alternatives heading inside the reading surface. Near-only summaries explicitly name the relaxed condition, using recorded absence rather than claims about the whole library. The final Recipe summary table includes formal and alternative selections, with a Requirement differences column. Mobile scroll stays inside the comparison table.

## Per-branch strict baselines (2026-10-24)

When supplemental recall succeeds, each branch retains an immutable snapshot of its original strict results, candidate count and server duration. BM25 and Vector tabs automatically compare that baseline with their deduplicated strict-first augmented list. Before/after labels, recipe IDs, total versus displayed counts, new items and rank changes remain explicit. Relaxed actions are displayed separately from original qualification conditions. No additional query is issued; failed strict or supplemental branches do not fabricate a baseline. Existing manually saved comparison remains available for ordinary runs. Snapshots are page-local and are replaced by a new completed retrieval.

## Separate parallel branch cards (2026-10-24)

Initial and supplemental retrieval use unboxed lane groups, each with separate vertically stacked BM25/Vector cards. Each branch owns its duration, count, loading state and DSL control; existing forward fan-in/fan-out edges attach to individual card boundaries. The small Parallel label identifies the relationship without enclosing both cards in another panel. Relaxation inspection uses an icon-only sliders button with an accessible name, tooltip, aria-expanded, keyboard focus and 44px hit target.

## Detail ingredient provenance (2026-10-24)

Recipe Detail places a distinct, lightly tinted From instructions section immediately below the original Ingredients list. It shows persisted extract_ingredients only, deduplicated by Unicode/case/spacing/punctuation normalization against the original list and itself. No semantic ingredient inference or new extraction call occurs. Original Ingredients remain unchanged. Empty extra data retains a compact No additional ingredient names recorded message.

## Related ingredient candidates: decision reasons

The Other recipes with the required ingredient disclosure contains compact per-recipe cards. Each lists decisive unmet or unresolved requirements with condition type/name, Not met / Unconfirmed / Not checked, the recorded reason and evidence where available. Non-decisive OR alternatives are omitted. Both Recipe Check and Generation share this rendering; source details remain accessible through recipe titles.

## Borderline dish identity alternatives

Completed semantic dish-name uncertainty may be disclosed as a near-miss difference only for relaxed-source candidates whose other requirements pass under selected recall deviations. Original checks remain unknown; this never makes a formal recommendation. Both Recipe Check and generated alternatives sort fewer deviations first, retaining original ranking for ties. Dish identity uncertainty appears alongside missing-ingredient/numeric differences and in the final comparison table.

## Default summary-only generation

Recipe Check is the default authority for qualification. Generation consumes its cached groups and verified evidence for selection/explanation without repeating semantic checks. Recheck semantic decisions is off in frontend and API defaults; an explicitly labeled experimental switch remains inside collapsed Research settings. Structural coverage, source grounding, ID membership and pass/near-miss group enforcement remain active. Research rechecks operate on a copy of the checked pool and do not mutate the cached original.

## Recipe Check result surface (2026-10-25)

A single bordered Candidate results card contains five independent collapsed outcome groups, each with a count badge, label and disclosure chevron. Expanded groups retain compact recipe cards and nested evidence. Debug content follows in a separate muted footer: Token usage & estimated cost and Research details start collapsed; run statistics and ordinary warnings live inside research details. Operational batch failures and retry actions stay visible above the result card. The primary next-stage handoff remains immediately below the Check again header.


### Missing-image presentation (2026-10-25)
Mode: Operate / Read. Dish-form fallback marks replace photographic substitutes. Use the same green, 2.2-unit stroke on a pale surface, with a readable native category caption. These are category icons, never claimed to depict a recipe. Missing-image retrieval rows use 80px marks (64px mobile). Generation places an 88px mark next to the title and reason; mobile keeps the title beside the 64px mark, then lets prose use the full width. Original images keep the existing layout; runtime load failures adopt the icon layout. Detail headings use the same compact distinction. Name > labels > ingredients; form matching is word-based and independent of protein.

### Aligned photo slots (2026-10-25)
Supersedes the compact missing-image layout: original and fallback images share the same slot and text alignment. Retrieval keeps 120×112px desktop and 86×92px mobile slots. Generation uses one common 16:9 frame, up to 520px, for both sources, including small original images. Category names sit inside the fallback image at the bottom; source photos remain free of category captions. Detail uses the original photo heading dimensions for either source. Classification and icons remain unchanged.

### Quiet fallback banners and matching affordance (2026-10-25)
Supersedes the full-height fallback slot in Generation: preserve the common width and title alignment, but use a 112px symbolic banner (88px mobile), with category text inside beside the icon. Original photographs keep their established frame. The explanation control now pairs a checklist icon with “Why this recipe” text and keeps its keyboard/expanded-state behavior. Retrieval image dimensions remain aligned with originals.
