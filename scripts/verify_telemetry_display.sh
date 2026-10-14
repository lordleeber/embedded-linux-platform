#!/usr/bin/env bash
# Step 10-c acceptance: build/telemetry_display shows the INA219's hwmon values on the OLED.
# Usage: sudo bash scripts/verify_telemetry_display.sh [--no-unplug] [--watch-seconds N]
#
# Needs this boot's overlay with ina219@41 (Step 7) and oled@3c (Step 10-a), and a person at
# the board who answers y/n for what the panel shows. Loads edge_ina219 and edge_oled from
# this tree, runs the app in its own process group, and checks:
#   1. the screen reads BAT % / V / I / P and the app's values match hwmon read directly
#   2. sensor unbound: lines go to --.-- and the status to NO SENSOR; bound again (maybe a new
#      hwmonN): values come back without restarting the app
#   3. (unless --no-unplug) all four OLED wires off: the app keeps running and reports the
#      write error once; reconnected: the picture comes back by itself
#   4. N seconds (default 30) of 1 s refreshes: no flicker or brightness drop (PR #15 review:
#      every flush re-sends the settings while the panel is lit)
#   5. SIGTERM to the process group: exit 0 within 2 s, panel blank, no process left
# Exit status: 0 = all checks passed, 1 = a check failed, 2 = environment/usage problem.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP="$REPO/build/telemetry_display"
INA_NODE=/proc/device-tree/bus@0/i2c@c250000/ina219@41
OLED_NODE=/proc/device-tree/bus@0/i2c@c240000/oled@3c
INA_DRV=/sys/bus/i2c/drivers/edge_ina219
UNPLUG=1
WATCH_SEC=30
ANSWER_TIMEOUT=300
failures=0

pass() { echo "PASS $*"; }
fail() { echo "FAIL $*"; failures=$((failures + 1)); }
die()  { echo "ERROR $*" >&2; exit 2; }
usage() { die "usage: $0 [--no-unplug] [--watch-seconds N]"; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-unplug) UNPLUG=0; shift ;;
        --watch-seconds) [[ ${2:-} =~ ^[0-9]+$ ]] || usage; WATCH_SEC=$2; shift 2 ;;
        *) usage ;;
    esac
done
[[ $EUID -eq 0 ]] || die "run as root: sudo bash scripts/verify_telemetry_display.sh"
command -v i2cdetect >/dev/null || die "i2cdetect missing (apt install i2c-tools)"
# /dev/tty is mode 666 even without a controlling terminal; only opening it tells.
{ : </dev/tty; } 2>/dev/null || die "needs a terminal: a person answers what the OLED shows"
[[ -e $INA_NODE && -e $OLED_NODE ]] || die "this boot lacks ina219@41 or oled@3c: install the overlay and reboot"
for m in edge_ina219 edge_oled; do
    grep -q "^$m " /proc/modules && die "$m already loaded; rmmod $m first"
done
BUILD_USER="${SUDO_USER:-root}"
INA_BUS="$(i2cdetect -l | awk '$3 == "c250000.i2c" { sub("i2c-", "", $1); print $1 }')"
[[ -n $INA_BUS ]] || die "no c250000.i2c adapter in i2cdetect -l"
INA_CLIENT=$INA_BUS-0041

tmpdir="$(mktemp -d)"
PID=""
UNPLUGGED=0
COMM=telemetry_displ    # the kernel keeps 15 characters of the name: pgrep -x matches this
cleanup() {
    [[ -n $PID ]] && kill -TERM -- -"$PID" 2>/dev/null
    sleep 0.3
    pkill -KILL -x "$COMM" 2>/dev/null
    [[ -e /sys/bus/i2c/devices/$INA_CLIENT && ! -e /sys/bus/i2c/devices/$INA_CLIENT/driver && -d $INA_DRV ]] &&
        echo "$INA_CLIENT" > "$INA_DRV/bind" 2>/dev/null
    for m in edge_oled edge_ina219; do
        grep -q "^$m " /proc/modules && { rmmod $m || echo "WARN cleanup rmmod $m failed" >&2; }
    done
    rm -rf "$tmpdir"
}
trap cleanup EXIT
trap '[[ $UNPLUGGED -eq 1 ]] && echo ">>> Interrupted: reconnect the OLED."; exit 2' INT TERM

