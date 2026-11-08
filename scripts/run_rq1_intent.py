"""RQ1 intent-parsing benchmark: 4 models x N runs over a cases JSON file.

Paid API calls. Never logs or stores API keys. Writes one JSON per call and a
sheet-ready CSV (same column order as the RQ1-50 Google Sheet tab).

Default mode calls parse_gpt6() in-process, so neither the web server nor
Elasticsearch needs to be running; only OPENAI_API_KEY / DEEPSEEK_API_KEY.

From the repository root (results under var/outputs, which git ignores):
  uv run python scripts/run_rq1_intent.py --cases-file CASES.json   # -> var/outputs/rq1/run-<timestamp>
  uv run python scripts/run_rq1_intent.py --cases-file CASES.json \
      --models gpt41-mini --cases D01 D02 --runs 1   # smoke test

Re-running with the same --output resumes: finished calls are skipped.
"""

import argparse
import csv
import getpass
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from recipe_search.settings import get_settings

CASES = None  # Supply an explicit --cases-file; historical results are not bundled.
MODELS = ["gpt41-mini", "gpt41-nano", "gpt6", "deepseek-flash"]
SHEET_COLUMNS = [
    "Case ID",
    "Split",
    "Test Purpose",
    "Primary Fields",
    "Query",
    "Row Type",
    "Model",
    "Run #",
    "Call Status",
    "Status",
    "Intent",
    "Dish Name",
    "Dish Type",
    "Meal Type",
    "Meal Type Role",
    "Cuisine",
    "Cuisine Role",
    "Available",
    "Required",
    "Excluded",
    "Prefer",
    "Avoid",
    "Required Expression",
    "Numeric Bounds",
    "Dietary Restrictions",
    "Soft Preferences",
    "Generation Notes",
    "Spelling Corrections",
    "Clarification",
    "Acceptable Alternatives",
    "Gold Status",
    "Error Type",
    "Parsing Total (ms)",
    "Input Tokens",
    "Output Tokens",
    "Notes",
]


# ---------- normalization: extraction dict -> sheet cells ----------
def fmt_num(v):
    return str(int(v)) if isinstance(v, (int, float)) and float(v).is_integer() else str(v)


def expr_str(node, parent=None):
    if not node:
        return ""
    if node.get("op") == "ingredient":
        return (node.get("ingredient") or "").strip().lower()
    op = node.get("op")
    text = f" {op} ".join(expr_str(c, op) for c in node.get("children") or [])
    return f"({text})" if parent and parent != op else text


def extraction_cells(x):
    """Map a v6 extraction (dict) to sheet columns. Works for validated and unvalidated output."""
    if not isinstance(x, dict):
        return {}
    roles = {r: [] for r in ("available", "required", "excluded", "prefer", "avoid")}
    for i in x.get("ingredients") or []:
        if isinstance(i, dict) and i.get("role") in roles:
            tag = "c" if i.get("entity_type") == "category" else "s"
            roles[i["role"]].append(f"{(i.get('name') or '').strip().lower()}[{tag}]")
    bounds = [
        f"{b.get('field')}|{b.get('operator')}|{fmt_num(b.get('value'))}|{b.get('unit')}|{b.get('basis')}"
        for b in x.get("bounds") or []
        if isinstance(b, dict)
    ]

    def j(xs):
        return "; ".join(str(v) for v in xs or [] if v not in (None, ""))

    return {
        "Intent": x.get("intent") or "",
        "Dish Name": x.get("dish_name") or "",
        "Dish Type": x.get("dish_type") or "",
        "Meal Type": x.get("meal_type") or "",
        "Meal Type Role": x.get("meal_type_role") or "",
        "Cuisine": x.get("cuisine") or "",
        "Cuisine Role": x.get("cuisine_role") or "",
        "Available": j(roles["available"]),
        "Required": j(roles["required"]),
        "Excluded": j(roles["excluded"]),
        "Prefer": j(roles["prefer"]),
        "Avoid": j(roles["avoid"]),
        "Required Expression": expr_str(x.get("required_expression")),
        "Numeric Bounds": j(bounds),
        "Dietary Restrictions": j(x.get("dietary_restrictions")),
        "Soft Preferences": j(x.get("soft_preferences")),
        "Generation Notes": j(x.get("generation_notes")),
        "Spelling Corrections": j(
            f"{c.get('original')}→{c.get('normalized')}"
            for c in x.get("corrections") or []
            if isinstance(c, dict)
        ),
        "Clarification": " ".join(q for q in x.get("clarification_questions") or [] if q),
    }


