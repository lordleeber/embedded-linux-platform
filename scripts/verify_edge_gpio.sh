#!/usr/bin/env bash
# Step 4 acceptance: build edge_gpio.ko and check probe / GPIO / release on this boot.
# Usage: sudo bash scripts/verify_edge_gpio.sh [--blink] [cycles]
#
# The result depends on whether this boot has the overlay applied
# (scripts/install_edge_gpio_overlay.py + reboot):
#   no /proc/device-tree/edge-led  -> insmod must NOT probe (driver registered, nothing bound)
#   node present                   -> probe, GPIO owned as output, pin level follows writes,
#                                     rmmod refused while open, GPIO released after rmmod
# --blink toggles the LED 5 times so a person can watch it.
# Exit status: 0 = all checks passed, 1 = a check failed, 2 = environment/usage problem.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MOD_DIR="$REPO/kernel/edge_gpio"
KO="$MOD_DIR/edge_gpio.ko"
DEV=/dev/edge_gpio
NODE=/proc/device-tree/edge-led
DRV=/sys/bus/platform/drivers/edge_gpio
CHIP=gpiochip0
LINE=105            # PQ.05 = header pin 29
BLINK=0
CYCLES=3
failures=0

pass() { echo "PASS $*"; }
fail() { echo "FAIL $*"; failures=$((failures + 1)); }
die()  { echo "ERROR $*" >&2; exit 2; }

for arg in "$@"; do
    case $arg in
        --blink) BLINK=1 ;;
        *) [[ $arg =~ ^[1-9][0-9]*$ ]] || die "usage: $0 [--blink] [cycles]"; CYCLES=$arg ;;
    esac
done
[[ $EUID -eq 0 ]] || die "run as root: sudo bash scripts/verify_edge_gpio.sh"
command -v gpioinfo >/dev/null || die "gpioinfo missing (apt install gpiod)"
BUILD_USER="${SUDO_USER:-root}"

is_loaded() { grep -q '^edge_gpio ' /proc/modules; }
# Checked before the EXIT trap exists, so a module the user loaded is left alone.
is_loaded && die "edge_gpio already loaded; rmmod edge_gpio first"

outfile="$(mktemp)"   # root writes test output here: never a guessable /tmp name
cleanup() {
    rm -f "$outfile"
    exec 7<&- 2>/dev/null
    if is_loaded; then rmmod edge_gpio || echo "WARN cleanup rmmod failed" >&2; fi
}
trap cleanup EXIT
trap 'exit 2' INT TERM

