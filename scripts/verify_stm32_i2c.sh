#!/usr/bin/env bash
# Step 11 / 12-a / 12-b acceptance: the Blue Pill's I2C target firmware (register map v1.1), from
# Jetson userspace with i2c-tools.
# Usage: bash scripts/verify_stm32_i2c.sh [--no-look] [--no-touch] [--rounds N]
#
# No root needed (i2c group). Flash first: ~/.platformio/penv/bin/pio run -d firmware/stm32f103 -t upload
# Wiring: Blue Pill PB6 -> header pin 28 (SCL), PB7 -> pin 27 (SDA), GND -> a header GND pin;
# the bus (c240000.i2c) is the OLED's (0x3c); the OLED may stay connected or be unplugged.
# Step 12-b inputs: two 330-ohm resistors from 3.3 to GND on the breadboard (their joint is the
# "midpoint"), a wire from A0 (PA0) that a person moves between GND, the midpoint and 3.3, and
# a button from A1 (PA1) to GND. Without --no-touch the script asks for each move and press.
# Checks: the bus scan (0x42 and the OLED's 0x3c), DEVICE_ID / FW / PROTOCOL_VERSION, writes the
# firmware must drop (read-only, unmapped, invalid LED value) each with its STATUS bit,
# STATUS write-1-to-clear, LED_CONTROL 1 / 0 with read back (a person looks at the PC13 LED
# unless --no-look), multi-byte reads and writes (auto-increment) and that reads never move the
# pointer, N rounds of mixed single- and multi-byte reads (a byte left over from the previous
# read, or a pointer moved by a read, would show here), then the unit tests against the board.
# Then the inputs: the ADC at GND / 3.3 V / midpoint (a burst of 2-byte reads at each), then
# with the A0 wire pulled out so A0 floats across 0x800: ADC_LOW and ADC_HIGH from two different
# conversions would be about 256 counts off (read from 0x0f so ADC_HIGH is the 3rd byte, the
# first one the F103 fetches after a byte has gone out); and the button held, released and
# pressed several times (the counter must see each press exactly once). --no-touch keeps only the checks that need no hands. The wire should end at the midpoint.
# The LED is switched off and STATUS cleared on exit. Clearing writes 0xff, which also clears
# STATUS's RESET bit (0x80): on purpose, the script resets the board's state at both ends, and
# its value at the start is printed first (INFO line).
# Exit status: 0 = all checks passed, 1 = a check failed, 2 = environment/usage problem.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTROLLER=c240000.i2c
ADDR=0x42
LOOK=1
TOUCH=1
ROUNDS=100
ADC_N=200
# Limits for 12-bit readings (0..4095, VDDA = 3.3 V). Measured in Step 12-b, docs/baseline.md.
ADC_SPREAD_MAX=40   # measured spread 10-19 over 300 reads; same value as the unit test
ADC_GND_MAX=100     # measured 24-37
ADC_VCC_MIN=3995    # measured 4085-4095
ADC_MID_MIN=1940    # 2048 with two 5 % resistors: 1945-2150; measured mean 2068
ADC_MID_MAX=2160
TEAR_N=1000         # reads with A0 floating
TEAR_LIMIT=180      # floating noise measured within 100 of the median; a torn read is ~256 off
PRESS_COUNT=5
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
wait_enter() {
    drain_tty
    read -r -t "$ANSWER_TIMEOUT" -p ">>> $1, then press Enter " _ </dev/tty || { echo; die "no answer in ${ANSWER_TIMEOUT} s"; }
}

while (( $# )); do
    case $1 in
        --no-look) LOOK=0 ;;
        --no-touch) TOUCH=0 ;;
        --rounds) [[ ${2:-} =~ ^[0-9]+$ ]] || die "--rounds needs a number"; ROUNDS=$2; shift ;;
        *) die "usage: $0 [--no-look] [--no-touch] [--rounds N]" ;;
    esac
    shift
done
for c in i2cdetect i2cget i2cset i2ctransfer; do
    command -v $c >/dev/null || die "$c missing (apt install i2c-tools)"
done
if (( LOOK || TOUCH )); then { true </dev/tty; } 2>/dev/null || die "needs a terminal for the questions (or --no-look --no-touch)"; fi

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
expect 0x02 0x03 FW_MINOR
expect 0x03 0x11 "PROTOCOL_VERSION (1.1)"
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
expect 0x14 0xff "unmapped register"
expect_status 0x00 "reading an unmapped register (not an error)"
put 0x14 0x55 >/dev/null
expect_status 0x02 "an unmapped write (UNMAPPED_WRITE)"
put 0x10 0x55 >/dev/null
expect_status 0x01 "a write to ADC_LOW (RO_WRITE)"
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
expect_xfer "0xed 0x00 0x03 0x11" "4-byte read from 0x00" w1@$ADDR 0x00 r4@$ADDR
expect_xfer "0x11 0xff" "read past the identification block" w1@$ADDR 0x03 r2@$ADDR
expect_xfer "0xff 0xed" "read wraps from 0xff to 0x00" w1@$ADDR 0xff r2@$ADDR
expect_xfer "0x00 0x03 0x11" "3-byte read from 0x01" w1@$ADDR 0x01 r3@$ADDR
expect_xfer "0x00 0x03" "read with no pointer write starts at the pointer again" r2@$ADDR
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
    [[ "$(xfer w1@$ADDR 0x00 r4@$ADDR)" == "0xed 0x00 0x03 0x11" ]] || bad=$((bad + 1))
    [[ "$(get 0x20)" == 0x01 ]] || bad=$((bad + 1))
    [[ "$(xfer w1@$ADDR 0x30 r2@$ADDR)" == "0x00 0x00" ]] || bad=$((bad + 1))
    [[ "$(get 0x02)" == 0x03 ]] || bad=$((bad + 1))
    [[ "$(xfer r1@$ADDR)" == 0x03 ]] || bad=$((bad + 1))  # pointer still 0x02