def derived_status(x):
    if not isinstance(x, dict):
        return ""
    if x.get("clarification_questions"):
        return "needs_clarification"
    return "ready" if x.get("intent") == "recipe_search" else "unsupported"


def sheet_row(case, model, run, record):
    row = dict.fromkeys(SHEET_COLUMNS, "")
    row.update(
        {
            "Case ID": case["id"],
            "Split": case["split"],
            "Row Type": "model",
            "Model": model,
            "Run #": run,
        }
    )
    res, err = record.get("response"), record.get("error")
    if res:
        parsed = res.get("parsed") or {}
        row.update(extraction_cells(parsed.get("extraction")))
        row["Call Status"] = "Success"
        row["Status"] = parsed.get("status") or ""
        row["Clarification"] = parsed.get("clarification_question") or row["Clarification"]
        usage = res.get("token_usage") or {}
        row["Parsing Total (ms)"] = res.get("intent_parse_ms", "")
    else:
        detail = (err or {}).get("detail") or {}
        output = detail.get("model_output") if isinstance(detail, dict) else None
        row.update(extraction_cells(output))  # unvalidated output kept for lenient scoring
        row["Status"] = derived_status(output)
        code = (err or {}).get("status_code", "")
        label = detail.get("code", "") if isinstance(detail, dict) else str(detail)
        row["Call Status"] = f"HTTP {code} - {label}".strip()
        row["Error Type"] = (
            "validation_failed" if label == "invalid_model_output" else "call_failed"
        )
        msgs = (
            [
                f"{e.get('field')}: {e.get('reason')}"
                for e in (detail.get("validation_errors") or [])
            ]
            if isinstance(detail, dict)
            else []
        )
        row["Notes"] = ("Unvalidated output (lenient only). " if output else "") + " | ".join(msgs)[
            :900
        ]
        usage = (detail.get("token_usage") if isinstance(detail, dict) else None) or {}
        row["Parsing Total (ms)"] = (
            detail.get("intent_parse_ms", "") if isinstance(detail, dict) else ""
        )
    row["Input Tokens"] = usage.get("input_tokens") or ""
    row["Output Tokens"] = usage.get("output_tokens") or ""
    return row


# ---------- callers ----------
def make_inprocess_caller():
    from fastapi import HTTPException

    from recipe_search.llm.gpt_intent_service import parse_gpt6
    from recipe_search.llm.intent_service import IntentRequest

    def call(model, query):
        try:
            return {
                "response": json.loads(
                    json.dumps(parse_gpt6(IntentRequest(query=query), model), default=str)
                )
            }
        except HTTPException as e:
            return {"error": {"status_code": e.status_code, "detail": e.detail}}

    return call


