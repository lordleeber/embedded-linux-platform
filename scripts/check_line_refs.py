#!/usr/bin/env python3
"""Verify the line numbers the textbook prose cites ("第 91 行", "verify.sh:42") against the source files.

Usage: python3 scripts/check_line_refs.py [docs_dir]

Every such number in the prose is wrapped as
  <span data-ref="PATH:RANGES" data-expect="TEXT|TEXT">shown numbers</span>
RANGES is "A", "A-B" or several joined by "," (e.g. "64-65,129"); data-expect has one
piece of text per range, joined by "|". The piece must be on the FIRST line of its range;
"HEAD…TAIL" requires TAIL on the last line, a piece without "…" must be on both. So a range that slid or grew is caught
even when the cited lines still exist. The numbers shown inside the span must be the
same as RANGES. PATH is relative to the repo root (the parent of docs_dir);
PATH@REV reads the file as committed in REV, like check_listings.py.
data-ref="-" marks a "第 N 行" that is not a source line (a row on the OLED screen).
Any "第 N 行" or "file.ext:N" left in the prose without a data-ref fails, so a new
citation cannot skip the check. Terminal output (<pre>) and listing captions are not prose.

Exit status: 0 = all references match, 1 = a reference drifted, is malformed or is
unmarked, 2 = a reference cannot be measured (file or revision missing). There is no --skip.
"""
import html
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_listings import source_lines  # noqa: E402  (same PATH / PATH@REV rules)

REF = re.compile(r'<span data-ref="([^"]*)"(?: data-expect="([^"]*)")?>(.*?)</span>', re.S)
SPEC = re.compile(r"(.+):(\d+(?:-\d+)?(?:,\d+(?:-\d+)?)*)")
NOT_PROSE = re.compile(r"<pre\b.*?</pre>|<figcaption>.*?</figcaption>|<script\b.*?</script>|<style\b.*?</style>", re.S)
UNMARKED = [re.compile(r"第 ?\d+(?: ?[–-] ?\d+)?(?:[、,] ?\d+(?: ?[–-] ?\d+)?)* ?行"),
            re.compile(r"[\w./-]+\.(?:sh|py|c|h|cpp|txt|dts|md):\d+"),
            re.compile(r"\b(?:Makefile|CMakeLists\.txt):\d+")]


def ranges(text):
    out = []
    for part in text.split(","):
        a, _, b = part.partition("-")
        out.append((int(a), int(b or a)))
    return out


def shown_numbers(inner):
    return [int(n) for n in re.findall(r"\d+", re.sub(r"<[^>]+>", "", inner))]


def main(argv):
    if len(argv) > 1 or any(a.startswith("-") for a in argv):
        print("usage: check_line_refs.py [docs_dir]", file=sys.stderr)
        return 2
    docs = Path(argv[0] if argv else "docs")
    if not docs.is_dir():
        print(f"ERROR no such directory: {docs}", file=sys.stderr)
        return 2
    root = docs.resolve().parent
    checked = bad = unmeasurable = 0
    for page in sorted(docs.glob("*.html")):
        prose = NOT_PROSE.sub(" ", page.read_text(encoding="utf-8"))
        for spec, expect, inner in REF.findall(prose):
            if spec == "-":
                continue
            m = SPEC.fullmatch(spec)
            pieces = html.unescape(expect).split("|") if expect else []
            if not m or len(pieces) != len(ranges(m.group(2))):
                print(f"{page.name}: malformed data-ref {spec!r} (need PATH:RANGES and one data-expect text per range)")
                bad += 1
                continue
            path, rs = m.group(1), ranges(m.group(2))
            lines = source_lines(root, path)
            if lines is None:
                print(f"ERROR {page.name}: {path} not found", file=sys.stderr)
                unmeasurable += 1
                continue
            checked += 1
            want = [n for a, b in rs for n in ((a,) if a == b else (a, b))]
            if shown_numbers(inner) != want:
                print(f"{page.name}: {spec} shows {shown_numbers(inner)} in the text")
                bad += 1
            for (a, b), piece in zip(rs, pieces):
                head, dots, tail = piece.partition("…")
                tail = tail if dots else head  # without "…" the piece pins both ends
                if b > len(lines) or head not in lines[a - 1] or tail not in lines[b - 1]:
                    print(f"{page.name}: {path}:{a}-{b} does not start with a line containing {head!r}"
                          + f" and end with one containing {tail!r}")
                    bad += 1
        rest = REF.sub(" ", prose)
        for pattern in UNMARKED:
            for hit in pattern.finditer(rest):
                print(f"{page.name}: unmarked line reference {hit.group(0)!r} (wrap it in data-ref)")
                bad += 1
    print(f"line refs checked: {checked}, bad: {bad}, unmeasurable: {unmeasurable}")
    if unmeasurable:
        return 2
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
