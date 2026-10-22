#!/usr/bin/env bash
# Step 11 / 12-a acceptance: the Blue Pill's I2C target firmware (register map v1.0), from Jetson
# userspace with i2c-tools.
# Usage: bash scripts/verify_stm32_i2c.sh [--no-look] [--rounds N]
#
# No root needed (i2c group). Flash first: ~/.platformio/penv/bin/pio run -d firmware/stm32f103 -t upload
# Wiring: Blue Pill PB6 -> header pin 28 (SCL), PB7 -> pin 27 (SDA), GND -> a header GND pin;
# the bus (c240000.i2c) is the OLED's (0x3c); the OLED may stay connected or be unplugged.
# Checks: the bus scan (0x42 and the OLED's 0x3c), DEVICE_ID / FW / PROTOCOL_VERSION, writes the
# firmware must drop (read-only, unmapped, invalid LED value) each with its STATUS bit,
# STATUS write-1-to-clear, LED_CONTROL 1 / 0 with read back (a person looks at the PC13 LED
# unless --no-look), multi-byte reads and writes (auto-increment) and that reads never move the
# pointer, N rounds of mixed single- and multi-byte reads (a byte left over from the previous
# read, or a pointer moved by a read, would show here), then the unit tests against the board.
# The LED is switched off and STATUS cleared on exit.
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
trap 'i2cset -y "$BUS" $ADDR 0x20 0 2>/dev/null; i2cset -y "$BUS" $ADDR 0x30 0xff 2>/dev/null' EXIT

get() { i2cget -y "$BUS" $ADDR "$1" 2>&1; }
put() { i2cset -y "$BUS" $ADDR "$1" "$2" 2>&1; }
expect() {  # register, wanted value, label
    local got; got="$(get "$1")"
    if [[ $got == "$2" ]]; then pass "$3: reg $1 = $got"; else fail "$3: reg $1 = '$got', want $2"; fi
}
xfer() { i2ctransfer -y "$BUS" "$@" 2>&1; }
expect_xfer() {  # wanted bytes, label, i2ctransfer args...
    local want=$1 label=$2 got; shift 2
    got="$(xfer "$@")"
    if [[ $got == "$want" ]]; then pass "$label: $got"; else fail "$label: '$got', want $want"; fi
}
expect_status() {  # wanted STATUS, label; then clears STATUS
    expect 0x30 "$1" "STATUS after $2"
    put 0x30 0xff >/dev/null
}

echo "== bus scan (i2cdetect -y -r $BUS)"
scan="$(i2cdetect -y -r "$BUS" 2>/dev/null)"
echo "$scan"
has() { awk -v a="$1" 'NR > 1 { for (i = 2; i <= NF; i++) if ($i == a) f = 1 } END { exit !f }' <<<"$scan"; }
if has 42; then pass "STM32 answers at $ADDR"; else fail "nothing at $ADDR (flashed? PB6/PB7 and GND wired?)"; fi
# The STM32 steps do not need the OLED; when it is connected too, it must keep answering.
if has 3c; then pass "OLED still answers at 0x3c on the shared bus"; else echo "SKIP OLED not on i2c-$BUS (not needed for this step)"; fi

echo "== identification"
expect 0x00 0xed DEVICE_ID
expect 0x01 0x00 FW_MAJOR
expect 0x02 0x02 FW_MINOR
expect 0x03 0x10 "PROTOCOL_VERSION (1.0)"
expect 0x31 0x00 "WATCHDOG_STATUS (placeholder)"

echo "== STATUS"
# RESET (0x80) is set from power-on until someone clears it: informational only.
echo "INFO STATUS as found: $(get 0x30) (0x80 = not cleared since the board started)"
put 0x30 0xff >/dev/null
expect 0x30 0x00 "STATUS after writing 0xff (write-1-to-clear)"

echo "== writes the firmware must drop, each reported in STATUS"
put 0x00 0x55 >/dev/null
expect 0x00 0xed "DEVICE_ID after writing 0x55"
expect_status 0x01 "a read-only write (RO_WRITE)"
expect 0x10 0xff "unmapped register"
expect_status 0x00 "reading an unmapped register (not an error)"
put 0x10 0x55 >/dev/null
expect_status 0x02 "an unmapped write (UNMAPPED_WRITE)"
put 0x00 1 >/dev/null; put 0x20 9 >/dev/null
put 0x30 0x01 >/dev/null
expect_status 0x04 "two errors, then clearing only bit 0"

echo "== LED_CONTROL"
put 0x20 1 >/dev/null
expect 0x20 0x01 "LED_CONTROL = 1"
(( LOOK )) && check_ask "Is the Blue Pill's blue LED (PC13) ON"
put 0x20 2 >/dev/null
expect 0x20 0x01 "LED_CONTROL after the invalid value 2"
expect_status 0x04 "LED_CONTROL = 2 (BAD_VALUE)"
put 0x20 0 >/dev/null
expect 0x20 0x00 "LED_CONTROL = 0"
(( LOOK )) && check_ask "Is the LED OFF now"

echo "== auto-increment"
expect_xfer "0xed 0x00 0x02 0x10" "4-byte read from 0x00" w1@$ADDR 0x00 r4@$ADDR
expect_xfer "0x10 0xff" "read past the identification block" w1@$ADDR 0x03 r2@$ADDR
expect_xfer "0xff 0xed" "read wraps from 0xff to 0x00" w1@$ADDR 0xff r2@$ADDR
expect_xfer "0x00 0x02 0x10" "3-byte read from 0x01" w1@$ADDR 0x01 r3@$ADDR
expect_xfer "0x00 0x02" "read with no pointer write starts at the pointer again" r2@$ADDR
expect_xfer "0x01" "write LED_CONTROL = 1 and read it in one transaction" w2@$ADDR 0x20 0x01 r1@$ADDR
put 0x20 0 >/dev/null
xfer w3@$ADDR 0x1f 0x00 0x01 >/dev/null
expect 0x20 0x01 "LED_CONTROL after w3@ 0x1f 0x00 0x01"
expect_status 0x02 "a write crossing 0x1f (UNMAPPED_WRITE) into 0x20"
put 0x20 0 >/dev/null

echo "== $ROUNDS rounds of mixed reads (r4 from 0x00, 0x20, r2 from 0x30, 0x02, r1 with no pointer write; LED on)"
put 0x20 1 >/dev/null
bad=0; start=$(date +%s.%N)
for ((i = 0; i < ROUNDS; i++)); do
    [[ "$(xfer w1@$ADDR 0x00 r4@$ADDR)" == "0xed 0x00 0x02 0x10" ]] || bad=$((bad + 1))
    [[ "$(get 0x20)" == 0x01 ]] || bad=$((bad + 1))
    [[ "$(xfer w1@$ADDR 0x30 r2@$ADDR)" == "0x00 0x00" ]] || bad=$((bad + 1))
    [[ "$(get 0x02)" == 0x02 ]] || bad=$((bad + 1))
    [[ "$(xfer r1@$ADDR)" == 0x02 ]] || bad=$((bad + 1))  # pointer still 0x02
done
secs=$(awk -v s="$start" -v e="$(date +%s.%N)" 'BEGIN { printf "%.1f", e - s }')
if (( bad == 0 )); then pass "$((ROUNDS * 5)) transactions in $secs s, all correct"; else fail "$bad of $((ROUNDS * 5)) transactions wrong"; fi
put 0x20 0 >/dev/null
expect_status 0x00 "the rounds (nothing dropped)"

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
