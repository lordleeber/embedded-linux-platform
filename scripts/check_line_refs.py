#!/usr/bin/env python3
"""Verify the line numbers the textbook prose cites ("第 91 行", "verify.sh:42") against the source files.

Usage: python3 scripts/check_line_refs.py [docs_dir]

Every such number in the prose is wrapped as
  <span data-ref="PATH:RANGES" data-expect="TEXT|TEXT">shown numbers</span>
(attributes in any order, markup allowed inside). RANGES is "A", "A-B" or several joined
by "," (e.g. "64-65,129"), with 1 <= A <= B. data-expect has one piece of text per range,
joined by "|" (write a literal pipe as &#124;). The piece must be on the FIRST line of its
range; "HEAD…TAIL" requires TAIL on the last line, a piece without "…" must be on both.
Neither HEAD nor TAIL may be empty. So a range that slid or grew is caught even when the
cited lines still exist. The numbers shown inside the span must be the same as RANGES.
PATH is relative to the repo root (the parent of docs_dir); PATH@REV reads the file as
committed in REV, like check_listings.py.
data-ref="-" marks a "第 N 行" that is not a source line (a row on the OLED screen).
Any "第 N 行" or "file.ext:N" left in the prose without a data-ref fails, so a new
citation cannot skip the check; tags and entities are removed before that scan.
Terminal output (<pre>) is not prose; neither is the "PATH:A–B — " head of a listing
caption, which check_listings.py verifies. The rest of a caption is prose.

Exit status: 0 = all references match, 1 = a reference drifted, is malformed or is
unmarked, 2 = a reference cannot be measured (file or revision missing). There is no --skip.
"""
import html
from html.parser import HTMLParser
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_listings import source_lines  # noqa: E402  (same PATH / PATH@REV rules)

SPEC = re.compile(r"(.+):(\d+(?:-\d+)?(?:,\d+(?:-\d+)?)*)")
NOT_PROSE = re.compile(r"<pre\b.*?</pre>|<script\b.*?</script>|<style\b.*?</style>", re.S)
LISTING_HEAD = re.compile(r'(<figure class="listing"><figcaption>)[^<:]+:\d+–\d+ — ')
RAW_EXPECT = re.compile(r'\sdata-expect="([^"]*)"')
SEP = r"\s*[–\-~～至到、,，和與及]\s*"
UNMARKED = [re.compile(rf"第\s*\d+(?:{SEP}\d+)*\s*行"),
            re.compile(r"[\w./-]*\w\.[A-Za-z]\w*:\d+"),
            re.compile(r"\b(?:Makefile|Kconfig|Dockerfile|CMakeLists\.txt):\d+")]


class Prose(HTMLParser):
    """Plain text of the prose, with every data-ref span taken out and collected."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text, self.refs, self.spans = [], [], []

    def handle_starttag(self, tag, attrs):
        if tag != "span":
            return
        attrs = dict(attrs)
        if "data-ref" not in attrs:
            self.spans.append(None)
            return
        # The raw attribute, not the parser's unescaped one: &#124; is a pipe in the text, "|" separates ranges.
        raw = RAW_EXPECT.search(self.get_starttag_text())
        self.spans.append({"spec": attrs["data-ref"], "expect": raw.group(1) if raw else None,
                           "text": [], "nested": any(self.spans)})

    def handle_endtag(self, tag):
        if tag == "span" and self.spans:
            ref = self.spans.pop()
            if ref:
                self.refs.append(ref)
                self.text.append(" ")

    def handle_data(self, data):
        ref = next((r for r in reversed(self.spans) if r), None)
        (ref["text"] if ref else self.text).append(data)


def ranges(text):
    out = []
    for part in text.split(","):
        a, _, b = part.partition("-")
        out.append((int(a), int(b or a)))
    return out


def check_ref(page, ref, root):
    """Return (problems, measurable)."""
    spec = ref["spec"]
    m = SPEC.fullmatch(spec)
    pieces = [html.unescape(p) for p in ref["expect"].split("|")] if ref["expect"] else []
    if ref["nested"] or not m or len(pieces) != len(ranges(m.group(2))):
        return [f"{page}: malformed data-ref {spec!r} (need PATH:RANGES, one data-expect text per range, no nesting)"], True
    path, rs = m.group(1), ranges(m.group(2))
    lines = source_lines(root, path)
    if lines is None:
        return [], False
    problems = []
    shown = [int(n) for n in re.findall(r"\d+", "".join(ref["text"]))]
    want = [n for a, b in rs for n in ((a,) if a == b else (a, b))]
    if shown != want:
        problems.append(f"{page}: {spec} shows {shown} in the text")
    for (a, b), piece in zip(rs, pieces):
        head, dots, tail = piece.partition("…")
        tail = tail if dots else head  # without "…" the piece pins both ends
        if not head or not tail:
            problems.append(f"{page}: {spec} has an empty data-expect head or tail")
        elif not 1 <= a <= b <= len(lines):
            problems.append(f"{page}: {path}:{a}-{b} is not a range of lines 1-{len(lines)}")
        elif head not in lines[a - 1] or tail not in lines[b - 1]:
            problems.append(f"{page}: {path}:{a}-{b} does not start with a line containing {head!r}"
                            f" and end with one containing {tail!r}")
    return problems, True


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
        source = page.read_text(encoding="utf-8")
        prose = Prose()
        prose.feed(LISTING_HEAD.sub(r"\1", NOT_PROSE.sub(" ", source)))
        prose.close()
        for ref in prose.refs:
            if ref["spec"] == "-":
                continue
            problems, measurable = check_ref(page.name, ref, root)
            if not measurable:
                print(f"ERROR {page.name}: {ref['spec'].rpartition(':')[0]} not found", file=sys.stderr)
                unmeasurable += 1
                continue
            checked += 1
            for p in problems:
                print(p)
            bad += len(problems)
        rest = "".join(prose.text)
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
