#!/usr/bin/env bash
# Step 10-a acceptance: build edge_oled.ko, bind it to the SSD1306 OLED and draw through
# /dev/edge_oled with build/edge_oled_ctl.
# Usage: sudo bash scripts/verify_edge_oled.sh [--no-unplug]
#
# The OLED answers on c240000.i2c (header pins 27/28, found by name) at 0x3c. The SSD1306
# cannot be read back over I2C, so a person at the board answers y/n for what the panel shows.
# The result depends on whether this boot has the overlay with the oled@3c node
# (make -C dts, install, reboot):
#   no node      -> no client <bus>-003c exists, insmod must not bind anything
#   node present -> the panel is first scrambled from userspace (oled_probe EDGE + inverse);
#                   probe must leave it dark (its own init + clear). Then clear / fill /
#                   pattern / pixel / edge from userspace, the device unit tests, oled_probe
#                   refused while bound, unbind with a file open (ENODEV, display off), bind
#                   again, and (unless --no-unplug) all four wires off while bound: the write
#                   must fail with Remote I/O error and, once reconnected, the next write must
#                   bring the panel up again by itself.
# Both modes also instantiate a client at 0x3d (nobody answers): probe() must fail.
# Exit status: 0 = all checks passed, 1 = a check failed, 2 = environment/usage problem.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MOD_DIR="$REPO/kernel/edge_oled"
KO="$MOD_DIR/edge_oled.ko"
CTL="$REPO/build/edge_oled_ctl"
PROBE="$REPO/build/oled_probe"
DRV=/sys/bus/i2c/drivers/edge_oled
DEV=/dev/edge_oled
NODE=/proc/device-tree/bus@0/i2c@c240000/oled@3c
DEAD=0x3d
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
[[ $EUID -eq 0 ]] || die "run as root: sudo bash scripts/verify_edge_oled.sh"
for c in i2cdetect i2ctransfer; do
    command -v $c >/dev/null || die "$c missing (apt install i2c-tools)"
done
# /dev/tty is mode 666 even without a controlling terminal; only opening it tells.
{ : </dev/tty; } 2>/dev/null || die "needs a terminal: a person answers what the OLED shows"
BUILD_USER="${SUDO_USER:-root}"

BUS="$(i2cdetect -l | awk '$3 == "c240000.i2c" { sub("i2c-", "", $1); print $1 }')"
[[ -n $BUS ]] || die "no c240000.i2c adapter in i2cdetect -l"
ADAPTER=/sys/bus/i2c/devices/i2c-$BUS
CLIENT=/sys/bus/i2c/devices/$BUS-003c
DEAD_CLIENT=/sys/bus/i2c/devices/$BUS-00${DEAD#0x}

is_loaded() { grep -q '^edge_oled ' /proc/modules; }
# Checked before the EXIT trap exists, so a module the user loaded is left alone.
is_loaded && die "edge_oled already loaded; rmmod edge_oled first"

tmpdir="$(mktemp -d)"
UNPLUGGED=0
cleanup() {
    [[ -e $DEAD_CLIENT ]] && echo "$DEAD" > "$ADAPTER/delete_device"
    rm -rf "$tmpdir"
    if is_loaded; then rmmod edge_oled || echo "WARN cleanup rmmod failed" >&2; fi
}
trap cleanup EXIT
trap '[[ $UNPLUGGED -eq 1 ]] && echo ">>> Interrupted: reconnect the OLED."; exit 2' INT TERM

bound() { [[ "$(readlink -f "$CLIENT/driver" 2>/dev/null)" == "$(readlink -f $DRV)" ]]; }
# i2cdetect cell for 0x3c: "3c" = answers, "UU" = a driver owns the address.
cell3c() { i2cdetect -y -r "$BUS" | awk '$1 == "30:" { print $14 }'; }
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
    echo "    $out"
    if [[ $rc -ne 0 ]]; then fail "edge_oled_ctl $*: exit $rc"; return; fi
    if ask "$q"; then pass "ctl $*: $q"; else fail "ctl $*: person answered no to '$q'"; fi
}

if timeout 300 sudo -u "$BUILD_USER" make -C "$MOD_DIR" >/dev/null 2>&1; then
    pass "build edge_oled.ko"
else
    fail "build edge_oled.ko"; exit 1
fi
if timeout 300 sudo -u "$BUILD_USER" sh -c "cmake -S '$REPO' -B '$REPO/build' >/dev/null && cmake --build '$REPO/build' --target edge_oled_ctl oled_probe test_edge_oled_proto >/dev/null"; then
    pass "build edge_oled_ctl, oled_probe, test_edge_oled_proto (CMake)"
else
    fail "build (CMake)"; exit 1
fi
if "$REPO/build/test_edge_oled_proto" >/dev/null; then pass "protocol vectors (driver bytes = Step 9's)"; else fail "protocol vectors"; fi
vermagic="$(modinfo -F vermagic "$KO" | awk '{ print $1 }')"
if [[ $vermagic == "$(uname -r)" ]]; then pass "vermagic matches running kernel"; else fail "vermagic '$vermagic'"; fi
echo "    bus: c240000.i2c = i2c-$BUS"