done
secs=$(awk -v s="$start" -v e="$(date +%s.%N)" 'BEGIN { printf "%.1f", e - s }')
if (( bad == 0 )); then pass "$((ROUNDS * 5)) transactions in $secs s, all correct"; else fail "$bad of $((ROUNDS * 5)) transactions wrong"; fi
put 0x20 0 >/dev/null
expect_status 0x00 "the rounds (nothing dropped)"

echo "== ADC (A0 = PA0)"
adc_burst() {  # prints "min max mean" of ADC_N two-byte reads of ADC_LOW / ADC_HIGH
    local i out lo hi v min=4096 max=-1 sum=0
    for ((i = 0; i < ADC_N; i++)); do
        out="$(xfer w1@$ADDR 0x10 r2@$ADDR)" || { echo "error: $out"; return 1; }
        read -r lo hi <<<"$out"
        v=$(( (hi << 8) | lo ))
        (( v < min )) && min=$v
        (( v > max )) && max=$v
        sum=$((sum + v))
    done
    echo "$min $max $((sum / ADC_N))"
}
check_adc() {  # label, then extra checks on the same burst, each as "min|max|mean" OP N
    local label=$1 stats min max mean
    shift
    stats="$(adc_burst)" || { fail "ADC $label: $stats"; return; }
    read -r min max mean <<<"$stats"
    echo "INFO ADC $label: min $min max $max mean $mean ($ADC_N reads)"
    if (( max - min <= ADC_SPREAD_MAX )); then pass "ADC $label: spread $((max - min)) <= $ADC_SPREAD_MAX"
    else fail "ADC $label: spread $((max - min)) > $ADC_SPREAD_MAX (bytes from two conversions?)"; fi
    while (( $# >= 3 )); do
        if (( ${!1} $2 $3 )); then pass "ADC $label: $1 $2 $3"; else fail "ADC $label: $1 = ${!1}, want $2 $3"; fi
        shift 3
    done
}
check_tearing() {  # A0 floating: no read may be a LOW / HIGH pair from two conversions
    local i out lo hi v d med vals=() below=0 above=0 far=0 worst=0
    for ((i = 0; i < TEAR_N; i++)); do
        out="$(xfer w1@$ADDR 0x0f r3@$ADDR)" || { fail "ADC floating: $out"; return; }
        read -r _ lo hi <<<"$out"
        vals+=($(( (hi << 8) | lo )))
    done
    med=$(printf '%s\n' "${vals[@]}" | sort -n | sed -n "$((TEAR_N / 2 + 1))p")
    for v in "${vals[@]}"; do
        if (( v < 0x800 )); then below=$((below + 1)); else above=$((above + 1)); fi
        d=$(( v > med ? v - med : med - v ))
        (( d > worst )) && worst=$d
        (( d > TEAR_LIMIT )) && far=$((far + 1))
    done
    echo "INFO ADC floating: median $med, $below reads below 0x800, $above at or above, farthest $worst from the median ($TEAR_N reads)"
    if (( below == 0 || above == 0 )); then
        fail "ADC floating: never crossed 0x800, tearing not checked (A0 wire out of the breadboard?)"
    elif (( far == 0 )); then pass "ADC floating: every read within $TEAR_LIMIT of the median (LOW and HIGH from one conversion)"
    else fail "ADC floating: $far of $TEAR_N reads more than $TEAR_LIMIT from the median (bytes from two conversions)"; fi
}
if (( TOUCH )); then
    wait_enter "Move the A0 wire to GND"
    check_adc GND max "<=" "$ADC_GND_MAX"
    wait_enter "Move the A0 wire to 3.3"
    check_adc 3.3V min ">=" "$ADC_VCC_MIN"
    wait_enter "Pull the A0 wire's other end out of the breadboard so A0 floats (touch nothing)"
    check_tearing
    wait_enter "Move the A0 wire to the midpoint between the two 330-ohm resistors"
    check_adc midpoint mean ">=" "$ADC_MID_MIN" mean "<=" "$ADC_MID_MAX"
else
    check_adc "as wired"
fi

echo "== button (A1 = PA1)"
if (( TOUCH )); then
    before=$(( $(get 0x13) ))
    wait_enter "Press and HOLD the button"
    expect 0x12 0x01 "BUTTON_STATE while held"
    wait_enter "Release the button"
    expect 0x12 0x00 "BUTTON_STATE released"
    after=$(( $(get 0x13) ))
    if (( (after - before) % 256 == 1 )); then pass "BUTTON_PRESSES +1 for one press ($before -> $after)"
    else fail "BUTTON_PRESSES $before -> $after for one press"; fi
    before=$after
    wait_enter "Press the button $PRESS_COUNT times (normal presses, not too fast)"
    after=$(( $(get 0x13) ))
    if (( (after - before + 256) % 256 == PRESS_COUNT )); then pass "BUTTON_PRESSES +$PRESS_COUNT ($before -> $after): no bounce counted"
    else fail "BUTTON_PRESSES $before -> $after, want +$PRESS_COUNT"; fi
else
    expect 0x12 0x00 "BUTTON_STATE (nobody pressing)"
fi
expect_status 0x00 "the input checks (nothing dropped)"

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
