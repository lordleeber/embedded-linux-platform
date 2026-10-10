#!/usr/bin/env python3
"""Show, open or close the pad of header pin 29 (PQ.05) through /dev/mem.

    sudo python3 scripts/pad_pin29.py show
    sudo python3 scripts/pad_pin29.py open     # output buffer on: tristate, input, pull cleared
    sudo python3 scripts/pad_pin29.py close    # back to the JP6 boot value

Lab tool for Step 4-a only. JP6 boots this pad tristated, so a GPIO output
never reaches the pin. This writes the pinmux register behind the kernel's
back; the change is lost on reboot. Step 4-b replaces it with a DT pinctrl
state. The register address was confirmed on this board by reading it back:
its low byte 0x58 decodes to exactly what debugfs pinconf reports for
soc_gpio32_pq5 (pull=up, tristate=1, enable-input=1, function=rsvd0).

open/close only write when the register looks like this pad: low byte 0x58
(boot value), or low byte 0x00 with bit 10 set (measured 0x400 once a GPIO
program has used the line). An all-zero register is refused, because that is what many
unrelated addresses read. Anything else means a wrong address or another
function, and the register is left alone. Bits outside the three fields are
always kept.

Limits: the read-modify-write goes through a Python memoryview of an mmap'd
page; CPython does not promise a single 32-bit bus access (it has behaved as
one here), and nothing stops the kernel's pinctrl driver from writing the same
register between the read and the write. Acceptable for a lab tool on a pad no
device claims; Step 4-b moves the pad setup into a DT pinctrl state.

Exit status: 0 = done (or nothing to do), 1 = unexpected register value
(nothing written), 2 = usage error or /dev/mem not accessible.
"""

import argparse
import mmap
import os
import sys


PINMUX_BASE = 0x02430000  # pinmux@2430000 in the base DT
REG_OFFSET = 0x68         # soc_gpio32_pq5
PULL_SHIFT, PULL_MASK = 2, 0x0C
TRISTATE = 0x10
INPUT = 0x40
FIELDS = PULL_MASK | TRISTATE | INPUT
BOOT_BITS = (2 << PULL_SHIFT) | TRISTATE | INPUT  # 0x58: pull-up, tristate, input on
GPIO_MODE = 0x400         # bit 10: 0 at boot, 1 after a GPIO line was used and released (measured; meaning not from the TRM)
PULLS = {0: "none", 1: "down", 2: "up", 3: "reserved"}


def decode(value):
    return (f"0x{value:08x} pull={PULLS[(value & PULL_MASK) >> PULL_SHIFT]} "
            f"tristate={int(bool(value & TRISTATE))} input={int(bool(value & INPUT))} "
            f"function={value & 0x3}")


def apply(reg, index, action):
    value = reg[index]
    print(f"before: {decode(value)}")
    if action == "show":
        return 0
    is_boot = value & 0xFF == BOOT_BITS
    is_open = value & 0xFF == 0x00 and value & GPIO_MODE
    if not (is_boot or is_open):
        print(f"error: 0x{value:08x} is neither the boot value (low byte 0x58) nor the open "
              "value (low byte 0x00 with bit 10 set); wrong address or pad reassigned, "
              "not writing", file=sys.stderr)
        return 1
    new = value & ~FIELDS & 0xFFFFFFFF
    if action == "close":
        new |= BOOT_BITS
    if new != value:
        reg[index] = new
    print(f"after:  {decode(reg[index])}")
    return 0


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mem", default="/dev/mem", help="memory device (tests pass a file)")
    parser.add_argument("action", choices=("show", "open", "close"))
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return 0 if e.code == 0 else 2

    try:
        fd = os.open(args.mem, os.O_RDWR | os.O_SYNC)
    except OSError as e:
        print(f"error: {args.mem}: {e.strerror}", file=sys.stderr)
        return 2
    try:
        with mmap.mmap(fd, mmap.PAGESIZE, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE,
                       offset=PINMUX_BASE) as page:
            reg = memoryview(page).cast("I")  # one aligned 32-bit access per index
            try:
                return apply(reg, REG_OFFSET // 4, args.action)
            finally:
                reg.release()
    except (OSError, ValueError) as e:
        print(f"error: {args.mem}: {e}", file=sys.stderr)
        return 2
    finally:
        os.close(fd)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
