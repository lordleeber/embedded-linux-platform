#!/usr/bin/env python3
"""Add or remove the Step 4 overlay on the DEFAULT boot entry of extlinux.conf.

    sudo python3 scripts/install_edge_gpio_overlay.py install dts/edge-gpio-overlay.dtbo
    sudo python3 scripts/install_edge_gpio_overlay.py remove

install copies the dtbo to <boot-dir>/edge-gpio-overlay.dtbo and appends
/boot/edge-gpio-overlay.dtbo to the OVERLAYS line of the DEFAULT label
(comma-separated, no spaces: the format jetson-io writes), adding the line if
the label has none. remove strips the entry from every label (DEFAULT may have
changed since install) and only then deletes the dtbo. The first install saves
extlinux.conf.edge-gpio.bak next to it. Both actions are idempotent. The file
is replaced atomically (temp file, fsync, rename), so a full disk or power cut
cannot leave a truncated extlinux.conf. Takes effect on the next reboot.

Exit status: 0 = done (or nothing to do), 1 = extlinux.conf has no usable
DEFAULT label or an OVERLAYS line this script cannot parse (file left
untouched), 2 = usage or file error.
"""

import argparse
import os
from pathlib import Path
import re
import shutil
import sys


NAME = "edge-gpio-overlay.dtbo"
ENTRY = "/boot/" + NAME
# "<indent>OVERLAYS[ <a,b,...>]" -- blanks are spaces/tabs only, so the newline is never eaten.
OVERLAYS = re.compile(r"(?P<indent>[ \t]*)OVERLAYS(?:(?P<sep>[ \t]+)(?P<val>\S+))?[ \t]*(?P<nl>\n?)")


class ConfigError(Exception):
    pass


def default_label_range(lines):
    """Return (start, end) line indexes of the DEFAULT label's block."""
    default = None
    for line in lines:
        m = re.match(r"\s*DEFAULT\s+(\S+)", line)
        if m:
            default = m.group(1)
    if default is None:
        raise ConfigError("no DEFAULT line")
    start = None
    for i, line in enumerate(lines):
        m = re.match(r"\s*LABEL\s+(\S+)", line)
        if m:
            if start is not None:
                return start, last_content(lines, start, i)
            if m.group(1) == default:
                start = i
    if start is None:
        raise ConfigError(f"DEFAULT label '{default}' not found")
    return start, last_content(lines, start, len(lines))


def last_content(lines, start, stop):
    """End of the block: drop trailing blank and comment lines."""
    end = stop
    while end > start + 1 and (not lines[end - 1].strip() or lines[end - 1].lstrip().startswith("#")):
        end -= 1
    return end


def overlays_line(line):
    """Parse an OVERLAYS line into (match, items); None if it is not one; error if malformed."""
    if not re.match(r"\s*OVERLAYS\b", line):
        return None
    m = OVERLAYS.fullmatch(line)
    if not m:
        raise ConfigError(f"cannot parse {line.strip()!r} (expected comma-separated paths, no spaces)")
    return m, [x for x in (m.group("val") or "").split(",") if x]


def render(m, items):
    return f"{m.group('indent')}OVERLAYS{m.group('sep') or ' '}{','.join(items)}{m.group('nl')}"


def edit(text, install):
    lines = text.splitlines(keepends=True)
    if not install:
        # Every label: the dtbo is about to be deleted, nothing may keep pointing at it.
        out = []
        for line in lines:
            parsed = overlays_line(line) if ENTRY in line else None
            if parsed:
                m, items = parsed
                items = [x for x in items if x != ENTRY]
                if items:
                    out.append(render(m, items))
                continue
            out.append(line)
        return "".join(out)

    start, end = default_label_range(lines)
    found = [(i, overlays_line(lines[i])) for i in range(start + 1, end)]
    found = [(i, p) for i, p in found if p]
    if len(found) > 1:
        raise ConfigError("DEFAULT label has more than one OVERLAYS line")
    if found:
        i, (m, items) = found[0]
        if ENTRY not in items:
            lines[i] = render(m, items + [ENTRY])
        return "".join(lines)
    indent = re.match(r"\s*", lines[start + 1] if end > start + 1 else "\t").group(0) or "\t"
    if not lines[end - 1].endswith("\n"):
        lines[end - 1] += "\n"
    lines.insert(end, f"{indent}OVERLAYS {ENTRY}\n")
    return "".join(lines)


def write_atomic(path, text):
    tmp = path.with_name(path.name + ".edge-gpio.tmp")
    try:
        with open(tmp, "w") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        shutil.copymode(path, tmp)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    dir_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--extlinux", default="/boot/extlinux/extlinux.conf", type=Path)
    parser.add_argument("--boot-dir", default="/boot", type=Path)
    sub = parser.add_subparsers(dest="action", required=True)
    inst = sub.add_parser("install")
    inst.add_argument("dtbo", type=Path)
    sub.add_parser("remove")
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return 0 if e.code == 0 else 2

    try:
        text = args.extlinux.read_text()
        if args.action == "install" and not args.dtbo.is_file():
            print(f"error: {args.dtbo} not found (run make -C dts first)", file=sys.stderr)
            return 2
        new = edit(text, args.action == "install")
    except ConfigError as e:
        print(f"error: {args.extlinux}: {e}", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    target = args.boot_dir / NAME
    try:
        # Order keeps every OVERLAYS entry pointing at an existing file:
        # install copies the dtbo first, remove deletes it last.
        if args.action == "install":
            backup = args.extlinux.with_name(args.extlinux.name + ".edge-gpio.bak")
            if not backup.exists():
                shutil.copy2(args.extlinux, backup)
            shutil.copyfile(args.dtbo, target)
        if new != text:
            write_atomic(args.extlinux, new)
        if args.action == "remove" and target.exists():
            target.unlink()
    except OSError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    print(f"{args.action}: {args.extlinux} {'updated' if new != text else 'unchanged'}; reboot to apply")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
