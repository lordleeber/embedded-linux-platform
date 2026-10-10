#!/usr/bin/env bash
# Step 6-a acceptance: the Waveshare UPS Power Module (C) sample reads the on-board INA219.
# Usage: bash scripts/verify_ina219_sample.sh [--no-unplug]
#
# No root needed: the user must be in the i2c group (/dev/i2c-7 is root:i2c 0660).
# The UPS powers the Jetson; its INA219 sits on i2c-7 (header pins 3/5) at 0x41.
# Checks: the chip answers on the bus scan, the unit tests against the real chip pass, the
# sample prints a plausible 3S battery reading, then (unless --no-unplug) a person unplugs the
# UPS's DC adapter so the battery carries the Jetson and the current must become non-zero,
# and plugs it back in. Note: the sample WRITES the Calibration and Config registers on start.
# Exit status: 0 = all checks passed, 1 = a check failed, 2 = environment/usage problem.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SAMPLE="$REPO/third_party/waveshare_ups_c/ina219.py"
BUS=7
ADDR=41
UNPLUG=1
WINDOW=20       # seconds sampled per adapter state (one block every 2 s)
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
[[ -r /dev/i2c-$BUS && -w /dev/i2c-$BUS ]] || die "cannot open /dev/i2c-$BUS (add yourself to the i2c group)"
command -v i2cdetect >/dev/null || die "i2cdetect missing (apt install i2c-tools)"
python3 -c 'import smbus' 2>/dev/null || die "python3-smbus missing (apt install python3-smbus)"
[[ -f "$SAMPLE" ]] || die "$SAMPLE missing"

tmpdir="$(mktemp -d)"
cleanup() {
    pkill -f "python3 -u $SAMPLE" 2>/dev/null
    rm -rf "$tmpdir"
}
trap cleanup EXIT
trap 'exit 2' INT TERM

# Run the sample for $1 seconds; output in $tmpdir/$2. SIGINT is what Ctrl-C would send.
sample() {
    timeout -s INT -k 2 "$1" python3 -u "$SAMPLE" >"$tmpdir/$2" 2>/dev/null
}
# One line per block: volts amps watts percent
blocks() { awk '/^Load Voltage/ {v=$3} /^Current/ {a=$2} /^Power/ {w=$2} /^Percentage/ {print v, a, w, $2}' "$tmpdir/$1"; }
max_abs_current() { blocks "$1" | awk '{ a = $2 < 0 ? -$2 : $2; if (a > m) { m = a; s = $2 } } END { printf "%.6f", s + 0 }'; }

echo "== bus scan (i2cdetect -y -r $BUS)"
scan="$(i2cdetect -y -r "$BUS" 2>/dev/null)"
echo "$scan"
if awk -v a="$ADDR" '$1 == "40:" { for (i = 2; i <= NF; i++) if ($i == a) found = 1 } END { exit !found }' <<<"$scan"; then
    pass "INA219 answers at 0x$ADDR on i2c-$BUS"
else
    fail "nothing at 0x$ADDR on i2c-$BUS (check the UPS connection)"
fi

echo "== unit tests against the real chip"
if EDGE_INA219_HW=1 python3 -m unittest discover -s "$REPO/tests" -p test_ina219_sample.py >"$tmpdir/ut" 2>&1; then
    pass "test_ina219_sample.py ($(tail -1 "$tmpdir/ut"))"
else
    cat "$tmpdir/ut"
    fail "test_ina219_sample.py"
fi

echo "== sample output (5 s)"
sample 5 idle
cat "$tmpdir/idle"
read -r v a w p < <(blocks idle | head -1)
if [[ -n "${v:-}" ]] && awk -v v="$v" 'BEGIN { exit !(v >= 9.0 && v <= 12.8) }'; then
    pass "battery voltage $v V, $p % (3S pack: 9.0 .. 12.6 V)"
else
    fail "no plausible voltage in the sample output"
fi
echo "current on adapter: $(max_abs_current idle) A"

if [[ $UNPLUG -eq 1 ]]; then
    echo
    echo ">>> UNPLUG the UPS's DC adapter now (the battery takes over the Jetson). Sampling ${WINDOW} s ..."
    sample "$WINDOW" battery
    blocks battery | sed 's/^/    V A W % = /'
    i="$(max_abs_current battery)"
    if awk -v i="$i" 'BEGIN { exit !(i * i >= 0.05 * 0.05) }'; then
        pass "on battery the current is non-zero: $i A (sign = direction through the shunt)"
    else
        fail "current stayed ~0 on battery ($i A): adapter still plugged in, or the shunt is not in the battery path"
    fi
    echo
    echo ">>> PLUG the DC adapter back in now. Sampling ${WINDOW} s ..."
    sample "$WINDOW" charging
    blocks charging | sed 's/^/    V A W % = /'
    echo "current back on adapter (recorded, not judged): $(max_abs_current charging) A"
fi

pgrep -f "python3 -u $SAMPLE" >/dev/null && fail "sample still running after the checks"
echo "=== $failures failure(s)"
[[ $failures -eq 0 ]]
