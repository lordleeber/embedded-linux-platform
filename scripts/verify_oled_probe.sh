#!/usr/bin/env bash
# Step 9 acceptance: bring up the SSD1306 OLED from userspace with build/oled_probe.
# Usage: bash scripts/verify_oled_probe.sh [--bus N] [--addr 0xNN] [--no-power-cycle]
#
# No root needed: the user must be in the i2c group. Default wiring: OLED SDA/SCL on header
# pins 27/28 = c240000.i2c (found by name), VCC pin 17 (3.3 V), GND pin 20; address 0x3c.
# The SSD1306 cannot be read back over I2C, so a person at the board answers y/n for what
# the panel shows. Checks: the bus scan, every mode of the tool (person looks), the unit
# tests against the real OLED, a state scrambled by i2ctransfer (inverse, mirrored, vertical
# addressing, contrast 0) that the next run must undo by itself, an absent address as an
# I/O error, then (unless --no-power-cycle) the person disconnects the whole OLED: the tool
# must fail with no ACK; after reconnecting the panel must be dark (power-on reset, display
# off) and the tool must bring it up again.
# Exit status: 0 = all checks passed, 1 = a check failed, 2 = environment/usage problem.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOOL="$REPO/build/oled_probe"
CONTROLLER=c240000.i2c
BUS=""
ADDR=0x3c
CYCLE=1
ANSWER_TIMEOUT=120
failures=0

pass() { echo "PASS $*"; }
fail() { echo "FAIL $*"; failures=$((failures + 1)); }
die()  { echo "ERROR $*" >&2; exit 2; }

while [[ $# -gt 0 ]]; do
    case $1 in
        --bus) BUS="${2:-}"; shift 2 || die "--bus needs a number" ;;
        --addr) ADDR="${2:-}"; shift 2 || die "--addr needs an address" ;;
        --no-power-cycle) CYCLE=0; shift ;;
        *) die "usage: $0 [--bus N] [--addr 0xNN] [--no-power-cycle]" ;;
    esac
done
for c in i2cdetect i2ctransfer; do
    command -v $c >/dev/null || die "$c missing (apt install i2c-tools)"
done
[[ -r /dev/tty ]] || die "needs a terminal: a person answers what the OLED shows"
cmake -S "$REPO" -B "$REPO/build" >/dev/null && cmake --build "$REPO/build" --target oled_probe >/dev/null \
    || die "build of oled_probe failed"
tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT
UNPLUGGED=0
on_int() {
    [[ $UNPLUGGED -eq 1 ]] && echo ">>> Interrupted: reconnect the OLED."
    exit 2
}
trap on_int INT TERM

tool() { timeout -k 1 5 "$TOOL" --bus "$BUS" --addr "$ADDR" "$@"; }
# ask "question": y -> 0, n -> 1; no answer within the timeout counts as n.
ask() {
    local ans=""
    read -r -t "$ANSWER_TIMEOUT" -p ">>> $1 [y/n] " ans </dev/tty || echo
    [[ $ans == [yY]* ]]
}
present() {
    i2cdetect -y -r "$BUS" "$ADDR" "$ADDR" 2>/dev/null | tail -n +2 | grep -qw "${ADDR#0x}"
}
# show MODE QUESTION: run the tool, then a person confirms the picture
show() {
    local out rc
    out="$(tool "$1" 2>&1)"; rc=$?
    echo "  $out"
    if [[ $rc -ne 0 ]]; then fail "oled_probe $1: exit $rc"; return; fi
    if ask "$2"; then pass "$1: $2"; else fail "$1: person answered no to '$2'"; fi
}

if [[ -z $BUS ]]; then
    echo "== which bus is $CONTROLLER (i2cdetect -l)"
    BUS="$(i2cdetect -l | awk -v c="$CONTROLLER" '$3 == c { sub("i2c-", "", $1); print $1 }')"
    [[ -n "$BUS" ]] || die "no adapter named $CONTROLLER (pass --bus)"
    pass "$CONTROLLER is i2c-$BUS (header pins 27/28)"
