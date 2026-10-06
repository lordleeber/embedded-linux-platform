#!/usr/bin/env python3
"""Verify "N tests" claims in the textbook against the real unittest loader.

Usage: python3 scripts/check_test_counts.py [docs_dir]

A claim is written as <span data-tests="tests/test_foo.py">12</span>; the path
is relative to the repo root (the parent of docs_dir). Cases are counted with
unittest's own loader, so the device must not be present: skipped tests count.
Exit status: 0 = all claims match, 1 = a claim is wrong,
2 = a claim cannot be measured (missing file, non-numeric claim, import error).
There is deliberately no --skip option.
"""
from pathlib import Path
import re
import sys
import unittest

CLAIM = re.compile(r'data-tests="([^"]+)"[^>]*>([^<]*)<')


def count_cases(path):
    loader = unittest.TestLoader()
    suite = loader.discover(str(path.parent), pattern=path.name, top_level_dir=str(path.parent))
    if loader.errors:
        raise ImportError(loader.errors[0].strip().splitlines()[-1])
    return suite.countTestCases()


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
            path = root / rel
            if not path.is_file():
                print(f"ERROR {page.name}: {rel} not found", file=sys.stderr)
                unmeasurable += 1
                continue
            if not claim.strip().isdigit():
                print(f"ERROR {page.name}: claim '{claim}' for {rel} is not a number", file=sys.stderr)
                unmeasurable += 1
                continue
            try:
                actual = count_cases(path)
            except ImportError as exc:
                print(f"ERROR {page.name}: cannot load {rel}: {exc}", file=sys.stderr)
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
