"""Back up and normalize ONLY recipecategory and keywords in an existing ES index.

prepare is read-only. apply requires a completed backup and optimistic concurrency.
No index deletion, document creation, mapping changes or embedding requests.
"""

import argparse
import fcntl
import gzip
import hashlib
import json
from datetime import datetime, timezone
from itertools import islice
from pathlib import Path

from elasticsearch import helpers

from recipe_search.ingest.ingest_recipes import DEFAULT_ES_URL, DEFAULT_INDEX, connect_elasticsearch
from recipe_search.matching.tag_normalization import VERSION, normalize_tags
from recipe_search.settings import get_settings

FIELDS = ("recipecategory", "keywords")


def patch_tags(source):
    return {field: normalize_tags(source.get(field)) for field in FIELDS}


def other_hash(source):
    other = {k: v for k, v in source.items() if k not in FIELDS}
    return hashlib.sha256(
        json.dumps(other, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def read_backup(path):
    with gzip.open(path, "rt") as f:
        for line in f:
            yield json.loads(line)


def recovery_state(record, document):
    if not document.get("found") or document.get("_id") != record["id"]:
        return "conflict"
    current = document.get("_source", {})
    if all(f in current and current[f] == record["after"][f] for f in FIELDS):
        return "done"
    if all(
        (f in current) == (f in record["before"]) and current.get(f) == record["before"].get(f)
        for f in FIELDS
    ):
        return "pending"
    return "conflict"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["prepare", "apply", "resume"])
    parser.add_argument(
        "--run-dir",
        type=Path,
        default=get_settings().output_dir / "tag-refresh",
        help="Backup/manifest folder shared by prepare/apply/resume; default var/outputs/tag-refresh",
    )
    parser.add_argument("--es-url", default=DEFAULT_ES_URL)
    parser.add_argument("--index", default=DEFAULT_INDEX)
    args = parser.parse_args()
    # The OS releases this lock even if the terminal/process is killed.
    if args.mode != "prepare":
        lock = (args.run_dir / "writer.lock").open("a")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit(
                "Another writer is running for this backup. Do not start a second one."
            )
    client = connect_elasticsearch(args.es_url)
    info = client.indices.get(index=args.index)
    if len(info) != 1 or args.index not in info:
        raise RuntimeError("Use one concrete index, not an alias or pattern.")
    uuid = info[args.index]["settings"]["index"]["uuid"]
    props = info[args.index]["mappings"]["properties"]
    if any(props[f]["type"] != "keyword" for f in FIELDS):
        raise RuntimeError("Unexpected field types.")
    backup = args.run_dir / "original-tags.jsonl.gz"
    manifest = args.run_dir / "manifest.json"
    if args.mode == "prepare":
        args.run_dir.mkdir(parents=True, exist_ok=False)
        total = client.count(index=args.index)["count"]
        scanned = changed = 0
        samples = []
        with gzip.open(backup, "wt") as out:
            for hit in helpers.scan(
                client,
                index=args.index,
                query={
                    "query": {"match_all": {}},
                    "_source": list(FIELDS),
                    "seq_no_primary_term": True,
                },
                size=1000,
                scroll="5m",
            ):
                scanned += 1
                source = hit["_source"]
                desired = patch_tags(source)
                if any(source.get(f) != desired[f] for f in FIELDS):
                    record = {
                        "id": hit["_id"],
                        "before": source,
                        "after": desired,
                        "seq_no": hit["_seq_no"],
                        "primary_term": hit["_primary_term"],
                    }
                    out.write(json.dumps(record) + "\n")
                    changed += 1
                    if len(samples) < 5:
                        full = client.get(index=args.index, id=hit["_id"])["_source"]
                        samples.append(
                            {
                                "id": hit["_id"],
                                "other_fields_sha256": other_hash(full),
                                "before": source,
                                "after": desired,
                            }
                        )
                if scanned % 10000 == 0:
                    print(f"Prepared {scanned} documents; {changed} changes", flush=True)
        if scanned != total:
            raise RuntimeError("Index count changed during backup; no apply manifest produced.")
        data = dict(
            index=args.index,
            index_uuid=uuid,
            version=VERSION,
            total=total,
            scanned=scanned,
            changes=changed,
            samples=samples,
            created_at=datetime.now(timezone.utc).isoformat(),
            backup_sha256=hashlib.sha256(backup.read_bytes()).hexdigest(),
        )
        manifest.write_text(json.dumps(data, indent=2) + "\n")
        print(json.dumps(data, indent=2))
        return

    data = json.loads(manifest.read_text())
    if data["index_uuid"] != uuid or data["index"] != args.index or data["version"] != VERSION:
        raise RuntimeError("Index or normalizer changed since preparation.")
    if hashlib.sha256(backup.read_bytes()).hexdigest() != data["backup_sha256"]:
        raise RuntimeError("Backup checksum mismatch.")
    if args.mode == "apply" and (args.run_dir / "apply-started.json").exists():
        raise RuntimeError(
            "This run was already started. Use resume to reconcile current records safely."
        )
    if not (args.run_dir / "apply-started.json").exists():
        (args.run_dir / "apply-started.json").write_text(
            json.dumps({"started_at": datetime.now(timezone.utc).isoformat()})
        )
    recovery = {"already_done": 0, "conflicts": 0, "scanned": 0}
    conflicts = (args.run_dir / "recovery-conflicts.jsonl").open("a")

    def actions():
        records = iter(read_backup(backup))
        while batch := list(islice(records, 500)):
            if args.mode == "resume":
                docs = client.mget(
                    index=args.index, ids=[r["id"] for r in batch], source_includes=list(FIELDS)
                )["docs"]
                if len(docs) != len(batch):
                    raise RuntimeError("Incomplete reconciliation response.")
            else:
                docs = [None] * len(batch)
            for r, doc in zip(batch, docs):
                recovery["scanned"] += 1
                if args.mode == "resume":
                    state = recovery_state(r, doc)
                    if state == "done":
                        recovery["already_done"] += 1
                        continue
                    if state == "conflict":
                        recovery["conflicts"] += 1
                        conflicts.write(
                            json.dumps({"id": r["id"], "reason": "missing_or_changed_tags"}) + "\n"
                        )
                        conflicts.flush()
                        continue
                    seq, term = doc["_seq_no"], doc["_primary_term"]
                else:
                    seq, term = r["seq_no"], r["primary_term"]
                yield {
                    "_op_type": "update",
                    "_index": args.index,
                    "_id": r["id"],
                    "if_seq_no": seq,
                    "if_primary_term": term,
                    "doc": r["after"],
                }
            if recovery["scanned"] % 5000 == 0:
                print(
                    f"Reconciled {recovery['scanned']}; already done {recovery['already_done']}; conflicts {recovery['conflicts']}",
                    flush=True,
                )

    updated = failed = 0
    with (args.run_dir / "failures.jsonl").open("a") as out:
        for ok, result in helpers.streaming_bulk(
            client,
            actions(),
            chunk_size=250,
            max_retries=2,
            raise_on_error=False,
            raise_on_exception=False,
        ):
            if ok:
                updated += 1
            else:
                failed += 1
                out.write(json.dumps(result) + "\n")
                out.flush()
            if (updated + failed) % 5000 == 0:
                print(f"Applied {updated}; failed {failed}", flush=True)
    client.indices.refresh(index=args.index)
    checked = mismatched = 0
    batch = []

    def verify(records):
        docs = client.mget(
            index=args.index, ids=[r["id"] for r in records], source_includes=list(FIELDS)
        )["docs"]
        return sum(
            not d.get("found") or any(d.get("_source", {}).get(f) != r["after"][f] for f in FIELDS)
            for r, d in zip(records, docs)
        )

    for r in read_backup(backup):
        batch.append(r)
        if len(batch) == 500:
            mismatched += verify(batch)
            checked += len(batch)
            batch = []
            if checked % 10000 == 0:
                print(f"Verified {checked}; mismatched {mismatched}", flush=True)
    if batch:
        mismatched += verify(batch)
        checked += len(batch)
    untouched = all(
        other_hash(client.get(index=args.index, id=s["id"])["_source"]) == s["other_fields_sha256"]
        for s in data["samples"]
    )
    total_after = client.count(index=args.index)["count"]
    report = dict(
        mode=args.mode,
        updated=updated,
        failed=failed,
        verified=checked,
        mismatched=mismatched,
        **recovery,
        other_fields_unchanged_in_samples=untouched,
        total_before=data["total"],
        total_after=total_after,
    )
    report["success"] = (
        not failed
        and not mismatched
        and not recovery["conflicts"]
        and untouched
        and updated + recovery["already_done"] == data["changes"]
        and total_after == data["total"]
    )
    (args.run_dir / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    if not report["success"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