fi
[[ -r /dev/i2c-$BUS && -w /dev/i2c-$BUS ]] || die "cannot open /dev/i2c-$BUS (add yourself to the i2c group)"
ADDR="$(printf '0x%02x' "$ADDR")" || die "bad address"

echo "== bus scan (i2cdetect -y -r $BUS)"
i2cdetect -y -r "$BUS"
if present; then pass "OLED answers at $ADDR on i2c-$BUS"
else fail "nothing at $ADDR on i2c-$BUS (wiring? some modules use 0x3d)"; fi

echo "== the tool, mode by mode (look at the panel)"
show clear   "Is the whole screen dark?"
show pixel   "Five single dots: four corners and the centre?"
show pattern "A border around the edge and a diagonal from the TOP-LEFT corner going down-right?"
show edge    "EDGE, white on black, readable (not mirrored, not upside down), centred?"

echo "== unit tests against the real OLED"
if EDGE_OLED_HW=1 EDGE_OLED_BUS="$BUS" EDGE_OLED_ADDR="$ADDR" \
        python3 -m unittest discover -s "$REPO/tests" -p test_oled_probe.py >"$tmpdir/ut" 2>&1; then
    pass "test_oled_probe.py ($(tail -1 "$tmpdir/ut"))"
else
    cat "$tmpdir/ut"
    fail "test_oled_probe.py"
fi

echo "== scrambled state: i2ctransfer leaves it inverse (0xA7), mirrored (0xA0, 0xC0),"
echo "   in vertical addressing (0x20 0x01) with contrast 0 (0x81 0x00); the tool must undo it"
if i2ctransfer -y "$BUS" w9@"$ADDR" 0x00 0xA7 0xA0 0xC0 0x20 0x01 0x81 0x00 0xAF; then
    show edge "After the scramble: EDGE looks exactly as before (white on black, readable, bright)?"
else
    fail "i2ctransfer scramble"
fi

echo "== absent address (what an unplugged OLED looks like)"
other=0x3d; [[ $ADDR == 0x3d ]] && other=0x3c
err="$(timeout -k 1 5 "$TOOL" --bus "$BUS" --addr $other edge 2>&1 >/dev/null)"; rc=$?
echo "  $err"
if [[ $rc -eq 1 && $err == *"Remote I/O error"* ]]; then pass "$other: exit 1, Remote I/O error"
else fail "$other: exit $rc, '$err'"; fi

if [[ $CYCLE -eq 1 ]]; then
    # Unplugging VCC alone is not a power cycle: measured 2026-10-13, the SSD1306 still
    # ACKed with VCC out (most likely fed through the SDA/SCL pull-ups). Take all four off.
    echo
    echo ">>> DISCONNECT the OLED: all four wires (VCC, GND, SDA, SCL), then answer."
    UNPLUGGED=1
    ask "OLED disconnected (all four wires)?" || die "power cycle not done"
    err="$(tool edge 2>&1 >/dev/null)"; rc=$?
    echo "  $err"
    if [[ $rc -eq 1 && $err == *"Remote I/O error"* ]]; then pass "disconnected OLED: exit 1, no ACK"
    else fail "disconnected OLED: exit $rc, '$err' (still connected?)"; fi
    sleep 2
    echo ">>> RECONNECT the OLED (VCC pin 17, GND pin 20, SDA pin 27, SCL pin 28)."
    ask "OLED reconnected?" || die "OLED not reconnected"
    UNPLUGGED=0
    sleep 1
    # Power-on reset leaves the display OFF (0xAE); nothing has been sent since, so a lit
    # panel here means the chip never lost power and the check below would prove nothing.
    if ask "Before any command: is the screen completely dark (EDGE gone)?"; then
        pass "power-on reset seen: panel dark after reconnecting"
    else
        fail "panel not dark after reconnecting: the chip kept power, not a real power cycle"
    fi
    if present; then pass "OLED answers again after power-up"
    else fail "nothing at $ADDR after power-up"; fi
    show edge "After the power cycle: EDGE is back, same as before?"
fi

pgrep -x oled_probe >/dev/null && fail "oled_probe still running after the checks"
echo "=== $failures failure(s)"
[[ $failures -eq 0 ]]
