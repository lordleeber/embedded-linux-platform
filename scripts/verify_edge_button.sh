#!/usr/bin/env bash
# Step 5-b acceptance: build edge_button.ko and check IRQ -> wait queue -> blocking read() on this boot.
# Usage: sudo bash scripts/verify_edge_button.sh [--no-press]
#
# Wiring: header pin 33 (PH.00) -- push button -- pin 34 (GND), plus 330 Ohm from pin 33 to
# pin 1 (3.3 V): the internal pull-up cannot reach the header (TXB0108). The result depends on
# whether this boot has the overlay with the edge-button node (install + reboot):
#   no /proc/device-tree/edge-button -> insmod must NOT probe
#   node present -> probe, GPIO owned as input/IRQ, reader sleeps without CPU, signal and
#                   rmmod behaviour, then (unless --no-press) a person presses the button:
#                   one press, one long press, rapid presses.
# Exit status: 0 = all checks passed, 1 = a check failed, 2 = environment/usage problem.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MOD_DIR="$REPO/kernel/edge_button"
KO="$MOD_DIR/edge_button.ko"
WAIT="$REPO/build/edge_button_wait"
DEV=/dev/edge_button
NODE=/proc/device-tree/edge-button
DRV=/sys/bus/platform/drivers/edge_button
SYSFS=/sys/bus/platform/devices/edge-button
CHIP=gpiochip0
LINE=43             # PH.00 = header pin 33
PRESS=1
failures=0

pass() { echo "PASS $*"; }
fail() { echo "FAIL $*"; failures=$((failures + 1)); }
die()  { echo "ERROR $*" >&2; exit 2; }

for arg in "$@"; do
    case $arg in
        --no-press) PRESS=0 ;;
        *) die "usage: $0 [--no-press]" ;;
    esac
done
[[ $EUID -eq 0 ]] || die "run as root: sudo bash scripts/verify_edge_button.sh"
command -v gpioinfo >/dev/null || die "gpioinfo missing (apt install gpiod)"
BUILD_USER="${SUDO_USER:-root}"

is_loaded() { grep -q '^edge_button ' /proc/modules; }
# Checked before the EXIT trap exists, so a module the user loaded is left alone.
is_loaded && die "edge_button already loaded; rmmod edge_button first"

tmpdir="$(mktemp -d)"   # root writes here: never a guessable /tmp name
cleanup() {
    pkill -f "^$WAIT" 2>/dev/null
    rm -rf "$tmpdir"
    if is_loaded; then rmmod edge_button || echo "WARN cleanup rmmod failed" >&2; fi
}
trap cleanup EXIT
trap 'exit 2' INT TERM