# Throw away keys pressed while the script was busy: an Enter typed during the watch would
# otherwise answer the next question (empty = no) before anyone reads it.
drain_tty() { while read -r -t 0.05 _ </dev/tty; do :; done; }
ask() {
    local ans=""
    drain_tty
    read -r -t "$ANSWER_TIMEOUT" -p ">>> $1 [y/n] " ans </dev/tty || echo
    [[ $ans == [yY]* ]]
}
wait_enter() {
    drain_tty
    read -r -t "$ANSWER_TIMEOUT" -p ">>> $1, then press Enter " _ </dev/tty || echo
}
check_ask() { if ask "$1"; then pass "$1"; else fail "person answered no to '$1'"; fi; }
hwmon_dir() { grep -lx edge_ina219 /sys/class/hwmon/hwmon*/name 2>/dev/null | head -1 | xargs -r dirname; }
last() { tail -n 1 "$tmpdir/out"; }
# field V|I|P from the app's last stdout line ("-" = not read)
field() { last | tr ' ' '\n' | sed -n "s/^$1=//p"; }

for m in edge_ina219 edge_oled; do
    if timeout 300 sudo -u "$BUILD_USER" make -C "$REPO/kernel/$m" >/dev/null 2>&1; then pass "build $m.ko"; else fail "build $m.ko"; exit 1; fi
done
if timeout 300 sudo -u "$BUILD_USER" sh -c "cmake -S '$REPO' -B '$REPO/build' >/dev/null && cmake --build '$REPO/build' --target telemetry_display test_telemetry >/dev/null"; then
    pass "build telemetry_display, test_telemetry (CMake)"
else
    fail "build (CMake)"; exit 1
fi
if "$REPO/build/test_telemetry" >/dev/null; then pass "telemetry vectors"; else fail "telemetry vectors"; fi

marker="telemetry verify $$ $(date +%s)"
echo "$marker" > /dev/kmsg
insmod "$REPO/kernel/edge_ina219/edge_ina219.ko" || { fail "insmod edge_ina219"; exit 1; }
insmod "$REPO/kernel/edge_oled/edge_oled.ko" || { fail "insmod edge_oled"; exit 1; }
udevadm settle --timeout=10
HW="$(hwmon_dir)"
if [[ -n $HW && -c /dev/edge_oled ]]; then pass "sensor at $HW, /dev/edge_oled present"; else fail "no edge_ina219 hwmon or no /dev/edge_oled"; exit 1; fi

echo "== the app, 1 s refresh, own process group"
# The background child is not a group leader, so setsid execs the app itself: $! is the app
# and its new process group.
setsid "$APP" >"$tmpdir/out" 2>"$tmpdir/err" &
PID=$!
sleep 3
hv="$(cat "$HW/in1_input")" hi="$(cat "$HW/curr1_input")"
av="$(field V)" ai="$(field I)"
echo "    app: $(last)"
echo "    hwmon now: in1_input $hv mV, curr1_input $hi mA, power1_input $(cat "$HW/power1_input") uW"
# What the vendor sample (ina219.py) would print as Percentage for this voltage.
echo "    vendor formula: BAT $(awk -v mv="$hv" 'BEGIN { p = (mv - 9000) / 36; if (p < 0) p = 0; if (p > 100) p = 100; printf "%.2f", p }') %"
# Two reads a moment apart: Step 7's tolerances (bus 40 mV, current 50 mA).
if [[ $av =~ ^-?[0-9]+$ && $ai =~ ^-?[0-9]+$ ]] && (( (av - hv) * (av - hv) <= 1600 && (ai - hi) * (ai - hi) <= 2500 )); then
    pass "app values match hwmon (V $av vs $hv mV, I $ai vs $hi mA)"
else
    fail "app values '$av' / '$ai' vs hwmon $hv / $hi"
fi
check_ask "OLED: BAT % as the vendor formula above, then V / I / P with the hwmon numbers (rounded to 0.01), status OK and a counter going up?"

