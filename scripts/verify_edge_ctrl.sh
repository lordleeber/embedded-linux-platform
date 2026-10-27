#!/usr/bin/env bash
# Step 13 acceptance: build edge_ctrl.ko, bind it to the Blue Pill at 0x42, compare every
# sysfs attribute with raw I2C, and check errors, unbind and removal.
# Usage: sudo bash scripts/verify_edge_ctrl.sh [--no-look] [--no-unplug]
#
# The Blue Pill (Step 12-b firmware, register map v1.1) answers on c240000.i2c at 0x42, A0 on
# the divider midpoint. The result depends on whether this boot has the overlay with the
# controller@42 node (make -C dts, install, reboot):
#   no node      -> no client <bus>-0042 exists, insmod must not bind anything
#   node present -> client exists unbound before insmod; insmod binds it; the device unittest
#                   (as root) compares the attributes with i2ctransfer; LED on / off is checked
#                   by a person unless --no-look; unless --no-unplug, a person unplugs the
#                   ST-Link (the Blue Pill loses power): reads must fail with an errno, and after
#                   plugging it back they must work again without rebinding, with STATUS showing
#                   RESET; unbind removes the attributes, bind brings them back; a file opened
#                   before rmmod reads ENODEV afterwards
# Both modes also instantiate a client at 0x43 (nobody answers): probe() must fail.
# Raw access uses -f: while the driver is bound, i2c-dev refuses 0x42 without it (EBUSY).
# Exit status: 0 = all checks passed, 1 = a check failed, 2 = environment/usage problem.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MOD_DIR="$REPO/kernel/edge_ctrl"
KO="$MOD_DIR/edge_ctrl.ko"
DRV=/sys/bus/i2c/drivers/edge_ctrl
NODE=/proc/device-tree/bus@0/i2c@c240000/controller@42
DEAD=0x43
LOOK=1
UNPLUG=1
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

for a in "$@"; do
    case $a in
        --no-look) LOOK=0 ;;
        --no-unplug) UNPLUG=0 ;;
        *) die "usage: $0 [--no-look] [--no-unplug]" ;;
    esac
done
[[ $EUID -eq 0 ]] || die "run as root: sudo bash scripts/verify_edge_ctrl.sh"
command -v i2ctransfer >/dev/null || die "i2ctransfer missing (apt install i2c-tools)"
BUILD_USER="${SUDO_USER:-root}"

BUS="$(i2cdetect -l | awk '$3 == "c240000.i2c" { sub("i2c-", "", $1); print $1 }')"
[[ -n $BUS ]] || die "no c240000.i2c adapter in i2cdetect -l"
ADAPTER=/sys/bus/i2c/devices/i2c-$BUS
CLIENT=/sys/bus/i2c/devices/$BUS-0042

is_loaded() { grep -q '^edge_ctrl ' /proc/modules; }
is_loaded && die "edge_ctrl already loaded; rmmod edge_ctrl first"