line_info() { gpioinfo "$CHIP" | awk -v l="$LINE:" '$1 == "line" && $2 == l { $1 = $2 = ""; print }'; }
pinconf() {
    awk '/^[0-9]+ \(/ { show = /\(soc_gpio[0-9]*_ph0\)/ } show' \
        /sys/kernel/debug/pinctrl/*/pinconf-groups 2>/dev/null | tr -s ' \t\n' ' '
}
# Raw pin level from gpiolib debugfs ("hi"/"lo"); released = hi (pull-up, active-low).
pin_level() { awk '/\(PH\.00/ { for (i = 1; i <= NF; i++) if ($i == "hi" || $i == "lo") { print $i; exit } }' /sys/kernel/debug/gpio; }
counter() { cat "$SYSFS/$1"; }

# Runs edge_button_wait in the background for at most $1 seconds reading up to $2 events,
# events in $tmpdir/$3 (stderr in $3.err: a timeout ends it with "interrupted"); sets
# $reader_pid. Started before the prompt, so no press is missed.
start_reader() {
    timeout -k 2 "$1" "$WAIT" "$2" >"$tmpdir/$3" 2>"$tmpdir/$3.err" &   # -k: SIGKILL if SIGTERM is ignored
    reader_pid=$!
    sleep 0.3
}
# "seq=N pressed t=S.NNNNNNNNN" lines -> checks pressed/released alternate and seq has no gap.
check_events() {
    awk '
        { split($1, a, "="); seq = a[2]; state = $2 }
        NR == 1 && state != "pressed" { print "first event is " state; bad = 1 }
        NR > 1 && state == prev        { print "two " state " in a row at seq " seq; bad = 1 }
        NR > 1 && seq != pseq + 1      { print "seq gap " pseq " -> " seq; bad = 1 }
        { prev = state; pseq = seq }
        END { exit bad }' "$1"
}
# With dropped events: prints how many seq numbers are missing; fails if two events with
# consecutive seq numbers have the same state (a gap may legitimately break alternation).
seq_missing() {
    awk '
        { split($1, a, "="); seq = a[2]; state = $2 }
        NR > 1 { missing += seq - pseq - 1; if (seq == pseq + 1 && state == prev) bad = 1 }
        { prev = state; pseq = seq }
        END { print missing + 0; exit bad }' "$1"
}
held_seconds() { awk '{ split($3, t, "="); v[NR] = t[2] } END { printf "%.2f", v[2] - v[1] }' "$1"; }

mountpoint -q /sys/kernel/debug || mount -t debugfs none /sys/kernel/debug || die "cannot mount debugfs"

if timeout 300 sudo -u "$BUILD_USER" make -C "$MOD_DIR" >/dev/null 2>&1; then
    pass "build edge_button.ko"
else
    fail "build edge_button.ko"; exit 1
fi
if timeout 300 sudo -u "$BUILD_USER" sh -c "cmake -S '$REPO' -B '$REPO/build' >/dev/null && cmake --build '$REPO/build' --target edge_button_wait >/dev/null"; then
    pass "build edge_button_wait (CMake)"
else
    fail "build edge_button_wait (CMake)"; exit 1
fi
vermagic="$(modinfo -F vermagic "$KO" | awk '{ print $1 }')"
if [[ $vermagic == "$(uname -r)" ]]; then pass "vermagic matches running kernel"; else fail "vermagic '$vermagic'"; fi

before="$(line_info)"
if [[ $before == *unused* ]]; then pass "line $LINE (PH.00) unused before insmod"; else fail "line $LINE already in use: $before"; exit 1; fi

marker="edge_button verify $$ $(date +%s)"
echo "$marker" > /dev/kmsg

if [[ ! -e $NODE ]]; then
    echo "--- no $NODE in this boot: checking that the driver does not probe"
    insmod "$KO" || { fail "insmod"; exit 1; }
    udevadm settle --timeout=10
    if [[ -d $DRV ]]; then pass "driver registered on platform bus"; else fail "$DRV missing"; fi
    bound="$(find "$DRV" -maxdepth 1 -type l ! -name module)"
    if [[ -z $bound ]]; then pass "no device bound to edge_button"; else fail "bound without DT node: $bound"; fi
    if [[ ! -e $DEV ]]; then pass "$DEV not created"; else fail "$DEV exists without DT node"; fi
    if [[ "$(line_info)" == *unused* ]]; then pass "line $LINE untouched"; else fail "line $LINE taken: $(line_info)"; fi
    rmmod edge_button || fail "rmmod"
    expect_probes=0
else
    echo "--- $NODE present: checking probe, input/IRQ and blocking read"
    insmod "$KO" || { fail "insmod"; exit 1; }
    udevadm settle --timeout=10

    if [[ "$(readlink -f $SYSFS/driver)" == "$(readlink -f $DRV)" ]]; then pass "edge-button bound to edge_button"; else fail "edge-button not bound"; fi
    if [[ -c $DEV && "$(stat -c %a $DEV)" == 444 ]]; then pass "$DEV created, mode 0444"; else fail "$DEV missing or mode $(stat -c %a $DEV 2>/dev/null)"; fi
    info="$(line_info)"
    if [[ $info == *'"button"'*input*active-low*used* ]]; then pass "line $LINE owned by \"button\", input, active-low"; else fail "line $LINE is '$info'"; fi
    if grep -q edge_button /proc/interrupts; then pass "IRQ registered: $(grep edge_button /proc/interrupts | tr -s ' ')"; else fail "edge_button not in /proc/interrupts"; fi

    conf="$(pinconf)"
    echo "    $conf"
    if [[ $conf == *pull=2* && $conf == *tristate=1* && $conf == *enable-input=1* ]]; then
        pass "PH.00 pad: pull-up, output off, input on"
    else
        fail "PH.00 pad not set by pinctrl-0 (want pull=2 tristate=1 enable-input=1)"
    fi
    if [[ "$(pin_level)" == hi ]]; then
        pass "pin idles high (released)"
    else
        fail "pin level '$(pin_level)' with the button released"
        # A pin stuck low gives no edge at all: asking for presses would only waste time.
        echo "    pin 33 is low with nobody pressing. It needs an external pull-up of 330 Ohm..1 kOhm"
        echo "    to 3.3 V (pin 1): the header pin sits behind a TXB0108 whose ~4 kOhm buffers hold"
        echo "    the last level, so the SoC pull-up and anything >= ~2 kOhm cannot lift it. Also"
        echo "    check the button is not shorting it (4-leg buttons: use diagonal legs). Skipping presses."
        PRESS=0
    fi

    echo "    do NOT touch the button until asked"
    if (cd "$REPO" && timeout 60 sudo -u "$BUILD_USER" env EDGE_BUTTON_REQUIRE=1 \
            python3 -m unittest discover -s tests -p test_edge_button_device.py >"$tmpdir/unit" 2>&1); then
        pass "device unittest as $BUILD_USER"
    else
        fail "device unittest as $BUILD_USER"; cat "$tmpdir/unit"
    fi

    # Blocked reader: asleep in the driver, no CPU, holds the module, leaves on a signal.
    "$WAIT" 1 >"$tmpdir/blocked" 2>&1 &
    pid=$!
    sleep 3
    read -r -a st <"/proc/$pid/stat"
    ticks=$((st[13] + st[14]))   # utime + stime
    if [[ ${st[2]} == S && $ticks -le 1 ]]; then
        pass "reader asleep after 3 s (state S, $ticks CPU ticks, wchan $(cat /proc/$pid/wchan))"
    else
        fail "reader state ${st[2]}, $ticks CPU ticks in 3 s"
    fi
    if rmmod edge_button 2>/dev/null; then fail "rmmod succeeded with a reader blocked"; else pass "rmmod refused while a reader is blocked"; fi
    kill -TERM "$pid"
    if timeout 2 tail --pid="$pid" -f /dev/null; then
        wait "$pid"; rc=$?
        if [[ $rc -eq 1 && "$(cat "$tmpdir/blocked")" == interrupted ]]; then pass "SIGTERM wakes the reader: exit 1, 'interrupted'"; else fail "reader exit $rc: $(cat "$tmpdir/blocked")"; fi
    else
        fail "reader still running 2 s after SIGTERM"
    fi

    if ((PRESS)); then
        irq0=$(counter irq_count); ev0=$(counter event_count); drop0=$(counter dropped)

        echo ">>> press the button ONCE and release it (15 s)"
        start_reader 15 2 one; wait "$reader_pid"; rc=$?
        cat "$tmpdir/one" | sed 's/^/    /'
        if [[ $rc -eq 0 ]] && check_events "$tmpdir/one" >/dev/null && [[ $(grep -c . "$tmpdir/one") -eq 2 ]]; then
            pass "one press -> pressed + released"
        else
            fail "one press: exit $rc"; check_events "$tmpdir/one"
        fi
        start_reader 2 1 extra; wait "$reader_pid"
        if [[ ! -s $tmpdir/extra ]]; then pass "no extra event after the release"; else fail "extra event: $(cat "$tmpdir/extra")"; fi
        echo "    raw IRQs for that press: $(( $(counter irq_count) - irq0 )) (bounces), events: $(( $(counter event_count) - ev0 ))"

        echo ">>> press and HOLD the button about 2 s, then release (15 s)"
        start_reader 15 2 long; wait "$reader_pid"; rc=$?
        cat "$tmpdir/long" | sed 's/^/    /'
        if [[ $rc -eq 0 ]] && check_events "$tmpdir/long" >/dev/null; then
            held="$(held_seconds "$tmpdir/long")"
            if awk -v h="$held" 'BEGIN { exit !(h >= 1.0) }'; then
                pass "long press -> one pressed, one released ${held} s later, nothing in between"
            else
                fail "long press held only ${held} s (hold about 2 s)"
            fi
        else
            fail "long press: exit $rc"; check_events "$tmpdir/long"
        fi

        echo ">>> press the button over and over, about 10 times, as fast as you can, until '>>> stop' (6 s)"
        drop1=$(counter dropped); ev1=$(counter event_count)
        start_reader 6 100000 rapid; wait "$reader_pid"
        echo ">>> stop"
        sleep 0.5
        n=$(grep -c . "$tmpdir/rapid"); evs=$(( $(counter event_count) - ev1 )); drops=$(( $(counter dropped) - drop1 ))
        echo "    $n events read, $evs state changes, $drops dropped, $(head -c 300 "$tmpdir/rapid" | tr '\n' ' ')"
        if ((n >= 4)) && check_events "$tmpdir/rapid" >/dev/null && ((drops == 0)); then
            pass "rapid presses: $n events, alternating, no seq gap"
        elif ((n >= 4 && drops > 0)) && missing="$(seq_missing "$tmpdir/rapid")" && ((missing == drops)); then
            pass "rapid presses: queue overflowed, $drops dropped = $missing missing seq numbers"
        else
            fail "rapid presses: $n events"; check_events "$tmpdir/rapid"
        fi
        echo "    totals: irq_count=$(counter irq_count) event_count=$(counter event_count) dropped=$(counter dropped)"
    else
        echo "--- --no-press: skipping the button press checks"
    fi

    rmmod edge_button || fail "rmmod"
    udevadm settle --timeout=10
    if is_loaded || [[ -e $DEV ]]; then fail "leftovers after rmmod"; else pass "module and $DEV gone"; fi
    if [[ "$(line_info)" == *unused* ]]; then pass "line $LINE released"; else fail "line $LINE still held: $(line_info)"; fi
    if grep -q edge_button /proc/interrupts; then fail "IRQ still registered"; else pass "IRQ freed"; fi
    expect_probes=1
fi

log="$(dmesg | sed -n "/$marker/,\$p")"
if grep -Eq 'Oops|BUG:|WARNING:|Call trace' <<<"$log"; then fail "kernel warnings in dmesg"; echo "$log"; else pass "dmesg free of Oops/BUG/WARNING"; fi
probes="$(grep -c 'edge_button edge-button: probed' <<<"$log")"
removes="$(grep -c 'edge_button edge-button: removed' <<<"$log")"
if [[ $probes -eq $expect_probes && $removes -eq $expect_probes ]]; then
    pass "dmesg shows $probes probe / $removes remove"
else
    fail "dmesg probe/remove $probes/$removes, expected $expect_probes/$expect_probes"
fi
grep 'edge_button' <<<"$log" | tail -n 3

pkill -f "^$WAIT" 2>/dev/null
if pgrep -f "^$WAIT" >/dev/null; then fail "edge_button_wait still running"; fi
if is_loaded; then fail "module still loaded at exit"; fi
echo "=== $failures failure(s)"
[[ $failures -eq 0 ]]
