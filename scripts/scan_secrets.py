"""Scan tracked files or every reachable Git blob without printing secret values.

This is a publication gate, not proof that credentials have been rotated.
An optional private JSON file of known legacy values strengthens local history checks.
"""

import argparse
import ast
import json
import re
import subprocess
from pathlib import Path

KEY_NAMES = re.compile(r"(?:^|_)(?:PASSWORD|API_KEY|TOKEN|SECRET)(?:$|_)", re.I)
TOKEN = re.compile(
    r"\b(?:sk-(?:proj-)?[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9_]{30,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[0-9A-Z]{16})\b"
)
PRIVATE_KEY = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")
DUMMIES = {
    "test",
    "test-key",
    "fake-secret",
    "unit-test-jev-key",
    "test-key-openai",
    "mock",
    "fake",
    "example",
    "REPLACE_ME",
}


def issues(name, data, known=()):
    text = data.decode("utf-8", errors="replace")
    found = []
    if any(value and value in text for value in known):
        found.append("known legacy secret")
    if TOKEN.search(text):
        found.append("provider token pattern")
    if PRIVATE_KEY.search(text) and name != "scripts/scan_secrets.py":
        found.append("private key material")
    if name.endswith(".py"):
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return found
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = getattr(node, "targets", []) or [getattr(node, "target", None)]
            if not any(isinstance(t, ast.Name) and KEY_NAMES.search(t.id) for t in targets):
                continue
            value = node.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str) and value.value:
                if name.startswith("tests/") and value.value in DUMMIES:
                    continue
                found.append("literal credential assignment at line " + str(node.lineno))
    return sorted(set(found))


def git(*args):
    return subprocess.check_output(["git", *args])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", action="store_true")
    parser.add_argument("--known-secrets-file", type=Path)
    args = parser.parse_args()
    known = json.loads(args.known_secrets_file.read_text()) if args.known_secrets_file else []
    count = 0
    failures = []
    if args.history:
        lines = git("rev-list", "--objects", "--all").decode().splitlines()
        seen = set()
        for line in lines:
            sha, _, name = line.partition(" ")
            if sha in seen or not name:
                continue
            seen.add(sha)
            if git("cat-file", "-t", sha).strip() != b"blob":
                continue
            data = git("cat-file", "blob", sha)
            count += 1
            reasons = issues(name, data, known)
            if reasons:
                failures.append((name, sha[:12], reasons))
    else:
        for name in git("ls-files", "-z").decode().split("\0"):
            if not name or not Path(name).is_file():
                continue
            count += 1
            reasons = issues(name, Path(name).read_bytes(), known)
            if reasons:
                failures.append((name, "working tree", reasons))
    for name, ref, reasons in failures:
        print(name, ref, ":", ", ".join(reasons))
    print(
        f"Scanned {count} "
        + ("historical blobs" if args.history else "tracked files")
        + f"; findings: {len(failures)}. Values are never printed."
    )
    raise SystemExit(bool(failures))


if __name__ == "__main__":
    main()