tmpdir="$(mktemp -d)"
cleanup() {
    [[ -e /sys/bus/i2c/devices/$BUS-00${DEAD#0x} ]] && echo "$DEAD" > "$ADAPTER/delete_device"
    i2ctransfer -f -y "$BUS" w2@0x42 0x20 0x00 2>/dev/null   # LED off
    rm -rf "$tmpdir"
    if is_loaded; then rmmod edge_ctrl || echo "WARN cleanup rmmod failed" >&2; fi
}
trap cleanup EXIT
trap 'exit 2' INT TERM

bound() { [[ "$(readlink -f "$CLIENT/driver" 2>/dev/null)" == "$(readlink -f $DRV)" ]]; }
raw() { i2ctransfer -f -y "$BUS" w1@0x42 "$1" "r${2:-1}@0x42"; }
ATTRS="device_id firmware_version protocol_version adc button button_presses led status"
show_attrs() { for a in $ATTRS; do printf '    %-17s %s\n' "$a" "$(cat "$CLIENT/$a" 2>&1)"; done; }

if timeout 300 sudo -u "$BUILD_USER" make -C "$MOD_DIR" >/dev/null 2>&1; then
    pass "build edge_ctrl.ko"
else
    fail "build edge_ctrl.ko"; exit 1
fi
if timeout 300 sudo -u "$BUILD_USER" sh -c "cmake -S '$REPO' -B '$REPO/build' >/dev/null && cmake --build '$REPO/build' --target test_edge_ctrl_regs >/dev/null" \
        && "$REPO/build/test_edge_ctrl_regs" >/dev/null; then
    pass "register vectors against the firmware's state machine"
else
    fail "register vectors"
fi
vermagic="$(modinfo -F vermagic "$KO" | awk '{ print $1 }')"
if [[ $vermagic == "$(uname -r)" ]]; then pass "vermagic matches running kernel"; else fail "vermagic '$vermagic'"; fi
echo "    bus: c240000.i2c = i2c-$BUS"

marker="edge_ctrl verify $$ $(date +%s)"
echo "$marker" > /dev/kmsg

if [[ ! -e $NODE ]]; then
    echo "--- no $NODE in this boot: checking that the driver binds nothing"
    if [[ ! -e $CLIENT ]]; then pass "no client $BUS-0042 without the DT node"; else fail "$CLIENT exists without the DT node"; fi
    insmod "$KO" || { fail "insmod"; exit 1; }
    udevadm settle --timeout=10
    if [[ -z "$(find "$DRV" -maxdepth 1 -type l ! -name module)" ]]; then pass "no device bound"; else fail "something bound"; fi
    expect_probes=0
else
    echo "--- $NODE present: checking probe, attributes, errors and unbind"
    compat="$(tr -d '\0' < "$NODE/compatible")"
    if [[ $compat != edge,edge-ctrl ]]; then
        fail "node compatible '$compat': rebuild and reinstall the overlay (make -C dts), then reboot"; exit 1
    fi
    if [[ -e $CLIENT && ! -e $CLIENT/driver ]]; then pass "client $BUS-0042 exists, unbound, before insmod"; else fail "client $BUS-0042 missing or already bound"; fi
    name="$(cat "$CLIENT/name")"
    if [[ $name == edge-ctrl ]] && ! grep -q "^alias i2c:$name " "/lib/modules/$(uname -r)/modules.alias"; then
        pass "client name '$name', claimed by no installed module"
    else
        fail "client name '$name' (or another module claims it)"
    fi
    echo "    before insmod, raw 0x00..0x03: $(raw 0x00 4)  STATUS $(raw 0x30)"

    insmod "$KO" || { fail "insmod"; exit 1; }
    udevadm settle --timeout=10
    if bound; then pass "$BUS-0042 bound to edge_ctrl"; else fail "$BUS-0042 not bound"; exit 1; fi
    if ! out="$(i2cget -y "$BUS" 0x42 0x00 2>&1)" && [[ $out == *busy* ]]; then
        pass "i2cget without -f refused while bound: $out"
    else
        fail "i2cget while bound: '$out' (expected Device or resource busy)"
    fi
    show_attrs
    echo "    raw: 0x00..0x03 $(raw 0x00 4), 0x10..0x13 $(raw 0x10 4), LED $(raw 0x20), STATUS $(raw 0x30)"

    if (cd "$REPO" && EDGE_CTRL_REQUIRE=1 EDGE_CTRL_BUS="$BUS" timeout 120 \
            python3 -m unittest discover -s tests -p test_edge_ctrl_device.py >"$tmpdir/unit" 2>&1); then
        pass "device unittest as root ($(grep -E '^Ran' "$tmpdir/unit"))"
    else
        fail "device unittest"; cat "$tmpdir/unit"
    fi

    echo 1 > "$CLIENT/led"
    if [[ "$(raw 0x20)" == 0x01 ]]; then pass "echo 1 > led: LED_CONTROL reads 0x01"; else fail "LED_CONTROL after echo 1"; fi
    (( LOOK )) && check_ask "Is the Blue Pill's blue LED (PC13) ON"
    echo 0 > "$CLIENT/led"
    if [[ "$(raw 0x20)" == 0x00 ]]; then pass "echo 0 > led: LED_CONTROL reads 0x00"; else fail "LED_CONTROL after echo 0"; fi
    (( LOOK )) && check_ask "Is the LED OFF now"

    if (( UNPLUG )); then
        wait_enter "Unplug the ST-Link from the Jetson's USB (the Blue Pill loses power)"
        if ! out="$(cat "$CLIENT/device_id" 2>&1)"; then pass "board gone: device_id fails ($out)"; else fail "board gone: device_id read '$out'"; fi
        if ! out="$(cat "$CLIENT/adc" 2>&1)"; then pass "board gone: adc fails ($out)"; else fail "board gone: adc read '$out'"; fi
        echo "    same bus, ina3221 0x40 manufacturer ID: $(i2cget -f -y "$BUS" 0x40 0xfe w 2>&1)"
        wait_enter "Plug the ST-Link back in"
        for _ in $(seq 50); do [[ "$(cat "$CLIENT/device_id" 2>/dev/null)" == 0xed ]] && break; sleep 0.2; done
        if [[ "$(cat "$CLIENT/device_id" 2>&1)" == 0xed ]] && bound; then
            pass "board back: device_id 0xed again, same binding (no unbind / bind)"
        else
            fail "board back: device_id '$(cat "$CLIENT/device_id" 2>&1)'"
        fi
        st="$(cat "$CLIENT/status" 2>&1)"
        if [[ $st =~ ^0x[0-9a-f]+$ ]] && (( st & 0x80 )); then pass "status $st has RESET: the restart is visible"; else fail "status after power cycle '$st'"; fi
        echo 0xff > "$CLIENT/status"
    fi

    echo "$BUS-0042" > "$DRV/unbind"
    udevadm settle --timeout=10
    if [[ ! -e $CLIENT/adc && ! -e $CLIENT/led ]]; then pass "unbind removes the attributes"; else fail "attributes left after unbind"; fi
    echo "$BUS-0042" > "$DRV/bind"
    udevadm settle --timeout=10
    if bound && [[ "$(cat "$CLIENT/device_id")" == 0xed ]]; then pass "bind again: attributes back"; else fail "after bind"; fi
    expect_probes=2
fi

echo "edge_ctrl $DEAD" > "$ADAPTER/new_device"
udevadm settle --timeout=10
dead=/sys/bus/i2c/devices/$BUS-00${DEAD#0x}
if [[ -e $dead && ! -e $dead/driver ]]; then pass "client at $DEAD created and left unbound"; else fail "client at $DEAD bound or missing"; fi
echo "$DEAD" > "$ADAPTER/delete_device"

if ((expect_probes)); then
    out="$(python3 - "$CLIENT/adc" <<'EOF'
import errno, os, subprocess, sys
fd = os.open(sys.argv[1], os.O_RDONLY)
print("before:", os.pread(fd, 32, 0).decode().strip())
subprocess.run(["rmmod", "edge_ctrl"], check=True)
try:
    print("after:", os.pread(fd, 32, 0).decode().strip())
except OSError as e:
    print("after:", errno.errorcode[e.errno])
EOF
)"
    echo "$out" | sed 's/^/    /'
    if [[ $out == *"after: ENODEV"* ]]; then pass "file opened before rmmod reads ENODEV"; else fail "open file after rmmod: $out"; fi
else
    rmmod edge_ctrl || fail "rmmod"
fi
udevadm settle --timeout=10
if is_loaded || [[ -e $DRV ]]; then fail "driver still registered after rmmod"; else pass "module and $DRV gone"; fi
if ((expect_probes)); then
    if [[ -e $CLIENT && ! -e $CLIENT/driver && ! -e $CLIENT/adc ]]; then pass "client stays, unbound, no attributes"; else fail "client after rmmod"; fi
fi

log="$(dmesg | sed -n "/$marker/,\$p")"
if grep -Eq 'Oops|BUG:|WARNING:|Call trace' <<<"$log"; then fail "kernel warnings in dmesg"; echo "$log"; else pass "dmesg free of Oops/BUG/WARNING"; fi
probes="$(grep -c "edge_ctrl $BUS-0042: probed" <<<"$log")"
removes="$(grep -c "edge_ctrl $BUS-0042: removed" <<<"$log")"
if [[ $probes -eq $expect_probes && $removes -eq $expect_probes ]]; then
    pass "dmesg shows $probes probe / $removes remove for $BUS-0042"
else
    fail "dmesg probe/remove $probes/$removes, expected $expect_probes/$expect_probes"
fi
if grep -Eq "edge_ctrl $BUS-00${DEAD#0x}: error -(EREMOTEIO|121): cannot read DEVICE_ID" <<<"$log"; then
    pass "probe at $DEAD failed with -EREMOTEIO"
else
    fail "no -EREMOTEIO probe failure for $DEAD in dmesg"
fi
grep -E 'edge_ctrl|tegra-i2c c240000' <<<"$log" | sed 's/^/    /'

if is_loaded; then fail "module still loaded at exit"; fi
echo "=== $failures failure(s)"
[[ $failures -eq 0 ]]
