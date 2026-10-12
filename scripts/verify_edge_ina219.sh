#!/usr/bin/env bash
# Step 7 acceptance: build edge_ina219.ko, bind it to the INA219 and compare with ina219_raw.
# Usage: sudo bash scripts/verify_edge_ina219.sh
#
# The UPS Power Module (C) INA219 answers on the header I2C bus (c250000.i2c) at 0x41.
# The result depends on whether this boot has the overlay with the ina219@41 node
# (make -C dts, install, reboot):
#   no node      -> no client <bus>-0041 exists, insmod must not bind anything
#   node present -> client exists unbound before insmod; insmod binds it, Config/Cal are the
#                   sample's, the sysfs values match ina219_raw, rmmod unbinds it
# Both modes also instantiate a client at 0x45 (nobody answers): probe() must fail.
# Exit status: 0 = all checks passed, 1 = a check failed, 2 = environment/usage problem.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MOD_DIR="$REPO/kernel/edge_ina219"
KO="$MOD_DIR/edge_ina219.ko"
RAW="$REPO/build/ina219_raw"
DRV=/sys/bus/i2c/drivers/edge_ina219
NODE=/proc/device-tree/bus@0/i2c@c250000/ina219@41
DEAD=0x45
failures=0

pass() { echo "PASS $*"; }
fail() { echo "FAIL $*"; failures=$((failures + 1)); }
die()  { echo "ERROR $*" >&2; exit 2; }