marker="edge_oled verify $$ $(date +%s)"
echo "$marker" > /dev/kmsg

if [[ ! -e $NODE ]]; then
    echo "--- no $NODE in this boot: checking that the driver binds nothing"
    if [[ ! -e $CLIENT ]]; then pass "no client $BUS-003c without the DT node"; else fail "$CLIENT exists without the DT node"; fi
    insmod "$KO" || { fail "insmod"; exit 1; }
    udevadm settle --timeout=10
    if [[ -d $DRV ]]; then pass "driver registered on the i2c bus"; else fail "$DRV missing"; fi
    if [[ -z "$(find "$DRV" -maxdepth 1 -type l ! -name module)" && ! -e $DEV ]]; then pass "no device bound, no $DEV"; else fail "something bound"; fi
    expect_probes=0
else
    echo "--- NODE present ($NODE): probe, drawing from userspace, unbind"
    echo "    DT node: compatible '$(tr -d '\0' < "$NODE/compatible")', reg $(od -An -tx1 "$NODE/reg" | tr -s ' ')"
    if [[ -e $CLIENT && ! -e $CLIENT/driver ]]; then pass "client $BUS-003c exists, unbound, before insmod"; else fail "client $BUS-003c missing or already bound"; fi
    name="$(cat "$CLIENT/name" 2>/dev/null)"
    if [[ $name == edge-ssd1306 ]]; then pass "client name '$name' (compatible minus vendor prefix)"; else fail "client name '$name'"; fi
    if grep -q "^alias i2c:$name " "/lib/modules/$(uname -r)/modules.alias"; then fail "another module claims i2c:$name"; else pass "no installed module claims i2c:$name"; fi

    # A known, wrong state from userspace: probe must undo the inverse and clear the RAM.
    echo "== before insmod: EDGE from oled_probe, then inverse (0xA7) with i2ctransfer"
    if "$PROBE" --bus "$BUS" edge >/dev/null && i2ctransfer -y "$BUS" w2@0x3c 0x00 0xA7; then
        if ask "Before insmod: black EDGE on a white panel?"; then pass "panel scrambled before insmod"; else fail "scramble not seen"; fi
    else
        fail "could not scramble the panel from userspace"
    fi

    insmod "$KO" || { fail "insmod"; exit 1; }
    udevadm settle --timeout=10
    if bound; then pass "$BUS-003c bound to edge_oled"; else fail "$BUS-003c not bound"; exit 1; fi
    if ask "After insmod: is the panel completely dark (no white, no EDGE)?"; then pass "probe: init (normal, not inverse) + clear"; else fail "panel after probe"; fi
    if [[ "$(cell3c)" == UU ]]; then pass "i2cdetect shows UU at 0x3c"; else fail "i2cdetect cell 0x3c is '$(cell3c)'"; fi
    if [[ -c $DEV && "$(stat -c %a $DEV)" == 666 ]]; then pass "$DEV is a char device, mode 666"; else fail "$DEV: $(ls -l $DEV 2>&1)"; fi

    echo "== drawing from userspace"
    show "Every pixel lit (whole panel white)?" fill 0xff
    show "Border plus a diagonal from the TOP-LEFT corner?" pattern
    show "Five dots: the four corners and the centre?" pixel
    show "White EDGE on black, centred, readable (not mirrored, not upside down)?" edge
    show "Completely dark?" clear

    if (cd "$REPO" && timeout 120 sudo -u "$BUILD_USER" env EDGE_OLED_REQUIRE=1 EDGE_OLED_BUS="$BUS" \
            python3 -m unittest discover -s tests -p test_edge_oled_device.py -v >"$tmpdir/unit" 2>&1); then
        pass "device unittest as $BUILD_USER ($(grep -E '^Ran' "$tmpdir/unit"); $(grep -o '[0-9.]* ms per frame' "$tmpdir/unit"))"
    else
        fail "device unittest as $BUILD_USER"; cat "$tmpdir/unit"
    fi

    # Step 9 review: oled_probe uses I2C_RDWR (no EBUSY) and would re-init under the driver.
    if ! out="$("$PROBE" --bus "$BUS" edge 2>&1)" && [[ $out == *"bound to driver edge_oled"* ]]; then
        pass "oled_probe without --force refused: $out"
    else
        fail "oled_probe while bound: '$out'"
    fi

    # Unbind while a file is open: the struct outlives the binding, the file gets ENODEV.
    ctl edge >/dev/null
    out="$(python3 - "$DEV" "$DRV/unbind" "$BUS-003c" <<'EOF'
import errno, os, sys
fd = os.open(sys.argv[1], os.O_RDWR)
with open(sys.argv[2], "w") as f:
    f.write(sys.argv[3])
for name, op in (("write", lambda: os.write(fd, bytes(1024))), ("read", lambda: os.pread(fd, 1024, 0))):
    try:
        op()
        print(name, "OK")
    except OSError as e:
        print(name, errno.errorcode[e.errno])