echo "== sensor unbound, then bound again"
echo "$INA_CLIENT" > "$INA_DRV/unbind"
sleep 5
echo "    app: $(last)"
if [[ "$(last)" == *"V=- I=- P=-"* ]]; then pass "app reads nothing while the sensor is unbound"; else fail "app still reads values: $(last)"; fi
check_ask "OLED: V / I / P show --.-- and the status says NO SENSOR (counter still going up)?"
echo "$INA_CLIENT" > "$INA_DRV/bind"
udevadm settle --timeout=10
sleep 3
echo "    sensor now at $(hwmon_dir); app: $(last)"
if [[ "$(field V)" =~ ^[0-9]+$ ]]; then pass "values back after bind, app not restarted"; else fail "after bind: $(last)"; fi
check_ask "OLED: numbers and status OK back?"

if ((UNPLUG)); then
    echo "== OLED off and on while the app runs (--no-unplug skips this)"
    UNPLUGGED=1
    wait_enter "Disconnect all four wires of the OLED (VCC, GND, SDA, SCL)"
    sleep 3
    wait_enter "Reconnect all four wires"
    UNPLUGGED=0
    sleep 3
    if kill -0 "$PID" 2>/dev/null; then pass "app still running"; else fail "app exited during the unplug"; fi
    # Wires go back one at a time: other errnos or a second failure streak are fine; an error
    # must have been reported and the last refresh must have got through.
    if grep -q "/dev/edge_oled: " "$tmpdir/err" && [[ "$(last)" == *"oled=ok" ]]; then
        pass "write error reported ($(grep -c /dev/edge_oled: "$tmpdir/err") line(s)), last refresh ok"
    else
        fail "stderr: $(cat "$tmpdir/err"); last: $(last)"
    fi
    check_ask "OLED: the values are back by themselves (nothing restarted)?"
else
    echo "SKIP OLED unplug (--no-unplug)"
fi

if ((WATCH_SEC)); then
    echo "== watch for $WATCH_SEC s: flicker or brightness drop at any refresh (--watch-seconds 0 skips)"
    wait_enter "Look at the OLED and keep watching until asked"
    before=$(wc -l < "$tmpdir/out")
    sleep "$WATCH_SEC"
    lines=$(( $(wc -l < "$tmpdir/out") - before ))
    bad=$(tail -n "$lines" "$tmpdir/out" | grep -vc "oled=ok")
    if (( lines >= WATCH_SEC - 2 && lines <= WATCH_SEC + 2 && bad == 0 )); then
        pass "$lines refreshes in $WATCH_SEC s, every write ok"
    else
        fail "$lines refreshes in $WATCH_SEC s, $bad not ok"
    fi
    check_ask "During those $WATCH_SEC s: no flicker and no brightness drop at any refresh?"
fi

echo "== SIGTERM to the process group"
kill -TERM -- -"$PID"
for _ in $(seq 20); do kill -0 "$PID" 2>/dev/null || break; sleep 0.1; done
if kill -0 "$PID" 2>/dev/null; then
    kill -KILL -- -"$PID"; fail "still running 2 s after SIGTERM (killed)"
fi
wait "$PID"; rc=$?
PID=""
if [[ $rc -eq 0 ]]; then pass "exit 0 within 2 s"; else fail "exit status $rc (or still running)"; fi
if pgrep -x "$COMM" >/dev/null; then fail "a telemetry_display process is left"; else pass "no process left (pgrep)"; fi
check_ask "OLED: blank (dark), no numbers left on it?"

rmmod edge_oled || fail "rmmod edge_oled"
rmmod edge_ina219 || fail "rmmod edge_ina219"
log="$(dmesg | sed -n "/$marker/,\$p")"
if grep -Eq 'Oops|BUG:|WARNING:|Call trace' <<<"$log"; then fail "kernel warnings in dmesg"; echo "$log"; else pass "dmesg free of Oops/BUG/WARNING"; fi
grep -E 'edge_(oled|ina219)' <<<"$log" | sed 's/^/    /'

echo "=== $failures failure(s)"
[[ $failures -eq 0 ]]