[[ $# -eq 0 ]] || die "usage: $0"
[[ $EUID -eq 0 ]] || die "run as root: sudo bash scripts/verify_edge_ina219.sh"
command -v i2cdetect >/dev/null || die "i2cdetect missing (apt install i2c-tools)"
BUILD_USER="${SUDO_USER:-root}"

BUS="$(i2cdetect -l | awk '$3 == "c250000.i2c" { sub("i2c-", "", $1); print $1 }')"
[[ -n $BUS ]] || die "no c250000.i2c adapter in i2cdetect -l"
ADAPTER=/sys/bus/i2c/devices/i2c-$BUS
CLIENT=/sys/bus/i2c/devices/$BUS-0041

is_loaded() { grep -q '^edge_ina219 ' /proc/modules; }
# Checked before the EXIT trap exists, so a module the user loaded is left alone.
is_loaded && die "edge_ina219 already loaded; rmmod edge_ina219 first"

tmpdir="$(mktemp -d)"
cleanup() {
    [[ -e /sys/bus/i2c/devices/$BUS-00${DEAD#0x} ]] && echo "$DEAD" > "$ADAPTER/delete_device"
    rm -rf "$tmpdir"
    if is_loaded; then rmmod edge_ina219 || echo "WARN cleanup rmmod failed" >&2; fi
}
trap cleanup EXIT
trap 'exit 2' INT TERM

bound() { [[ "$(readlink -f "$CLIENT/driver" 2>/dev/null)" == "$(readlink -f $DRV)" ]]; }
# i2cdetect cell for 0x41: "41" = answers, "UU" = a driver owns the address.
cell41() { i2cdetect -y -r "$BUS" | awk '$1 == "40:" { print $3 }'; }

if timeout 300 sudo -u "$BUILD_USER" make -C "$MOD_DIR" >/dev/null 2>&1; then
    pass "build edge_ina219.ko"
else
    fail "build edge_ina219.ko"; exit 1
fi
if timeout 300 sudo -u "$BUILD_USER" sh -c "cmake -S '$REPO' -B '$REPO/build' >/dev/null && cmake --build '$REPO/build' --target ina219_raw test_edge_ina219_conv >/dev/null"; then
    pass "build ina219_raw, test_edge_ina219_conv (CMake)"
else
    fail "build ina219_raw (CMake)"; exit 1
fi
if "$REPO/build/test_edge_ina219_conv" >/dev/null; then pass "conversion vectors"; else fail "conversion vectors"; fi
vermagic="$(modinfo -F vermagic "$KO" | awk '{ print $1 }')"
if [[ $vermagic == "$(uname -r)" ]]; then pass "vermagic matches running kernel"; else fail "vermagic '$vermagic'"; fi
echo "    bus: c250000.i2c = i2c-$BUS"

marker="edge_ina219 verify $$ $(date +%s)"
echo "$marker" > /dev/kmsg

if [[ ! -e $NODE ]]; then
    echo "--- no $NODE in this boot: checking that the driver binds nothing"
    if [[ ! -e $CLIENT ]]; then pass "no client $BUS-0041 without the DT node"; else fail "$CLIENT exists without the DT node"; fi
    insmod "$KO" || { fail "insmod"; exit 1; }
    udevadm settle --timeout=10
    if [[ -d $DRV ]]; then pass "driver registered on the i2c bus"; else fail "$DRV missing"; fi
    if [[ -z "$(find "$DRV" -maxdepth 1 -type l ! -name module)" ]]; then pass "no device bound"; else fail "something bound"; fi
    expect_probes=0
else
    echo "--- $NODE present: checking probe, sysfs values and unbind"
    echo "    DT node: compatible '$(tr -d '\0' < "$NODE/compatible")', reg $(od -An -tx1 "$NODE/reg" | tr -s ' ')"
    if [[ -e $CLIENT && ! -e $CLIENT/driver ]]; then pass "client $BUS-0041 exists, unbound, before insmod"; else fail "client $BUS-0041 missing or already bound"; fi
    if [[ "$(tr -d '\0' < "$NODE/compatible")" != edge,edge-ina219 ]]; then
        fail "node compatible is not edge,edge-ina219: rebuild and reinstall the overlay (make -C dts), then reboot"
        exit 1
    fi
    # The I2C core names the client after the compatible minus the vendor prefix and also
    # matches that name against every driver's i2c_device_id table: it must not be "ina219",
    # which the upstream ina2xx driver lists.
    name="$(cat "$CLIENT/name")"
    if [[ $name == edge-ina219 ]]; then pass "client name '$name' (compatible minus vendor prefix)"; else fail "client name '$name'"; fi
    if grep -q "^alias i2c:$name " "/lib/modules/$(uname -r)/modules.alias"; then
        fail "another module claims i2c:$name"
    else
        pass "no installed module claims i2c:$name"
    fi
    if "$RAW" --bus "$BUS" >"$tmpdir/raw0"; then
        echo "    before insmod: $(grep -E '^0x0[05]' "$tmpdir/raw0" | tr -s ' \n' ' ')"
    fi

    insmod "$KO" || { fail "insmod"; exit 1; }
    udevadm settle --timeout=10
    if bound; then pass "$BUS-0041 bound to edge_ina219"; else fail "$BUS-0041 not bound"; fi
    if [[ "$(cell41)" == UU ]]; then pass "i2cdetect shows UU at 0x41"; else fail "i2cdetect cell 0x41 is '$(cell41)'"; fi
    # i2c-dev's I2C_SLAVE refuses an address a driver owns; I2C_RDWR (ina219_raw) does not check.
    if ! out="$(i2cget -y "$BUS" 0x41 0x00 w 2>&1)" && [[ $out == *busy* ]]; then
        pass "i2cget without -f refused while bound: $out"
    else
        fail "i2cget while bound: '$out' (expected Device or resource busy)"
    fi

    for a in registers bus_mv shunt_uv current_ua power_uw; do
        printf '    %-11s %s\n' "$a" "$(cat "$CLIENT/$a" 2>&1)"
    done
    if "$RAW" --bus "$BUS" >"$tmpdir/raw1"; then
        pass "ina219_raw still reads with the driver bound"
        sed 's/^/    /' "$tmpdir/raw1"
    else
        fail "ina219_raw with the driver bound"
    fi

    if (cd "$REPO" && timeout 60 sudo -u "$BUILD_USER" env EDGE_INA219_REQUIRE=1 EDGE_INA219_BUS="$BUS" \
            python3 -m unittest discover -s tests -p test_edge_ina219_device.py >"$tmpdir/unit" 2>&1); then
        pass "device unittest as $BUILD_USER ($(grep -E '^Ran' "$tmpdir/unit"))"
    else
        fail "device unittest as $BUILD_USER"; cat "$tmpdir/unit"
    fi
    expect_probes=1
fi

# A client where nobody answers: probe() reads Config, gets no ACK and must fail.
echo "edge_ina219 $DEAD" > "$ADAPTER/new_device"
udevadm settle --timeout=10
dead=/sys/bus/i2c/devices/$BUS-00${DEAD#0x}
if [[ -e $dead && ! -e $dead/driver ]]; then pass "client at $DEAD created and left unbound"; else fail "client at $DEAD bound or missing"; fi
echo "$DEAD" > "$ADAPTER/delete_device"

rmmod edge_ina219 || fail "rmmod"
udevadm settle --timeout=10
if is_loaded || [[ -e $DRV ]]; then fail "driver still registered after rmmod"; else pass "module and $DRV gone"; fi
if ((expect_probes)); then
    if [[ -e $CLIENT && ! -e $CLIENT/driver && ! -e $CLIENT/bus_mv ]]; then
        pass "client stays, unbound, attributes gone"
    else
        fail "client after rmmod: $(ls "$CLIENT" 2>&1 | tr '\n' ' ')"
    fi
    if [[ "$(cell41)" == 41 ]]; then pass "i2cdetect shows 41 again"; else fail "i2cdetect cell 0x41 is '$(cell41)'"; fi
fi

log="$(dmesg | sed -n "/$marker/,\$p")"
if grep -Eq 'Oops|BUG:|WARNING:|Call trace' <<<"$log"; then fail "kernel warnings in dmesg"; echo "$log"; else pass "dmesg free of Oops/BUG/WARNING"; fi
probes="$(grep -c "edge_ina219 $BUS-0041: probed" <<<"$log")"
removes="$(grep -c "edge_ina219 $BUS-0041: removed" <<<"$log")"
if [[ $probes -eq $expect_probes && $removes -eq $expect_probes ]]; then
    pass "dmesg shows $probes probe / $removes remove for $BUS-0041"
else
    fail "dmesg probe/remove $probes/$removes, expected $expect_probes/$expect_probes"
fi
if grep -Eq "edge_ina219 $BUS-00${DEAD#0x}: error -(EREMOTEIO|121): cannot read Config" <<<"$log"; then
    pass "probe at $DEAD failed with -EREMOTEIO"
else
    fail "no -EREMOTEIO probe failure for $DEAD in dmesg"
fi
grep 'edge_ina219' <<<"$log" | sed 's/^/    /'

if is_loaded; then fail "module still loaded at exit"; fi
echo "=== $failures failure(s)"
[[ $failures -eq 0 ]]
