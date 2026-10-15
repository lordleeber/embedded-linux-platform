#!/usr/bin/env bash
# Step 11 acceptance: the Blue Pill's I2C target firmware, from Jetson userspace with i2c-tools.
# Usage: bash scripts/verify_stm32_i2c.sh [--no-look] [--rounds N]
#
# No root needed (i2c group). Flash first: ~/.platformio/penv/bin/pio run -d firmware/stm32f103 -t upload
# Wiring: Blue Pill PB6 -> header pin 28 (SCL), PB7 -> pin 27 (SDA), GND -> a header GND pin;
# the bus (c240000.i2c) is the OLED's (0x3c); the OLED may stay connected or be unplugged.
# Checks: the bus scan (0x42 and the OLED's 0x3c), DEVICE_ID / FW version, a write to a
# read-only register, an unmapped register, LED_CONTROL 1 / 0 with read back (a person looks at
# the PC13 LED unless --no-look), an invalid LED value, a 3-byte read (no auto-increment),
# N rounds of alternating register reads (a byte left over from the previous read would show
# here), then the unit tests against the board. The LED is switched off on exit.
# Exit status: 0 = all checks passed, 1 = a check failed, 2 = environment/usage problem.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTROLLER=c240000.i2c
ADDR=0x42
LOOK=1
ROUNDS=100
ANSWER_TIMEOUT=120
failures=0

pass() { echo "PASS $*"; }
fail() { echo "FAIL $*"; failures=$((failures + 1)); }
die()  { echo "ERROR $*" >&2; exit 2; }
drain_tty() { while read -r -t 0.05 _ </dev/tty; do :; done; }
ask() {
    local ans=""
    drain_tty
    read -r -t "$ANSWER_TIMEOUT" -p ">>> $1 [y/n] " ans </dev/tty || echo
    [[ $ans == [yY]* ]]
}
check_ask() { if ask "$1"; then pass "$1"; else fail "person answered no to '$1'"; fi; }

while (( $# )); do
    case $1 in
        --no-look) LOOK=0 ;;
        --rounds) [[ ${2:-} =~ ^[0-9]+$ ]] || die "--rounds needs a number"; ROUNDS=$2; shift ;;
        *) die "usage: $0 [--no-look] [--rounds N]" ;;
    esac
    shift
done
for c in i2cdetect i2cget i2cset i2ctransfer; do
    command -v $c >/dev/null || die "$c missing (apt install i2c-tools)"
done
if (( LOOK )); then { true </dev/tty; } 2>/dev/null || die "needs a terminal for the y/n questions (or --no-look)"; fi

BUS="$(i2cdetect -l | awk -v c="$CONTROLLER" '$3 == c { sub("i2c-", "", $1); print $1 }')"
[[ -n "$BUS" ]] || die "no adapter named $CONTROLLER"
[[ -r /dev/i2c-$BUS && -w /dev/i2c-$BUS ]] || die "cannot open /dev/i2c-$BUS (add yourself to the i2c group)"
pass "$CONTROLLER is i2c-$BUS"
trap 'i2cset -y "$BUS" $ADDR 0x20 0 2>/dev/null' EXIT

get() { i2cget -y "$BUS" $ADDR "$1" 2>&1; }
put() { i2cset -y "$BUS" $ADDR "$1" "$2" 2>&1; }
expect() {  # register, wanted value, label
    local got; got="$(get "$1")"
    if [[ $got == "$2" ]]; then pass "$3: reg $1 = $got"; else fail "$3: reg $1 = '$got', want $2"; fi
}

echo "== bus scan (i2cdetect -y -r $BUS)"
scan="$(i2cdetect -y -r "$BUS" 2>/dev/null)"
echo "$scan"
has() { awk -v a="$1" 'NR > 1 { for (i = 2; i <= NF; i++) if ($i == a) f = 1 } END { exit !f }' <<<"$scan"; }
if has 42; then pass "STM32 answers at $ADDR"; else fail "nothing at $ADDR (flashed? PB6/PB7 and GND wired?)"; fi
# Step 11 does not need the OLED; when it is connected too, it must keep answering.
if has 3c; then pass "OLED still answers at 0x3c on the shared bus"; else echo "SKIP OLED not on i2c-$BUS (not needed for Step 11)"; fi

echo "== identification"
expect 0x00 0xed DEVICE_ID
expect 0x01 0x00 FW_MAJOR
expect 0x02 0x01 FW_MINOR

echo "== writes the firmware must drop"
put 0x00 0x55 >/dev/null
expect 0x00 0xed "DEVICE_ID after writing 0x55"
expect 0x10 0xff "unmapped register"

echo "== LED_CONTROL"
put 0x20 1 >/dev/null
expect 0x20 0x01 "LED_CONTROL = 1"
(( LOOK )) && check_ask "Is the Blue Pill's green LED (PC13) ON"
put 0x20 2 >/dev/null
expect 0x20 0x01 "LED_CONTROL after the invalid value 2"
put 0x20 0 >/dev/null
expect 0x20 0x00 "LED_CONTROL = 0"
(( LOOK )) && check_ask "Is the LED OFF now"

echo "== 3-byte read of FW_MINOR (no auto-increment)"
out="$(i2ctransfer -y "$BUS" w1@$ADDR 0x02 r3@$ADDR 2>&1)"
if [[ $out == "0x01 0x01 0x01" ]]; then pass "i2ctransfer: $out"; else fail "i2ctransfer: '$out', want 0x01 0x01 0x01"; fi

echo "== $ROUNDS rounds of alternating reads (0x00 0x01 0x02 0x20, LED on)"
put 0x20 1 >/dev/null
bad=0; start=$(date +%s.%N)
for ((i = 0; i < ROUNDS; i++)); do
    for pair in 0x00:0xed 0x01:0x00 0x02:0x01 0x20:0x01; do
        [[ "$(get "${pair%:*}")" == "${pair#*:}" ]] || bad=$((bad + 1))
    done
done
secs=$(awk -v s="$start" -v e="$(date +%s.%N)" 'BEGIN { printf "%.1f", e - s }')
if (( bad == 0 )); then pass "$((ROUNDS * 4)) reads in $secs s, all correct"; else fail "$bad of $((ROUNDS * 4)) reads wrong"; fi
put 0x20 0 >/dev/null

echo "== unit tests against the board"
tmp="$(mktemp)"
if EDGE_STM32_HW=1 EDGE_STM32_BUS="$BUS" python3 -m unittest discover -s "$REPO/tests" -p test_stm32_i2c_target.py >"$tmp" 2>&1; then
    pass "test_stm32_i2c_target.py ($(tail -1 "$tmp"))"
else
    cat "$tmp"
    fail "test_stm32_i2c_target.py"
fi
rm -f "$tmp"

echo "=== $failures failure(s)"
(( failures == 0 ))
