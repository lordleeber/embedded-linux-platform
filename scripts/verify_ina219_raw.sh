#!/usr/bin/env bash
# Step 6-b acceptance: bring up the INA219 from userspace with i2c-tools and build/ina219_raw.
# Usage: bash scripts/verify_ina219_raw.sh [--no-unplug]
#
# No root needed: the user must be in the i2c group (/dev/i2c-7 is root:i2c 0660).
# Checks: the bus number behind c250000.i2c (header pins 3/5), the bus scan, i2cget of all
# six registers (SMBus words come back LSB first), an i2cset round trip that writes back the
# Calibration value already there, the tool against i2cget, the unit tests against the real
# chip, an absent address as an I/O error, then (unless --no-unplug) a person unplugs the
# UPS's DC adapter and the current must become non-zero.
# Exit status: 0 = all checks passed, 1 = a check failed, 2 = environment/usage problem.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOOL="$REPO/build/ina219_raw"
CONTROLLER=c250000.i2c
ADDR=0x41
UNPLUG=1
WINDOW=20       # seconds sampled with the adapter unplugged
failures=0

pass() { echo "PASS $*"; }
fail() { echo "FAIL $*"; failures=$((failures + 1)); }
die()  { echo "ERROR $*" >&2; exit 2; }

for arg in "$@"; do
    case $arg in
        --no-unplug) UNPLUG=0 ;;
        *) die "usage: $0 [--no-unplug]" ;;
    esac
done
for c in i2cdetect i2cget i2cset; do
    command -v $c >/dev/null || die "$c missing (apt install i2c-tools)"
done
cmake -S "$REPO" -B "$REPO/build" >/dev/null && cmake --build "$REPO/build" --target ina219_raw >/dev/null \
    || die "build of ina219_raw failed"
tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT
UNPLUGGED=0
on_int() {
    [[ $UNPLUGGED -eq 1 ]] && echo ">>> Interrupted: PLUG the DC adapter back in (the Jetson is on battery)."
    exit 2
}
trap on_int INT TERM

swap16() { printf '0x%04X' $(( ($1 & 0xFF) << 8 | $1 >> 8 )); }
tool() { timeout -k 1 5 "$TOOL" --bus "$BUS" "$@"; }
# raw value of register $2 (0..5) from the tool output in $1
tool_reg() { awk -v r="$(printf '0x%02X' "$2")" '$1 == r { print $3 }' <<<"$1"; }

echo "== which bus is $CONTROLLER (i2cdetect -l)"
i2cdetect -l
BUS="$(i2cdetect -l | awk -v c="$CONTROLLER" '$3 == c { sub("i2c-", "", $1); print $1 }')"
[[ -n "$BUS" ]] || die "no adapter named $CONTROLLER"
[[ -r /dev/i2c-$BUS && -w /dev/i2c-$BUS ]] || die "cannot open /dev/i2c-$BUS (add yourself to the i2c group)"
pass "$CONTROLLER is i2c-$BUS"

echo "== bus scan (i2cdetect -y -r $BUS)"
scan="$(i2cdetect -y -r "$BUS" 2>/dev/null)"
echo "$scan"
if awk '$1 == "40:" { for (i = 2; i <= NF; i++) if ($i == "41") f = 1 } END { exit !f }' <<<"$scan"; then
    pass "INA219 answers at $ADDR"
else
    fail "nothing at $ADDR on i2c-$BUS (check the UPS connection)"
fi

echo "== i2cget, word mode (SMBus sends the low byte first; swapped = the chip's value)"
declare -A word
for reg in 0 1 2 3 4 5; do
    if ! word[$reg]="$(i2cget -y "$BUS" $ADDR $reg w 2>&1)"; then
        fail "i2cget reg $reg: ${word[$reg]}"
        unset 'word[$reg]'
        continue
    fi
    echo "  reg 0x0$reg  i2cget ${word[$reg]}  swapped $(swap16 "${word[$reg]}")"
done

echo "== i2cset round trip: write Calibration back with the value just read"
cal="${word[5]:-}"
if [[ $cal == 0x* ]] && i2cset -y "$BUS" $ADDR 0x05 "$cal" w && [[ "$(i2cget -y "$BUS" $ADDR 0x05 w)" == "$cal" ]]; then
    pass "Calibration still $(swap16 "$cal") after i2cset"
else
    fail "i2cset / i2cget round trip on Calibration"
fi

echo "== build/ina219_raw"
out="$(tool)"; rc=$?
echo "$out"
if [[ $rc -eq 0 ]]; then
    for reg in 0 5; do
        got="$(tool_reg "$out" $reg)"; want="$(swap16 "${word[$reg]:-0}")"
        if [[ "$got" == "$want" ]]; then pass "reg 0x0$reg: tool $got = i2cget swapped"
        else fail "reg 0x0$reg: tool $got, i2cget swapped $want"; fi
    done
    v="$(awk '/^bus voltage:/ { print $3 }' <<<"$out")"
    if awk -v v="$v" 'BEGIN { exit !(v >= 9.0 && v <= 12.8) }'; then
        pass "bus voltage $v V (accepted 9.0 .. 12.8 V; a 3S pack is 9.0 .. 12.6 V)"
    else
        fail "bus voltage '$v' not plausible"
    fi
else
    fail "ina219_raw exit $rc"
fi

echo "== unit tests against the real chip"
if EDGE_INA219_HW=1 EDGE_INA219_BUS="$BUS" python3 -m unittest discover -s "$REPO/tests" -p test_ina219_raw.py >"$tmpdir/ut" 2>&1; then
    pass "test_ina219_raw.py ($(tail -1 "$tmpdir/ut"))"
else
    cat "$tmpdir/ut"
    fail "test_ina219_raw.py"
fi

echo "== absent address (what an unplugged module looks like)"
err="$(tool --addr 0x45 2>&1 >/dev/null)"; rc=$?
echo "  $err"
if [[ $rc -eq 1 && $err == *"Remote I/O error"* ]]; then
    pass "0x45: exit 1, Remote I/O error"
else
    fail "0x45: exit $rc, '$err'"
fi

if [[ $UNPLUG -eq 1 ]]; then
    echo
    echo ">>> UNPLUG the UPS's DC adapter now (the battery takes over the Jetson). Sampling ${WINDOW} s ..."
    UNPLUGGED=1
    max=0
    for ((i = 0; i < WINDOW / 2; i++)); do
        sleep 2
        snap="$(tool)" || { fail "ina219_raw failed on battery (error above)"; continue; }
        echo "    $(grep -E '^(bus voltage|current)' <<<"$snap" | awk '{ printf "%s %s %s %s  ", $1, $2, $3, $4 }')"
        ma="$(awk '/^current \(shunt\):/ { print $3 }' <<<"$snap")"
        max="$(awk -v a="$ma" -v m="$max" 'BEGIN { b = a < 0 ? -a : a; c = m < 0 ? -m : m; print (b > c ? a : m) }')"
    done
    if awk -v m="$max" 'BEGIN { exit !(m * m >= 50 * 50) }'; then
        pass "on battery the current is non-zero: $max mA (sign = direction through the shunt)"
    else
        fail "current stayed ~0 on battery ($max mA)"
    fi
    echo ">>> PLUG the DC adapter back in now."
    UNPLUGGED=0
fi

pgrep -x ina219_raw >/dev/null && fail "ina219_raw still running after the checks"
echo "=== $failures failure(s)"
[[ $failures -eq 0 ]]
