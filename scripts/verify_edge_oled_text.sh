#!/usr/bin/env bash
# Step 10-b acceptance: text on the SSD1306 OLED through edge_oled.ko (/dev/edge_oled).
# Usage: sudo bash scripts/verify_edge_oled_text.sh [--no-unplug]
#
# Needs this boot's overlay with the oled@3c node (Step 10-a) and a person at the board who
# answers y/n for what the panel shows (the SSD1306 cannot be read back over I2C).
#   1. the font vectors (apps/oled_text.h) pass
#   2. the font sheet and phase04's strings read the right way round, one text line per page
#   3. a line longer than the panel is cut at the right edge, an unsupported character is
#      a box, and edge_oled_ctl says so on stderr
#   4. five refreshes in a row do not blink the panel to black
#   5. (unless --no-unplug) Step 10-a's carry-over: all four wires off and back on with no
#      write in between; the panel is dark (power-on reset), and the next write alone must
#      bring the text up, although every message of it is ACKed.
# Exit status: 0 = all checks passed, 1 = a check failed, 2 = environment/usage problem.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MOD_DIR="$REPO/kernel/edge_oled"
KO="$MOD_DIR/edge_oled.ko"
CTL="$REPO/build/edge_oled_ctl"
DRV=/sys/bus/i2c/drivers/edge_oled
NODE=/proc/device-tree/bus@0/i2c@c240000/oled@3c
UNPLUG=1
ANSWER_TIMEOUT=300
failures=0

pass() { echo "PASS $*"; }
fail() { echo "FAIL $*"; failures=$((failures + 1)); }
die()  { echo "ERROR $*" >&2; exit 2; }

case "${1:-}" in
    "") ;;
    --no-unplug) UNPLUG=0; shift ;;
    *) die "usage: $0 [--no-unplug]" ;;