# "line 105: "PQ.05" "led" output active-high [used]" -> consumer and direction
line_info() { gpioinfo "$CHIP" | awk -v l="$LINE:" '$1 == "line" && $2 == l { $1 = $2 = ""; print }'; }
# pinconf-groups is multi-line: "115 (soc_gpio32_pq5):" then one indented line per config.
pinconf() {
    awk '/^[0-9]+ \(/ { show = /\(soc_gpio[0-9]*_pq5\)/ } show' \
        /sys/kernel/debug/pinctrl/*/pinconf-groups 2>/dev/null | tr -s ' \t\n' ' '
}
# Raw output register level from gpiolib debugfs ("hi"/"lo"); only listed while the line is requested.
pin_level() { awk '/\(PQ\.05/ { for (i = 1; i <= NF; i++) if ($i == "hi" || $i == "lo") { print $i; exit } }' /sys/kernel/debug/gpio; }

mountpoint -q /sys/kernel/debug || mount -t debugfs none /sys/kernel/debug || die "cannot mount debugfs"

if timeout 300 sudo -u "$BUILD_USER" make -C "$MOD_DIR" >/dev/null 2>&1; then
    pass "build edge_gpio.ko"
else
    fail "build edge_gpio.ko"; exit 1
fi
# Step 4-a's userspace blinker: must get EBUSY while the driver owns the line.
if timeout 300 sudo -u "$BUILD_USER" sh -c "cmake -S '$REPO' -B '$REPO/build' >/dev/null && cmake --build '$REPO/build' --target edge_gpio_blink >/dev/null"; then
    pass "build edge_gpio_blink (CMake)"
else
    fail "build edge_gpio_blink (CMake)"; exit 1
fi
vermagic="$(modinfo -F vermagic "$KO" | awk '{ print $1 }')"
if [[ $vermagic == "$(uname -r)" ]]; then pass "vermagic matches running kernel"; else fail "vermagic '$vermagic'"; fi

before="$(line_info)"
if [[ $before == *unused* ]]; then pass "line $LINE (PQ.05) unused before insmod"; else fail "line $LINE already in use: $before"; exit 1; fi

marker="edge_gpio verify $$ $(date +%s)"
echo "$marker" > /dev/kmsg

if [[ ! -e $NODE ]]; then
    echo "--- no $NODE in this boot: checking that the driver does not probe"
    CYCLES=1
    insmod "$KO" || { fail "insmod"; exit 1; }
    udevadm settle --timeout=10
    if [[ -d $DRV ]]; then pass "driver registered on platform bus"; else fail "$DRV missing"; fi
    bound="$(find "$DRV" -maxdepth 1 -type l ! -name module)"
    if [[ -z $bound ]]; then pass "no device bound to edge_gpio"; else fail "bound without DT node: $bound"; fi
    if [[ ! -e $DEV ]]; then pass "$DEV not created"; else fail "$DEV exists without DT node"; fi
    if [[ "$(line_info)" == *unused* ]]; then pass "line $LINE untouched"; else fail "line $LINE taken: $(line_info)"; fi
    rmmod edge_gpio || fail "rmmod"
    expect_probes=0
else
    flags="$(od -An -tx1 -j8 -N4 "$NODE/led-gpios" | tr -d ' \n')"
    case $flags in
        00000000) polarity=active-high; on=hi; off=lo ;;
        00000001) polarity=active-low;  on=lo; off=hi ;;
        *) die "unexpected led-gpios flags cell '$flags'" ;;
    esac
    echo "--- $NODE present ($polarity): checking probe, GPIO control and release"

    for ((i = 1; i <= CYCLES; i++)); do
        echo "--- cycle $i/$CYCLES"
        insmod "$KO" || { fail "cycle $i: insmod"; break; }
        udevadm settle --timeout=10

        # Pad config while the driver holds the line (the DT pinctrl "default" state).
        if ((i == 1)); then
            conf="$(pinconf)"
            if [[ -z $conf ]]; then
                fail "PQ.05 pinconf group not found in debugfs"
            else
                echo "    $conf"
                if [[ $conf == *tristate=0* && $conf == *enable-input=0* ]]; then
                    pass "PQ.05 pad drives (tristate=0, input=0) while bound"
                else
                    fail "PQ.05 pad not set by pinctrl-0: output will not reach the pin"
                fi
            fi
            # As root: a user outside the gpio group would get EACCES, not EBUSY.
            busy="$("$REPO/build/edge_gpio_blink" 2>&1)"; rc=$?
            if [[ $rc -eq 1 && $busy == *"request line 105"*busy* ]]; then
                pass "userspace edge_gpio_blink gets EBUSY while the driver owns line $LINE"
            else
                fail "edge_gpio_blink while bound: exit $rc, '$busy'"
            fi
        fi

        if [[ "$(readlink -f /sys/bus/platform/devices/edge-led/driver)" == "$(readlink -f $DRV)" ]]; then
            pass "cycle $i: edge-led bound to edge_gpio"
        else
            fail "cycle $i: edge-led not bound"
        fi
        if [[ -c $DEV ]]; then pass "cycle $i: $DEV created"; else fail "cycle $i: $DEV missing"; fi

        info="$(line_info)"
        if [[ $info == *'"led"'*output*$polarity* ]]; then
            pass "cycle $i: line $LINE owned by \"led\", output, $polarity"
        else
            fail "cycle $i: line $LINE is '$info'"
        fi

        if [[ "$(cat $DEV)" == 0 && "$(pin_level)" == "$off" ]]; then
            pass "cycle $i: starts off (pin $off)"
        else
            fail "cycle $i: initial state '$(cat $DEV)' pin '$(pin_level)', expected 0 / $off"
        fi
        echo 1 > $DEV
        if [[ "$(cat $DEV)" == 1 && "$(pin_level)" == "$on" ]]; then pass "cycle $i: on -> pin $on"; else fail "cycle $i: on -> pin '$(pin_level)'"; fi
        echo 0 > $DEV
        if [[ "$(cat $DEV)" == 0 && "$(pin_level)" == "$off" ]]; then pass "cycle $i: off -> pin $off"; else fail "cycle $i: off -> pin '$(pin_level)'"; fi

        if (cd "$REPO" && timeout 60 sudo -u "$BUILD_USER" env EDGE_GPIO_REQUIRE=1 \
                python3 -m unittest discover -s tests -p test_edge_gpio_device.py >"$outfile" 2>&1); then
            pass "cycle $i: device unittest as $BUILD_USER"
        else
            fail "cycle $i: device unittest as $BUILD_USER"; cat "$outfile"
        fi

        if ((BLINK && i == 1)); then
            echo "    watch the LED on pin 29: 5 blinks"
            for _ in 1 2 3 4 5; do echo 1 > $DEV; sleep 0.5; echo 0 > $DEV; sleep 0.5; done
        fi

        exec 7<"$DEV"
        if rmmod edge_gpio 2>/dev/null; then fail "cycle $i: rmmod succeeded with $DEV open"; else pass "cycle $i: rmmod refused while $DEV open"; fi
        exec 7<&-

        echo 1 > $DEV
        rmmod edge_gpio || { fail "cycle $i: rmmod"; break; }
        udevadm settle --timeout=10
        if is_loaded || [[ -e $DEV ]]; then fail "cycle $i: leftovers after rmmod"; else pass "cycle $i: module and $DEV gone"; fi
        if [[ "$(line_info)" == *unused* ]]; then pass "cycle $i: line $LINE released"; else fail "cycle $i: line $LINE still held: $(line_info)"; fi
    done
    # Informational: does the pad keep the pinctrl state after the driver is gone?
    echo "    after rmmod: $(pinconf)"
    # remove() must leave the LED off, but the released line is no longer in debugfs
    # and re-requesting it would change it: only a person can check this one.
    echo "    look at the LED now: it must be OFF (each cycle wrote 1 right before rmmod)"
    expect_probes=$CYCLES
fi

log="$(dmesg | sed -n "/$marker/,\$p")"
if grep -Eq 'Oops|BUG:|WARNING:|Call trace' <<<"$log"; then fail "kernel warnings in dmesg"; echo "$log"; else pass "dmesg free of Oops/BUG/WARNING"; fi
probes="$(grep -c 'edge_gpio edge-led: probed' <<<"$log")"
removes="$(grep -c 'edge_gpio edge-led: removed' <<<"$log")"
if [[ $probes -eq $expect_probes && $removes -eq $expect_probes ]]; then
    pass "dmesg shows $probes probe / $removes remove"
else
    fail "dmesg probe/remove $probes/$removes, expected $expect_probes/$expect_probes"
fi
grep 'edge_gpio' <<<"$log" | tail -n 4

if is_loaded; then fail "module still loaded at exit"; fi
echo "=== $failures failure(s)"
[[ $failures -eq 0 ]]
