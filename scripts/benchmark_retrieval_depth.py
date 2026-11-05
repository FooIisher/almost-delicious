"""Measure fixed retrieval snapshots; never calls intent/check/generation models."""

import argparse
import json
import math
import statistics
import time
import urllib.request
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--snapshot",
        type=Path,
        required=True,
        help="JSON containing the actual editable search request",
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8003")
    parser.add_argument("--depths", type=int, nargs="+", default=[100, 500, 1000])
    parser.add_argument(
        "--strategies",
        nargs="+",
        choices=["single", "multi-separate", "multi-combined"],
        default=["single", "multi-separate", "multi-combined"],
    )
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.repeats < 2 or any(d < 1 or d > 2000 for d in args.depths):
        parser.error("Use at least two repeats and depths 1–2000")
    snapshot = json.loads(args.snapshot.read_text())
    runs = []
    # First request is labelled first_observed, not claimed to be a verified cold cache.
    # Interleave depths to avoid giving a single depth all warm-up benefits.
    for repeat in range(args.repeats + 1):
        depths = args.depths if repeat % 2 == 0 else list(reversed(args.depths))
        for depth in depths:
            for strategy in args.strategies:
                body = {
                    **snapshot,
                    "relaxation_strategy": "single" if strategy == "single" else "multi",
                    "relaxation_vector_strategy": "separate"
                    if strategy == "multi-separate"
                    else "combined",
                    "bm25_candidates": depth,
                    "vector_candidates": depth,
                    "vector_num_candidates": max(
                        max(args.depths), snapshot.get("vector_num_candidates") or 0
                    ),
                }
                started = time.perf_counter()
                request = urllib.request.Request(
                    args.base_url.rstrip("/") + "/recipes/search",
                    data=json.dumps(body).encode(),
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(request, timeout=180) as response:
                    result = json.load(response)
                relax = result.get("relaxation", {})
                runs.append(
                    dict(
                        strategy=strategy,
                        depth=depth,
                        repeat=repeat,
                        cache_state="first_observed" if repeat == 0 else "subsequent_uncontrolled",
                        client_ms=round((time.perf_counter() - started) * 1000, 2),
                        timings=result.get("timings", {}),
                        candidate_counts=result.get("candidate_counts"),
                        generation_candidate_count=len(result.get("generation_candidate_ids", [])),
                        relaxation_status=relax.get("status"),
                        selected_plans=relax.get("selected_plans")
                        or ([relax["selected_plan"]] if relax.get("selected_plan") else []),
                        relaxation_executions=relax.get("executions"),
                        source_plan_coverage=len(
                            {
                                p
                                for m in result.get("generation_candidate_levels", {}).values()
                                for p in m.get("source_plans", [])
                            }
                        ),
                    )
                )
    summaries = []
    for depth, strategy in [(d, s) for d in args.depths for s in args.strategies]:
        rows = [
            x for x in runs if x["depth"] == depth and x["strategy"] == strategy and x["repeat"] > 0
        ]
        measurements = {"client_ms": [x["client_ms"] for x in rows]}
        for key in {k for x in rows for k in x["timings"]}:
            measurements[key] = [
                x["timings"][key] for x in rows if isinstance(x["timings"].get(key), (int, float))
            ]
        summaries.append(
            dict(
                depth=depth,
                strategy=strategy,
                metrics={
                    k: dict(
                        median=statistics.median(v),
                        p95=sorted(v)[math.ceil(0.95 * len(v)) - 1],
                        samples=len(v),
                    )
                    for k, v in measurements.items()
                    if v
                },
            )
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            dict(
                snapshot=snapshot,
                runs=runs,
                summaries=summaries,
                note="Retrieval-only: source-plan coverage is not semantic deviation diversity; Recipe Check and model costs are not measured. No cache reset or claim of linear causality. Record ES size, hardware and concurrent load separately; p95 needs more samples for robust conclusions.",
            ),
            indent=2,
        )
        + "\n"
    )
    print(f"Saved {len(runs)} retrieval-only runs to {args.output}")


if __name__ == "__main__":
    main()