esac
[[ $# -eq 0 ]] || die "usage: $0 [--no-unplug]"
[[ $EUID -eq 0 ]] || die "run as root: sudo bash scripts/verify_edge_oled_text.sh"
command -v i2cdetect >/dev/null || die "i2cdetect missing (apt install i2c-tools)"
# /dev/tty is mode 666 even without a controlling terminal; only opening it tells.
{ : </dev/tty; } 2>/dev/null || die "needs a terminal: a person answers what the OLED shows"
[[ -e $NODE ]] || die "no $NODE in this boot: install the Step 10-a overlay and reboot"
BUILD_USER="${SUDO_USER:-root}"

BUS="$(i2cdetect -l | awk '$3 == "c240000.i2c" { sub("i2c-", "", $1); print $1 }')"
[[ -n $BUS ]] || die "no c240000.i2c adapter in i2cdetect -l"
CLIENT=/sys/bus/i2c/devices/$BUS-003c

is_loaded() { grep -q '^edge_oled ' /proc/modules; }
# Checked before the EXIT trap exists, so a module the user loaded is left alone.
is_loaded && die "edge_oled already loaded; rmmod edge_oled first"

UNPLUGGED=0
cleanup() {
    if is_loaded; then rmmod edge_oled || echo "WARN cleanup rmmod failed" >&2; fi
}
trap cleanup EXIT
trap '[[ $UNPLUGGED -eq 1 ]] && echo ">>> Interrupted: reconnect the OLED."; exit 2' INT TERM

ctl() { timeout -k 1 10 "$CTL" "$@"; }
# ask "question": y -> 0, n -> 1; no answer within the timeout counts as n.
ask() {
    local ans=""
    read -r -t "$ANSWER_TIMEOUT" -p ">>> $1 [y/n] " ans </dev/tty || echo
    [[ $ans == [yY]* ]]
}
wait_enter() { read -r -t "$ANSWER_TIMEOUT" -p ">>> $1, then press Enter " _ </dev/tty || echo; }
# show "QUESTION" ARGS...: draw with edge_oled_ctl, then a person confirms the picture
show() {
    local q="$1" out rc; shift
    out="$(ctl "$@" 2>&1)"; rc=$?
    [[ -n $out ]] && echo "    $out"
    if [[ $rc -ne 0 ]]; then fail "edge_oled_ctl $*: exit $rc"; return; fi
    if ask "$q"; then pass "ctl $*: $q"; else fail "ctl $*: person answered no to '$q'"; fi
}

if timeout 300 sudo -u "$BUILD_USER" make -C "$MOD_DIR" >/dev/null 2>&1; then
    pass "build edge_oled.ko"
else
    fail "build edge_oled.ko"; exit 1
fi
if timeout 300 sudo -u "$BUILD_USER" sh -c "cmake -S '$REPO' -B '$REPO/build' >/dev/null && cmake --build '$REPO/build' --target edge_oled_ctl test_oled_text >/dev/null"; then
    pass "build edge_oled_ctl, test_oled_text (CMake)"
else
    fail "build (CMake)"; exit 1
fi
if "$REPO/build/test_oled_text" >/dev/null; then pass "font vectors"; else fail "font vectors"; fi

marker="edge_oled text verify $$ $(date +%s)"
echo "$marker" > /dev/kmsg
insmod "$KO" || { fail "insmod"; exit 1; }
udevadm settle --timeout=10
if [[ "$(readlink -f "$CLIENT/driver" 2>/dev/null)" == "$(readlink -f $DRV)" ]]; then
    pass "$BUS-003c bound to edge_oled"
else
    fail "$BUS-003c not bound"; exit 1
fi

echo "== text from userspace"
show "Font sheet: 7 lines from the top-left, first 'ABCDEFGHIJKLM', then N..Z, a..m, n..z, '0123456789 EDGE' and two lines of punctuation; nothing mirrored, upside down or shifted between lines?" font
show "Three lines at the top-left: EDGE / LINE 2 / 123456?" text EDGE "LINE 2" 123456

out="$(ctl text "0123456789ABCDEFGHIJKLMNOP" "TAB<$(printf '\t')>" 2>&1)"; rc=$?
echo "$out" | sed 's/^/    /'
if [[ $rc -eq 0 && $out == *"5 character(s) clipped"* && $out == *"1 character(s) not in the font"* ]]; then
    pass "edge_oled_ctl reports 5 clipped and 1 unsupported character"
else
    fail "clipping / unsupported report: exit $rc"
fi
if ask "Line 1 ends with K, then (the first two columns of L) a vertical line at the right edge, not wrapped to line 2; line 2 reads TAB< then a hollow box then >?"; then
    pass "long line clipped, unsupported character drawn as a box"
else
    fail "clipping / box on the panel"
fi

echo "== five refreshes, one per second: the panel must not blink black between them"
ok=1
ctl text "REFRESH 0/5" "EDGE" >/dev/null || ok=0
wait_enter "Look at the OLED (it shows REFRESH 0/5), keep watching"
for n in 1 2 3 4 5; do
    sleep 1
    ctl text "REFRESH $n/5" "EDGE" >/dev/null || ok=0
done
if ((ok)) && ask "Did EDGE stay lit the whole time, with no blink to black at any refresh?"; then
    pass "refresh does not blank the panel"
else
    fail "refreshes (write failed or the panel blinked)"
fi

if ((UNPLUG)); then
    echo "== OLED off and on again with no write in between (--no-unplug skips this)"
    ctl text "BEFORE UNPLUG" >/dev/null || fail "draw before unplug"
    UNPLUGGED=1
    wait_enter "Disconnect all four wires of the OLED (VCC, GND, SDA, SCL)"
    wait_enter "Reconnect all four wires"
    UNPLUGGED=0
    if ask "Reconnected: is the panel dark (power-on reset)?"; then pass "power-on reset seen"; else fail "panel not dark after reconnect: not a real power cycle"; fi
    show "AFTER REPLUG shown (the first write after power came back)?" text "AFTER REPLUG"
else
    echo "SKIP unplug with no write in between (--no-unplug)"
fi

rmmod edge_oled || fail "rmmod"
log="$(dmesg | sed -n "/$marker/,\$p")"
if grep -Eq 'Oops|BUG:|WARNING:|Call trace' <<<"$log"; then fail "kernel warnings in dmesg"; echo "$log"; else pass "dmesg free of Oops/BUG/WARNING"; fi
grep 'edge_oled' <<<"$log" | sed 's/^/    /'

echo "=== $failures failure(s)"
[[ $failures -eq 0 ]]