os.close(fd)
EOF
)"
    echo "$out" | sed 's/^/    /'
    if [[ $out == *"write ENODEV"*"read ENODEV"* ]]; then pass "file opened before unbind: write/read ENODEV"; else fail "open file after unbind: $out"; fi
    udevadm settle --timeout=10
    if [[ ! -e $DEV ]] && ! bound; then pass "unbind removes $DEV"; else fail "$DEV or binding still there"; fi
    if ask "After unbind: panel dark (driver turned the display off)?"; then pass "remove: display off"; else fail "panel after unbind"; fi
    echo "$BUS-003c" > "$DRV/bind"
    udevadm settle --timeout=10
    if bound && [[ -c $DEV ]]; then pass "bind again: $DEV back"; else fail "after bind: $(ls -l $DEV 2>&1)"; fi
    show "After bind: EDGE again?" edge

    if ((UNPLUG)); then
        echo "== OLED off while bound (--no-unplug skips this)"
        UNPLUGGED=1
        wait_enter "Disconnect all four wires of the OLED (VCC, GND, SDA, SCL)"
        # A different picture than the one on the panel (EDGE): the write fails, and read()
        # must still return EDGE, the last frame that got through (PR #14 review).
        out="$(ctl pattern 2>&1)"; rc=$?
        echo "    $out"
        if [[ $rc -eq 1 && $out == *"Remote I/O error"* ]]; then pass "write with the OLED unplugged: Remote I/O error"; else fail "unplugged write: exit $rc"; fi
        : > "$tmpdir/edge.bin" && ctl --dev "$tmpdir/edge.bin" edge >/dev/null
        if cmp -s "$DEV" "$tmpdir/edge.bin"; then pass "read() after the failed write: still the last frame sent (EDGE)"; else fail "read() after the failed write is not the last frame sent"; fi
        wait_enter "Reconnect all four wires"
        UNPLUGGED=0
        if ask "Reconnected: panel dark (power-on reset) before anything is sent?"; then pass "power-on reset seen"; else fail "panel not dark after reconnect: not a real power cycle"; fi
        show "EDGE back (driver re-sent the init sequence by itself)?" edge
    else
        echo "SKIP unplug while bound (--no-unplug)"
    fi
    expect_probes=2
fi

# A client where nobody answers: probe() sends the init sequence, gets no ACK and must fail.
if [[ "$(i2cdetect -y -r "$BUS" "$DEAD" "$DEAD" | awk 'NR > 1 { for (i = 2; i <= NF; i++) if ($i != "--") f = 1 } END { print f + 0 }')" == 0 ]]; then
    echo "edge_oled $DEAD" > "$ADAPTER/new_device"
    udevadm settle --timeout=10
    if [[ -e $DEAD_CLIENT && ! -e $DEAD_CLIENT/driver ]]; then pass "client at $DEAD created and left unbound"; else fail "client at $DEAD bound or missing"; fi
    echo "$DEAD" > "$ADAPTER/delete_device"
    dead_tested=1
else
    echo "SKIP something answers at $DEAD on i2c-$BUS"
    dead_tested=0
fi

rmmod edge_oled || fail "rmmod"
udevadm settle --timeout=10
if is_loaded || [[ -e $DRV || -e $DEV ]]; then fail "driver or $DEV still there after rmmod"; else pass "module, $DRV and $DEV gone"; fi
if ((expect_probes)); then
    if [[ -e $CLIENT && ! -e $CLIENT/driver ]]; then pass "client stays, unbound"; else fail "client after rmmod"; fi
    if [[ "$(cell3c)" == 3c ]]; then pass "i2cdetect shows 3c again"; else fail "i2cdetect cell 0x3c is '$(cell3c)'"; fi
fi

log="$(dmesg | sed -n "/$marker/,\$p")"
if grep -Eq 'Oops|BUG:|WARNING:|Call trace' <<<"$log"; then fail "kernel warnings in dmesg"; echo "$log"; else pass "dmesg free of Oops/BUG/WARNING"; fi
probes="$(grep -c "edge_oled $BUS-003c: probed" <<<"$log")"
removes="$(grep -c "edge_oled $BUS-003c: removed" <<<"$log")"
if [[ $probes -eq $expect_probes && $removes -eq $expect_probes ]]; then
    pass "dmesg shows $probes probe / $removes remove for $BUS-003c"
else
    fail "dmesg probe/remove $probes/$removes, expected $expect_probes/$expect_probes"
fi
if ((dead_tested)); then
    if grep -Eq "edge_oled $BUS-00${DEAD#0x}: error -(EREMOTEIO|121): cannot initialise the panel" <<<"$log"; then
        pass "probe at $DEAD failed with -EREMOTEIO"
    else
        fail "no -EREMOTEIO probe failure for $DEAD in dmesg"
    fi
fi
grep 'edge_oled' <<<"$log" | sed 's/^/    /'

echo "=== $failures failure(s)"
[[ $failures -eq 0 ]]
