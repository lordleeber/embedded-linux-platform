#!/usr/bin/env python3
"""Add or remove the Step 4 overlay on the DEFAULT boot entry of extlinux.conf.

    sudo python3 scripts/install_edge_gpio_overlay.py install dts/edge-gpio-overlay.dtbo
    sudo python3 scripts/install_edge_gpio_overlay.py remove

install copies the dtbo to <boot-dir>/edge-gpio-overlay.dtbo and appends
/boot/edge-gpio-overlay.dtbo to the OVERLAYS line of the DEFAULT label
(comma-separated, the same format jetson-io writes), adding the line if the
label has none. The first install saves extlinux.conf.edge-gpio.bak next to
it. Both actions are idempotent. Takes effect on the next reboot.

Exit status: 0 = done (or nothing to do), 1 = extlinux.conf has no usable
DEFAULT label (file left untouched), 2 = usage or file error.
"""

import argparse
from pathlib import Path
import re
import shutil
import sys


NAME = "edge-gpio-overlay.dtbo"
ENTRY = "/boot/" + NAME


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


def edit(text, install):
    lines = text.splitlines(keepends=True)
    start, end = default_label_range(lines)
    for i in range(start + 1, end):
        m = re.match(r"(\s*OVERLAYS\s+)(\S*)(\s*)$", lines[i])
        if not m:
            continue
        items = [x for x in m.group(2).split(",") if x]
        if install:
            if ENTRY not in items:
                items.append(ENTRY)
        else:
            items = [x for x in items if x != ENTRY]
        if items:
            lines[i] = m.group(1) + ",".join(items) + m.group(3)
        else:
            del lines[i]
        return "".join(lines)
    if install:
        indent = re.match(r"\s*", lines[start + 1] if end > start + 1 else "\t").group(0) or "\t"
        if not lines[end - 1].endswith("\n"):
            lines[end - 1] += "\n"
        lines.insert(end, f"{indent}OVERLAYS {ENTRY}\n")
    return "".join(lines)


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
        if args.action == "install":
            backup = args.extlinux.with_name(args.extlinux.name + ".edge-gpio.bak")
            if not backup.exists():
                shutil.copy2(args.extlinux, backup)
            shutil.copyfile(args.dtbo, target)
        elif target.exists():
            target.unlink()
        if new != text:
            args.extlinux.write_text(new)
    except OSError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    print(f"{args.action}: {args.extlinux} {'updated' if new != text else 'unchanged'}; reboot to apply")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
