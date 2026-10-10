#!/usr/bin/env bash
# Step 2 acceptance: build edge_test.ko, then load/test/unload it several times.
# Usage: sudo bash scripts/verify_edge_test.sh [cycles]
# Exit status: 0 = all checks passed, 1 = a check failed, 2 = environment/usage problem.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MOD_DIR="$REPO/kernel/edge_test"
KO="$MOD_DIR/edge_test.ko"
BUILD_DIR="$REPO/build"
CLI="$BUILD_DIR/edge_test_cli"
DEV=/dev/edge_test
CYCLES="${1:-3}"
failures=0

pass() { echo "PASS $*"; }
fail() { echo "FAIL $*"; failures=$((failures + 1)); }
die()  { echo "ERROR $*" >&2; exit 2; }

[[ $EUID -eq 0 ]] || die "run as root: sudo bash scripts/verify_edge_test.sh"
[[ $CYCLES =~ ^[1-9][0-9]*$ ]] || die "cycles must be a positive integer"

# Build as the invoking user so root-owned objects are not left in the tree.
BUILD_USER="${SUDO_USER:-root}"

outfile="$(mktemp)"   # root writes test output here: never a guessable /tmp name
cleanup() {
    rm -f "$outfile"
    if grep -q '^edge_test ' /proc/modules; then
        rmmod edge_test || echo "WARN cleanup rmmod failed" >&2
    fi
}
trap cleanup EXIT
trap 'exit 2' INT TERM

is_loaded() { grep -q '^edge_test ' /proc/modules; }
proc_major() { awk '$2 == "edge_test" { print $1 }' /proc/devices; }

is_loaded && die "edge_test already loaded; run kernel/edge_test/unload.sh first"

if timeout 300 sudo -u "$BUILD_USER" make -C "$MOD_DIR" >/dev/null; then
    pass "build edge_test.ko"
else
    fail "build edge_test.ko"
    exit 1
fi

vermagic="$(modinfo -F vermagic "$KO" | awk '{ print $1 }')"
if [[ $vermagic == "$(uname -r)" ]]; then
    pass "vermagic matches running kernel ($vermagic)"
else
    fail "vermagic '$vermagic' != running kernel '$(uname -r)'"
fi

# Step 3: userspace CLI and C++ ioctl test, built as the invoking user.
if timeout 300 sudo -u "$BUILD_USER" sh -c "cmake -S '$REPO' -B '$BUILD_DIR' >/dev/null && cmake --build '$BUILD_DIR' >/dev/null"; then
    pass "build edge_test_cli and test_edge_device (CMake)"
else
    fail "build edge_test_cli and test_edge_device (CMake)"
    exit 1
fi

marker="edge_test verify $$ $(date +%s)"
echo "$marker" > /dev/kmsg

for ((i = 1; i <= CYCLES; i++)); do
    echo "--- cycle $i/$CYCLES"
    if ! timeout 10 bash "$MOD_DIR/load.sh"; then
        fail "cycle $i: insmod"
        break
    fi
    udevadm settle --timeout=10

    major="$(proc_major)"
    if [[ -n $major ]]; then pass "cycle $i: /proc/devices major $major"; else fail "cycle $i: /proc/devices"; fi

    if [[ -c $DEV && "$(stat -c '%t' "$DEV")" == "$(printf '%x' "${major:-0}")" ]]; then
        pass "cycle $i: $DEV is char device with major $major"
    else
        fail "cycle $i: $DEV missing or wrong major"
    fi

    # Step 3: the ioctl value lives in the module, so a reload starts from 0.
    if ((i > 1)); then
        got="$(timeout 10 "$CLI" get 2>&1)"
        if [[ $got == 0 ]]; then pass "cycle $i: ioctl value reset to 0 after reload"; else fail "cycle $i: value after reload is '$got', expected 0"; fi
    fi

    if (cd "$REPO" && EDGE_TEST_REQUIRE=1 timeout 60 python3 -m unittest discover -s tests -p test_edge_test_device.py >"$outfile" 2>&1); then
        pass "cycle $i: device unittest (root)"
    else
        fail "cycle $i: device unittest (root)"; cat "$outfile"
    fi

    if [[ $BUILD_USER != root ]]; then
        out="$(timeout 10 sudo -u "$BUILD_USER" sh -c "echo hello > $DEV && cat $DEV")"
        if [[ $out == hello ]]; then pass "cycle $i: echo/cat as $BUILD_USER"; else fail "cycle $i: echo/cat as $BUILD_USER got '$out'"; fi
    fi

    if EDGE_TEST_REQUIRE=1 timeout 30 "$BUILD_DIR/test_edge_device" >"$outfile" 2>&1; then
        pass "cycle $i: C++ ioctl test (root)"
    else
        fail "cycle $i: C++ ioctl test (root)"; cat "$outfile"
    fi

    # Run as the invoking user so the CLI test's CMake step cannot leave root-owned files in build/.
    if (cd "$REPO" && timeout 120 sudo -u "$BUILD_USER" env EDGE_TEST_REQUIRE=1 python3 -m unittest discover -s tests -p test_edge_test_cli.py >"$outfile" 2>&1); then
        pass "cycle $i: CLI tests as $BUILD_USER"
    else
        fail "cycle $i: CLI tests as $BUILD_USER"; cat "$outfile"
    fi

    timeout 10 "$CLI" set 4242 >/dev/null || fail "cycle $i: set 4242 before unload"

    if ! timeout 10 bash "$MOD_DIR/unload.sh"; then
        fail "cycle $i: rmmod"
        break
    fi
    udevadm settle --timeout=10

    if is_loaded || [[ -e $DEV ]] || [[ -n "$(proc_major)" ]] || [[ -e /sys/class/edge_test ]]; then
        fail "cycle $i: leftovers after rmmod (module, $DEV, /proc/devices or /sys/class)"
    else
        pass "cycle $i: clean after rmmod"
    fi
done

log="$(dmesg | sed -n "/$marker/,\$p")"
if grep -Eq 'Oops|BUG:|WARNING:|Call trace' <<<"$log"; then
    fail "kernel warnings in dmesg"; echo "$log"
else
    pass "dmesg free of Oops/BUG/WARNING"
fi
loads="$(grep -c 'edge_test: registered' <<<"$log")"
unloads="$(grep -c 'edge_test: unregistered' <<<"$log")"
if [[ $loads -eq $CYCLES && $unloads -eq $CYCLES ]]; then
    pass "dmesg shows $loads load / $unloads unload messages"
else
    fail "dmesg load/unload count $loads/$unloads, expected $CYCLES/$CYCLES"
fi
echo "$log" | grep 'edge_test' | tail -n 4

if is_loaded; then fail "module still loaded at exit"; fi
echo "=== $failures failure(s)"
[[ $failures -eq 0 ]]
