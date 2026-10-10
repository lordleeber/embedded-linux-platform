#!/usr/bin/env bash
# Step 5-a acceptance: wait for button presses from userspace through gpiolib-cdev edge events.
# Usage: sudo bash scripts/verify_edge_gpio_button.sh [--no-press]
#
# Wiring as in Step 5-b: header pin 33 (PH.00) -- push button -- pin 34 (GND), plus 330 Ohm from
# pin 33 to pin 1 (3.3 V). No driver of ours: edge_button.ko must NOT be loaded (it would own
# line 43). Checks: pad config, idle level, reader asleep without CPU, second reader EBUSY,
# signal ends the wait and releases the line, then (unless --no-press) a person presses:
# once, a long press, rapid presses -- the same checks as verify_edge_button.sh.
# Exit status: 0 = all checks passed, 1 = a check failed, 2 = environment/usage problem.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP="$REPO/build/edge_gpio_button"
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
[[ $EUID -eq 0 ]] || die "run as root: sudo bash scripts/verify_edge_gpio_button.sh"
command -v gpioinfo >/dev/null || die "gpioinfo missing (apt install gpiod)"
grep -q '^edge_button ' /proc/modules && die "edge_button.ko is loaded and owns line $LINE; rmmod edge_button first"
BUILD_USER="${SUDO_USER:-root}"

tmpdir="$(mktemp -d)"   # root writes here: never a guessable /tmp name
cleanup() {
    pkill -f "^$APP" 2>/dev/null
    rm -rf "$tmpdir"
}
trap cleanup EXIT
trap 'exit 2' INT TERM

