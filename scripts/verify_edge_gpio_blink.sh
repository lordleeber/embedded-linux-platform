#!/usr/bin/env bash
# Step 4-a acceptance: drive header pin 29 from userspace (edge_gpio_blink) with
# the pad closed and then opened, and leave the board as it was found.
# Usage: sudo bash scripts/verify_edge_gpio_blink.sh
#
#   pad closed (JP6 boot state): output register reads hi while the pad stays
#                                tristated -> LED must stay dark for 5 cycles
#   pad opened (pad_pin29.py):   tristate=0, register follows hi/lo, LED blinks
#                                5 times, hardware unittests pass, line released
# Watch the LED: the script cannot see the pin voltage, only the register.
# Exit status: 0 = all checks passed, 1 = a check failed, 2 = environment/usage problem.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="$REPO/build"
CLI="$BUILD_DIR/edge_gpio_blink"
PAD="python3 $REPO/scripts/pad_pin29.py"
CHIP=gpiochip0
LINE=105            # PQ.05 = header pin 29
failures=0
bg=""

pass() { echo "PASS $*"; }
fail() { echo "FAIL $*"; failures=$((failures + 1)); }
die()  { echo "ERROR $*" >&2; exit 2; }

[[ $# -eq 0 ]] || die "usage: $0"
[[ $EUID -eq 0 ]] || die "run as root: sudo bash scripts/verify_edge_gpio_blink.sh"
command -v gpioinfo >/dev/null || die "gpioinfo missing (apt install gpiod)"
BUILD_USER="${SUDO_USER:-root}"

line_info() { gpioinfo "$CHIP" | awk -v l="$LINE:" '$1 == "line" && $2 == l { $1 = $2 = ""; print }'; }
# Raw output register level from gpiolib debugfs ("hi"/"lo"); only listed while the line is requested.
pin_level() { awk '/\(PQ\.05/ { for (i = 1; i <= NF; i++) if ($i == "hi" || $i == "lo") { print $i; exit } }' /sys/kernel/debug/gpio; }
# pinconf-groups is multi-line: "115 (soc_gpio32_pq5):" then one indented line per config.
pinconf() {
    awk '/^[0-9]+ \(/ { show = /\(soc_gpio[0-9]*_pq5\)/ } show' \
        /sys/kernel/debug/pinctrl/*/pinconf-groups 2>/dev/null | tr -s ' \t\n' ' '
}
pad_low_byte() { $PAD show | awk '/^before:/ { print substr($2, 9, 2) }'; }

mountpoint -q /sys/kernel/debug || mount -t debugfs none /sys/kernel/debug || die "cannot mount debugfs"
[[ "$(line_info)" == *unused* ]] || die "line $LINE in use: $(line_info) (rmmod edge_gpio?)"
orig="$(pad_low_byte)"
case $orig in
    58) orig_action=close ;;
    00) orig_action=open ;;
    *) die "pad register low byte '$orig' is not 58/00; not touching it" ;;
esac
echo "--- pad at start: $($PAD show | sed 's/^before: //')"

cleanup() {
    [[ -n $bg ]] && kill "$bg" 2>/dev/null && wait "$bg" 2>/dev/null
    $PAD "$orig_action" >/dev/null || echo "WARN could not restore pad ($orig_action)" >&2
}
trap cleanup EXIT
trap 'exit 2' INT TERM

if timeout 300 sudo -u "$BUILD_USER" sh -c "cmake -S '$REPO' -B '$BUILD_DIR' >/dev/null && cmake --build '$BUILD_DIR' --target edge_gpio_blink >/dev/null"; then
    pass "build edge_gpio_blink (CMake)"
else
    fail "build edge_gpio_blink (CMake)"; exit 1
fi

# One full run (5 x 500 ms on / 500 ms off) in the background; sample the
# register in the middle of the first high half and the first low half.
sample_run() {
    echo "    watch the LED on pin 29 for 5 s: $1"
    sudo -u "$BUILD_USER" "$CLI" >/dev/null &
    bg=$!
    local deadline=$((SECONDS + 3))
    until [[ "$(line_info)" == *'"edge_gpio_blink"'* ]] || ((SECONDS > deadline)) || ! kill -0 "$bg" 2>/dev/null; do
        sleep 0.02
    done
    sleep 0.2; high="$(pin_level)"
    sleep 0.5; low="$(pin_level)"
    wait "$bg"; status=$?; bg=""
}

echo "--- phase 1: pad closed (boot state)"
$PAD close >/dev/null || fail "pad close"
conf="$(pinconf)"; echo "    $conf"
if [[ $conf == *tristate=1* ]]; then pass "pad tristated"; else fail "pad not tristated after close"; fi
sample_run "it should stay DARK"
if [[ $status -eq 0 && $high == hi && $low == lo ]]; then
    pass "register goes hi/lo although the pad is tristated"
else
    fail "closed pad run: exit $status, levels '$high'/'$low'"
fi

echo "--- phase 2: pad opened"
$PAD open | sed 's/^/    /' || fail "pad open"
conf="$(pinconf)"; echo "    $conf"
if [[ $conf == *tristate=0* && $conf == *enable-input=0* ]]; then pass "pad drives (tristate=0, input=0)"; else fail "pad not open"; fi
sample_run "it should BLINK 5 times (the unittests after it blink about 12 more)"
if [[ $status -eq 0 && $high == hi && $low == lo ]]; then pass "register goes hi then lo with the pad open"; else fail "open pad run: exit $status, levels '$high'/'$low'"; fi
log="$(mktemp)"   # root writes it: never a guessable /tmp name
if (cd "$REPO" && timeout 60 sudo -u "$BUILD_USER" env EDGE_GPIO_HW=1 \
        python3 -m unittest discover -s tests -p test_edge_gpio_blink.py >"$log" 2>&1); then
    pass "edge_gpio_blink unittests (hardware) as $BUILD_USER"
else
    fail "edge_gpio_blink unittests as $BUILD_USER"; cat "$log"
fi
rm -f "$log"

if [[ "$(line_info)" == *unused* ]]; then pass "line $LINE released"; else fail "line $LINE still held: $(line_info)"; fi
trap - EXIT
cleanup
if [[ "$(pad_low_byte)" == "$orig" ]]; then pass "pad restored to low byte 0x$orig"; else fail "pad not restored"; fi
echo "=== $failures failure(s)"
[[ $failures -eq 0 ]]