def make_http_caller(base_url):
    import urllib.error
    import urllib.request

    def call(model, query):
        req = urllib.request.Request(
            f"{base_url}/intent/parse/{model}",
            data=json.dumps({"query": query}).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return {"response": json.load(r)}
        except urllib.error.HTTPError as e:
            try:
                body = json.loads(e.read())
            except ValueError:
                body = {}
            return {"error": {"status_code": e.code, "detail": body.get("detail", body)}}

    return call


def ensure_keys(models):
    need = {"DEEPSEEK_API_KEY" if m == "deepseek-flash" else "OPENAI_API_KEY" for m in models}
    for name in sorted(need):
        if not os.environ.get(name, "").strip():
            os.environ[name] = getpass.getpass(f"{name} (hidden, not saved): ").strip()
        if not os.environ.get(name):
            raise SystemExit(f"{name} is required.")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--output",
        default=str(get_settings().run_output("rq1/run")),
        help="Default var/outputs/rq1/run-<timestamp>; pass an existing run to resume it",
    )
    ap.add_argument("--models", nargs="+", default=MODELS, choices=MODELS)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument(
        "--cases-file",
        type=Path,
        required=True,
        help="Explicit source case JSON; never reads generated historical outputs",
    )
    ap.add_argument("--cases", nargs="+", help="Limit to these case IDs")
    ap.add_argument("--mode", choices=["inprocess", "http"], default="inprocess")
    ap.add_argument("--base-url", default=f"http://127.0.0.1:{get_settings().app_port}")
    ap.add_argument("--pause", type=float, default=0.3, help="Seconds between calls")
    a = ap.parse_args()

    cases_file = a.cases_file
    cases = json.loads(cases_file.read_text())
    if a.cases:
        cases = [c for c in cases if c["id"] in set(a.cases)]
    out = Path(a.output)
    (out / "calls").mkdir(parents=True, exist_ok=True)
    if a.mode == "inprocess":
        ensure_keys(a.models)
        call = make_inprocess_caller()
    else:
        call = make_http_caller(a.base_url)

    total = len(cases) * len(a.models) * a.runs
    done = 0
    meta = dict(
        started_at=datetime.now(timezone.utc).isoformat(),
        mode=a.mode,
        models=a.models,
        runs=a.runs,
        cases=[c["id"] for c in cases],
    )
    (out / "run_meta.json").write_text(json.dumps(meta, indent=2))
    # Order: run -> model -> case, so time-of-day drift is spread across models.
    for run in range(1, a.runs + 1):
        for model in a.models:
            for case in cases:
                done += 1
                path = out / "calls" / f"{case['id']}__{model}__r{run}.json"
                if path.exists():
                    continue
                t0 = time.perf_counter()
                rec = dict(
                    case_id=case["id"],
                    split=case["split"],
                    query=case["query"],
                    model=model,
                    run=run,
                    requested_at=datetime.now(timezone.utc).isoformat(),
                )
                rec.update(call(model, case["query"]))
                rec["wall_ms"] = round((time.perf_counter() - t0) * 1000, 2)
                if (
                    rec.get("error", {}).get("detail", {})
                    and isinstance(rec["error"]["detail"], dict)
                    and rec["error"]["detail"].get("code")
                    in (
                        "missing_api_key",
                        "intent_busy",
                        "openai_request_failed",
                        "deepseek_request_failed",
                        "connection_failed",
                        "intent_timeout",
                    )
                ):
                    print(
                        f"[{done}/{total}] {case['id']} {model} r{run}: {rec['error']['detail'].get('message')} (not saved, will retry on resume)"
                    )
                    time.sleep(2)
                    continue
                path.write_text(json.dumps(rec, ensure_ascii=False, indent=2))
                status = (
                    "ok"
                    if "response" in rec
                    else rec["error"].get("detail", {}).get("code", "error")
                )
                print(
                    f"[{done}/{total}] {case['id']} {model} r{run}: {status} {rec['wall_ms']:.0f}ms"
                )
                time.sleep(a.pause)

    # Sheet-ready CSV from every saved call (including earlier resumed ones).
    by_id = {c["id"]: c for c in json.loads(cases_file.read_text())}
    rows = []
    for p in sorted((out / "calls").glob("*.json")):
        r = json.loads(p.read_text())
        rows.append(sheet_row(by_id[r["case_id"]], r["model"], r["run"], r))
    order = {m: i for i, m in enumerate(MODELS)}
    rows.sort(key=lambda r: (r["Case ID"], order.get(r["Model"], 9), r["Run #"]))
    with open(out / "sheet_rows.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=SHEET_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    print(f"\nSaved {len(rows)} calls -> {out / 'sheet_rows.csv'}")


if __name__ == "__main__":
    main()