line_info() { gpioinfo "$CHIP" | awk -v l="$LINE:" '$1 == "line" && $2 == l { $1 = $2 = ""; print }'; }
pinconf() {
    awk '/^[0-9]+ \(/ { show = /\(soc_gpio[0-9]*_ph0\)/ } show' \
        /sys/kernel/debug/pinctrl/*/pinconf-groups 2>/dev/null | tr -s ' \t\n' ' '
}
# Raw level from gpiolib debugfs ("hi"/"lo"); only listed while the line is requested.
pin_level() { awk '/\(PH\.00/ { for (i = 1; i <= NF; i++) if ($i == "hi" || $i == "lo") { print $i; exit } }' /sys/kernel/debug/gpio; }
wait_held() {   # until gpioinfo shows our consumer on the line (max 2 s)
    for _ in $(seq 100); do [[ "$(line_info)" == *'"edge_gpio_button"'* ]] && return 0; sleep 0.02; done
    return 1
}
# Events in $tmpdir/$3, stderr in $3.err; sets $reader_pid. Started before the prompt.
start_reader() {
    timeout -k 2 "$1" "$APP" "$2" >"$tmpdir/$3" 2>"$tmpdir/$3.err" &   # -k: SIGKILL if SIGTERM is ignored
    reader_pid=$!
    wait_held
    sleep 0.1   # past the program's 50 ms settle
}
check_events() {   # pressed first, alternating, consecutive seq
    awk '
        { split($1, a, "="); seq = a[2]; state = $2 }
        NR == 1 && state != "pressed" { print "first event is " state; bad = 1 }
        NR > 1 && state == prev        { print "two " state " in a row at seq " seq; bad = 1 }
        NR > 1 && seq != pseq + 1      { print "seq gap " pseq " -> " seq; bad = 1 }
        { prev = state; pseq = seq }
        END { exit bad }' "$1"
}
held_seconds() { awk '{ split($3, t, "="); v[NR] = t[2] } END { printf "%.2f", v[2] - v[1] }' "$1"; }

mountpoint -q /sys/kernel/debug || mount -t debugfs none /sys/kernel/debug || die "cannot mount debugfs"

if timeout 300 sudo -u "$BUILD_USER" sh -c "cmake -S '$REPO' -B '$REPO/build' >/dev/null && cmake --build '$REPO/build' --target edge_gpio_button >/dev/null"; then
    pass "build edge_gpio_button (CMake)"
else
    fail "build edge_gpio_button (CMake)"; exit 1
fi
if [[ "$(line_info)" == *unused* ]]; then pass "line $LINE (PH.00) unused"; else fail "line $LINE in use: $(line_info)"; exit 1; fi
marker="edge_gpio_button verify $$ $(date +%s)"
echo "$marker" > /dev/kmsg

# Pad: without edge_button.ko nobody applies the DT pinctrl state, so this is the boot default --
# unless edge_button probed earlier in this boot (pinctrl states survive the unbind).
conf="$(pinconf)"
echo "    $conf"
if dmesg | grep -q 'edge_button edge-button: probed'; then
    echo "    note: edge_button probed earlier in this boot, so its pinctrl state may still be set; reboot to see the boot default"
else
    echo "    no edge_button probe in this boot: this is the boot-default pad"
fi
if [[ $conf == *enable-input=1* ]]; then pass "PH.00 pad: input enabled"; else fail "PH.00 pad: input disabled, the pin cannot be read"; fi

# Reader asleep, line held, level settled.
"$APP" 1 >"$tmpdir/blocked" 2>"$tmpdir/blocked.err" &
pid=$!
if wait_held; then pass "line $LINE held: $(line_info)"; else fail "line $LINE not taken: $(line_info)"; fi
sleep 3
if [[ "$(pin_level)" == hi ]]; then
    pass "pin idles high (released) once settled"
else
    fail "pin level '$(pin_level)' with the button released"
    echo "    pin 33 needs 330 Ohm..1 kOhm to 3.3 V (pin 1): see Step 5-b. Skipping presses."
    PRESS=0
fi
read -r -a st <"/proc/$pid/stat"
ticks=$((st[13] + st[14]))   # utime + stime
if [[ ${st[2]} == S && $ticks -le 1 ]]; then
    pass "reader asleep after 3 s (state S, $ticks CPU ticks, wchan $(cat /proc/$pid/wchan))"
else
    fail "reader state ${st[2]}, $ticks CPU ticks in 3 s"
fi
busy="$("$APP" 1 2>&1)"; rc=$?
if [[ $rc -eq 1 && $busy == *busy* ]]; then pass "second reader gets EBUSY: $busy"; else fail "second reader: exit $rc, '$busy'"; fi
kill -TERM "$pid"
if timeout 2 tail --pid="$pid" -f /dev/null; then
    wait "$pid"; rc=$?
    if [[ $rc -eq 1 && "$(cat "$tmpdir/blocked.err")" == *interrupted* ]]; then pass "SIGTERM ends the wait: exit 1, 'interrupted'"; else fail "reader exit $rc: $(cat "$tmpdir/blocked.err")"; fi
else
    fail "reader still running 2 s after SIGTERM"
fi
grep -h ignored "$tmpdir/blocked.err" | sed 's/^/    startup: /'
if [[ "$(line_info)" == *unused* ]]; then pass "line $LINE released"; else fail "line $LINE still held: $(line_info)"; fi

echo "    do NOT touch the button until asked"
if (cd "$REPO" && timeout 120 sudo -u "$BUILD_USER" env EDGE_GPIO_HW=1 \
        python3 -m unittest discover -s tests -p test_edge_gpio_button.py >"$tmpdir/unit" 2>&1); then
    pass "unittest (hardware cases) as $BUILD_USER"
else
    fail "unittest as $BUILD_USER"; cat "$tmpdir/unit"
fi

if ((PRESS)); then
    echo ">>> press the button ONCE and release it (15 s)"
    start_reader 15 2 one; wait "$reader_pid"; rc=$?
    sed 's/^/    /' "$tmpdir/one"
    if [[ $rc -eq 0 ]] && check_events "$tmpdir/one" >/dev/null && [[ $(grep -c . "$tmpdir/one") -eq 2 ]]; then
        pass "one press -> pressed + released"
    else
        fail "one press: exit $rc"; check_events "$tmpdir/one"
    fi
    start_reader 2 1 extra; wait "$reader_pid"
    if [[ ! -s $tmpdir/extra ]]; then pass "no extra event after the release"; else fail "extra event: $(cat "$tmpdir/extra")"; fi

    echo ">>> press and HOLD the button about 2 s, then release (15 s)"
    start_reader 15 2 long; wait "$reader_pid"; rc=$?
    sed 's/^/    /' "$tmpdir/long"
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
    start_reader 6 100000 rapid; wait "$reader_pid"
    echo ">>> stop"
    n=$(grep -c . "$tmpdir/rapid")
    echo "    $n events read, $(head -c 300 "$tmpdir/rapid" | tr '\n' ' ')"
    # Per the gpiolib-cdev source (not checked on this box), a full 16-entry queue drops the oldest
    # event: that shows as a seq gap.
    if ((n >= 4)) && check_events "$tmpdir/rapid" >/dev/null; then
        pass "rapid presses: $n events, alternating, no seq gap"
    else
        fail "rapid presses: $n events"; check_events "$tmpdir/rapid"
    fi
else
    echo "--- skipping the button press checks"
fi

log="$(dmesg | sed -n "/$marker/,\$p")"
if grep -Eq 'Oops|BUG:|WARNING:|Call trace' <<<"$log"; then fail "kernel warnings in dmesg"; echo "$log"; else pass "dmesg free of Oops/BUG/WARNING"; fi

pkill -f "^$APP" 2>/dev/null
sleep 0.2
if pgrep -f "^$APP" >/dev/null; then fail "edge_gpio_button still running"; fi
if [[ "$(line_info)" != *unused* ]]; then fail "line $LINE still held at exit"; fi
echo "=== $failures failure(s)"
[[ $failures -eq 0 ]]
