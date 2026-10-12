#!/usr/bin/env python3
"""Verify that every code listing in the textbook matches its source file verbatim.

Usage: python3 scripts/check_listings.py [docs_dir]

A listing is written as
  <figure class="listing"><figcaption>PATH:A–B — ...</figcaption>
  <pre data-start="A" ...>escaped source lines A..B</pre></figure>
PATH is relative to the repo root (the parent of docs_dir) or absolute.
PATH@REV (e.g. kernel/x.c@c818fea) reads the file as committed in REV instead of
the working tree: a chapter about an older step keeps quoting the code that step
shipped after a later step changed or removed it.
Exit status: 0 = all listings match, 1 = a listing drifted from its source,
2 = a listing cannot be measured (source file missing). There is no --skip.
"""
import html
from pathlib import Path
import re
import subprocess
import sys

LISTING = re.compile(
    r'<figure class="listing"><figcaption>([^<:]+):(\d+)–(\d+) — [^<]*</figcaption>\s*'
    r'<pre data-start="(\d+)"[^>]*>(.*?)</pre>', re.S)


def source_lines(root, path):
    """Lines of PATH or PATH@REV, or None when the file (or revision) does not exist."""
    if "@" in path:
        path, rev = path.rsplit("@", 1)
        r = subprocess.run(["git", "-C", str(root), "show", f"{rev}:{path}"],
                           capture_output=True, text=True)
        return r.stdout.splitlines() if r.returncode == 0 else None
    src = Path(path) if path.startswith("/") else root / path
    return src.read_text(encoding="utf-8").splitlines() if src.is_file() else None


def main(argv):
    if len(argv) > 1 or any(a.startswith("-") for a in argv):
        print("usage: check_listings.py [docs_dir]", file=sys.stderr)
        return 2
    docs = Path(argv[0] if argv else "docs")
    if not docs.is_dir():
        print(f"ERROR no such directory: {docs}", file=sys.stderr)
        return 2
    root = docs.resolve().parent
    checked = drifted = unmeasurable = 0
    for page in sorted(docs.glob("*.html")):
        for path, a, b, start, body in LISTING.findall(page.read_text(encoding="utf-8")):
            a, b = int(a), int(b)
            lines = source_lines(root, path)
            if lines is None:
                print(f"ERROR {page.name}: {path} not found", file=sys.stderr)
                unmeasurable += 1
                continue
            checked += 1
            want = lines[a - 1:b]
            if html.unescape(body).splitlines() != want or int(start) != a:
                print(f"{page.name}: {path}:{a}–{b} no longer matches the source")
                drifted += 1
    print(f"listings checked: {checked}, drifted: {drifted}, unmeasurable: {unmeasurable}")
    if unmeasurable:
        return 2
    return 1 if drifted else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
