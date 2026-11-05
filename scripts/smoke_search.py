"""Read-only live smoke checks against a running Prototype 1.1 API."""

import argparse
import json
from pathlib import Path
import time
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8001")
    parser.add_argument("--output", default="verification/live-smoke.json")
    args = parser.parse_args()
    records = []
    queries = [
        {"query": "chicken", "mode": "bm25"},
        {"query": "chicken", "mode": "hybrid", "execution": "parallel", "branch_timeout_seconds": 120},
        {"query": "chicken", "mode": "hybrid", "execution": "serial"},
        {"query": "chicken", "mode": "hybrid", "execution": "parallel"},
        {"query": "chicken", "mode": "hybrid", "include_ingredients": ["chicken"],
         "exclude_ingredients": ["peanut"], "max_total_time_minutes": 30, "max_calories": 700},
        {"query": "chicken", "mode": "vector"},
    ]
    for body in queries:
        started = time.perf_counter()
        request = urllib.request.Request(args.url + "/recipes/search", data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=150) as response:
                result = json.load(response)
            rows = result["results"]
            assert len({row["recipe_id"] for row in rows}) == len(rows)
            if body["mode"] == "hybrid":
                for row in rows:
                    expected = sum(result["rrf"][f"{branch}_boost"] / (result["rrf"]["k"] + row[f"{branch}_rank"])
                                   for branch in ("bm25", "vector") if row[f"{branch}_rank"] is not None)
                    assert abs(row["rrf_score"] - expected) < 1e-12
                assert [row["rrf_score"] for row in rows] == sorted((row["rrf_score"] for row in rows), reverse=True)
            if body.get("max_total_time_minutes"):
                for row in rows:
                    assert row["total_time_minutes"] <= 30
                    assert row["calories"] <= 700
                    ingredients = " ".join(row["ingredients"]).lower()
                    assert "chicken" in ingredients and "peanut" not in ingredients
            records.append({"request": body, "status": "ok", "response": result})
            print(json.dumps({"mode": body["mode"], "execution": body.get("execution", "parallel"),
                              "effective_mode": result["effective_mode"], "result_count": len(rows),
                              "timings": result["timings"], "warnings": result["warnings"]}), flush=True)
        except Exception as exc:
            records.append({"request": body, "status": "failed", "error": str(exc)})
            print(json.dumps({"mode": body["mode"], "status": "failed", "error": str(exc)}), flush=True)
        records[-1]["client_elapsed_ms"] = round((time.perf_counter() - started) * 1000, 2)
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(records, ensure_ascii=False, indent=2))
    if any(record["status"] != "ok" or record.get("response", {}).get("warnings") for record in records):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
