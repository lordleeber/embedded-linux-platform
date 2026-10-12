#!/usr/bin/env python3
"""Verify "N tests" claims in the textbook against the real unittest loader.

Usage: python3 scripts/check_test_counts.py [docs_dir]

A claim is written as <span data-tests="tests/test_foo.py">12</span>; the path
is relative to the repo root (the parent of docs_dir); tests/test_foo.py@REV counts
the file as committed in REV (a chapter about an older step keeps its claim after
a later step adds tests). Cases are counted with
unittest's own loader, so the device must not be present: skipped tests count.
Exit status: 0 = all claims match, 1 = a claim is wrong,
2 = a claim cannot be measured (missing file, non-numeric claim, import error).
There is deliberately no --skip option.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

CLAIM = re.compile(r'data-tests="([^"]+)"[^>]*>([^<]*)<')


def count_cases(path):
    loader = unittest.TestLoader()
    # Same module name from another directory (PATH@REV vs PATH): load it afresh.
    sys.modules.pop(path.stem, None)
    try:
        suite = loader.discover(str(path.parent), pattern=path.name, top_level_dir=str(path.parent))
    finally:
        sys.modules.pop(path.stem, None)
        if str(path.parent) in sys.path:
            sys.path.remove(str(path.parent))
    if loader.errors:
        raise ImportError(loader.errors[0].strip().splitlines()[-1])
    return suite.countTestCases()


def count_at(root, rel):
    """Cases in REL (or REL@REV, from git); None when the file or revision does not exist."""
    if "@" not in rel:
        path = root / rel
        return count_cases(path) if path.is_file() else None
    rel, rev = rel.rsplit("@", 1)
    r = subprocess.run(["git", "-C", str(root), "show", f"{rev}:{rel}"], capture_output=True, text=True)
    if r.returncode != 0:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        # Same place under the temp root, so the file's own parents[1] paths still resolve sensibly.
        path = Path(tmp) / rel
        path.parent.mkdir(parents=True)
        path.write_text(r.stdout)
        return count_cases(path)


def main(argv):
    if len(argv) > 1 or any(a.startswith("-") for a in argv):
        print("usage: check_test_counts.py [docs_dir]", file=sys.stderr)
        return 2
    docs = Path(argv[0] if argv else "docs")
    if not docs.is_dir():
        print(f"ERROR no such directory: {docs}", file=sys.stderr)
        return 2
    root = docs.resolve().parent
    wrong = unmeasurable = checked = 0
    for page in sorted(docs.glob("*.html")):
        for rel, claim in CLAIM.findall(page.read_text(encoding="utf-8")):
            if not claim.strip().isdigit():
                print(f"ERROR {page.name}: claim '{claim}' for {rel} is not a number", file=sys.stderr)
                unmeasurable += 1
                continue
            try:
                actual = count_at(root, rel)
            except ImportError as exc:
                print(f"ERROR {page.name}: cannot load {rel}: {exc}", file=sys.stderr)
                unmeasurable += 1
                continue
            if actual is None:
                print(f"ERROR {page.name}: {rel} not found", file=sys.stderr)
                unmeasurable += 1
                continue
            checked += 1
            if actual != int(claim):
                print(f"{page.name}: claims {claim} tests in {rel}, runner finds {actual}")
                wrong += 1
    print(f"test-count claims checked: {checked}, wrong: {wrong}, unmeasurable: {unmeasurable}")
    if unmeasurable:
        return 2
    return 1 if wrong else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
