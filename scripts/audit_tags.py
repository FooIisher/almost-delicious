from recipe_search.settings import get_settings

"""Read source Parquet and write reproducible tag inventory. No ES writes or model calls."""
import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow.parquet as pq

from recipe_search.ingest.ingest_recipes import parse_r_vector
from recipe_search.matching.tag_normalization import (
    VERSION,
    classify_tags,
    clean_tag,
    load_rules,
    normalize_tags,
)


def main():
    parser = argparse.ArgumentParser()
    Path(__file__).resolve().parents[1]
    parser.add_argument("--source", type=Path, default=get_settings().data_file("recipes.parquet"))
    parser.add_argument("--output", type=Path, default=get_settings().output_dir / "tag-audit")
    args = parser.parse_args()
    if args.source is None:
        parser.error("Supply --source or set DATA_DIR")
    counts = {
        k: Counter() for k in ("keywords", "recipecategory", "keywords_normalized", "category_tags")
    }
    examples = defaultdict(list)
    coverage = Counter()
    missing = Counter()
    symbols = Counter()
    rows = 0
    f = pq.ParquetFile(args.source)
    for batch in f.iter_batches(
        columns=["recipeid", "keywords", "recipecategory"], batch_size=10000
    ):
        for r in batch.to_pylist():
            rows += 1
            raw_category = r["recipecategory"]
            category = clean_tag(raw_category)
            tags = parse_r_vector(r["keywords"])
            missing["keywords"] += not bool(tags)
            missing["recipecategory"] += not bool(category)
            values = {
                "keywords": tags,
                "recipecategory": [str(raw_category)] if raw_category is not None else [],
                "keywords_normalized": normalize_tags(tags),
                "category_tags": normalize_tags([raw_category]),
            }
            for field, items in values.items():
                counts[field].update(set(items))
            for field in ("keywords", "recipecategory"):
                for tag in set(values[field]):
                    if len(examples[(field, tag)]) < 3:
                        examples[(field, tag)].append(str(r["recipeid"]))
                    for symbol in ("&", "|", "/", ";"):
                        if symbol in tag:
                            symbols[f"{field}:{symbol}"] += 1
            facets = classify_tags(tags, raw_category)
            for field in (
                "meal_types",
                "dish_types",
                "cuisines",
                "meal_type_candidates",
                "dish_type_candidates",
            ):
                coverage.update(f"{field}:{v}" for v in facets[field])
    inventory = {
        field: [
            {"tag": tag, "recipe_count": n, "example_recipe_ids": examples.get((field, tag), [])}
            for tag, n in c.most_common()
        ]
        for field, c in counts.items()
    }
    summary = dict(
        version=VERSION,
        source=str(args.source.resolve()),
        source_bytes=args.source.stat().st_size,
        recipe_count=rows,
        missing_after_cleaning=dict(missing),
        unique_labels={k: len(v) for k, v in counts.items()},
        symbol_occurrences=dict(symbols),
        mapped_recipe_counts=dict(coverage),
        note="Source Parquet audit, not an audit of the running ES index. Counts are unique recipes per label, not recall estimates.",
    )
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "inventory.json").write_text(
        json.dumps(dict(summary=summary, inventory=inventory), indent=2) + "\n"
    )
    lines = [
        "# Tag inventory and mapping v1",
        "",
        f"Source recipes: {rows:,}. Source: `{args.source.resolve()}`.",
        "This audits the local source dataset. The running Elasticsearch index has not been modified.",
        "",
        "## Data quality",
        "",
        f"- Missing categories after placeholder cleaning: {missing['recipecategory']:,}.",
        f"- Missing keyword lists: {missing['keywords']:,}.",
        "- No exact dinner label exists. Weeknight and One Dish Meal are candidate signals only.",
        "- Lunch/Snacks and Cookie & Brownie are ambiguous groups. Splitting text does not prove membership in both classes.",
        "- Salad Dressings is not Salad. Quick Breads is not a quick-time guarantee.",
        "- Healthy and other nutrition source labels do not establish compliance with the new numerical thresholds.",
        "- Bath/Beauty, Household Cleaner and Homeopathy/Remedies need a separate non-food review; no records were removed.",
        "",
        "## Mapping draft",
        "",
        "| Field | Canonical value | Source labels | Matching recipes | Policy |",
        "| --- | --- | --- | ---: | --- |",
    ]
    for rule in load_rules():
        lines.append(
            "| "
            + " | ".join(
                [
                    rule["field"],
                    rule["value"],
                    ", ".join(rule["source_tags"]),
                    str(coverage[f"{rule['field']}:{rule['value']}"]),
                    rule["filter_policy"],
                ]
            )
            + " |"
        )
    lines += [
        "",
        "`tagged_records_only` means restricting to explicitly tagged documents, not all recipes that semantically qualify. Hard semantic filtering remains unvalidated.",
        "",
        "## Compound label normalization",
        "",
        "| Source label | Normalized tags |",
        "| --- | --- |",
    ]
    for tag in sorted(set(counts["keywords"]) | set(counts["recipecategory"])):
        if any(s in tag for s in ("&", "|", "/")):
            lines.append(
                "| " + tag.replace("|", "\\|") + " | " + ", ".join(normalize_tags([tag])) + " |"
            )
    lines += [
        "",
        "## Rollout and acceptance",
        "",
        "1. Review the mapping draft and inspect positive and negative recipe samples by ID. Review sparse tags individually.",
        "2. Estimate precision on tagged records and missed matches among untagged records. Frequency is not semantic recall.",
        "3. Backfill additive fields into a separate ES index or reviewed partial-update job. Keep raw fields and vectors unchanged.",
        "4. Use exact/subtype mappings only for explicitly requested tagged scope until coverage is validated. Candidate mappings remain boost-only.",
        "5. Compare fixed search cases before enabling query routing. Check dinner coverage, soup false positives, missing tags and preference-only queries.",
        "6. Preserve explicit raw source tags and mapping version on every record. Never use tag-derived ingredient words as allergy evidence.",
        "",
    ]
    (args.output / "README.md").write_text("\n".join(lines))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
