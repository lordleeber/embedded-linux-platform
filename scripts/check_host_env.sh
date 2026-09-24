#!/usr/bin/env bash
# Step 1: inspect the Jetson target without changing system configuration.
set -u

usage() {
    printf 'Usage: %s [--record FILE]\n' "$0" >&2
    exit 2
}

record=''
if (( $# == 2 )) && [[ $1 == --record && -n $2 ]]; then
    record=$2
elif (( $# != 0 )); then
    usage
fi

# Used by the fixture tests; ordinary runs inspect the live filesystem.
root=${CHECK_HOST_ENV_ROOT:-/}
root=${root%/}
failed=0

file_line() {
    local line=''
    if [[ -r $1 ]]; then
        IFS= read -r line < "$1" || :
    fi
    printf '%s' "$line"
}

os_release='unavailable'
if [[ -r $root/etc/os-release ]]; then
    while IFS= read -r line; do
        if [[ $line == PRETTY_NAME=* ]]; then
            os_release=${line#PRETTY_NAME=}
            os_release=${os_release#\"}
            os_release=${os_release%\"}
            break
        fi
    done < "$root/etc/os-release"
fi

kernel=$(uname -r)
arch=$(uname -m)
full_uname=$(uname -a)
l4t=$(file_line "$root/etc/nv_tegra_release")
[[ -n $l4t ]] || l4t='unavailable'
model=''
if [[ -r $root/proc/device-tree/model ]]; then
    IFS= read -r -d '' model < "$root/proc/device-tree/model" || :
fi
[[ -n $model ]] || model='unavailable'
headers=$root/lib/modules/$kernel/build
has_headers() { [[ -d $headers ]]; }
jetpack='unavailable (nvidia-jetpack package not installed or dpkg-query missing)'
if command -v dpkg-query >/dev/null 2>&1; then
    version=$(dpkg-query -W -f='${Version}' nvidia-jetpack 2>/dev/null) || version=''
    [[ -z $version ]] || jetpack=$version
fi

snapshot() {
    printf 'Board model: %s\n' "$model"
    printf 'Architecture: %s\n' "$arch"
    printf 'uname -a: %s\n' "$full_uname"
    printf 'OS: %s\n' "$os_release"
    printf '%s\n' 'os-release contents:'
    if [[ -r $root/etc/os-release ]]; then
        while IFS= read -r line || [[ -n $line ]]; do
            printf '%s\n' "$line"
        done < "$root/etc/os-release"
    else
        printf '%s\n' 'unavailable'
    fi
    printf 'L4T: %s\n' "$l4t"
    printf 'JetPack package: %s\n' "$jetpack"
    printf 'Kernel headers path: %s\n' "$headers"
    if has_headers; then
        printf '%s\n' 'Kernel headers present: yes'
    else
        printf '%s\n' 'Kernel headers present: no'
    fi
}

printf '%s\n' '== Jetson target =='
snapshot

check() {
    local label=$1
    shift
    if "$@"; then
        printf 'PASS %s\n' "$label"
    else
        printf 'FAIL %s\n' "$label"
        failed=1
    fi
}

available() { command -v "$1" >/dev/null 2>&1; }
present() { [[ $1 != unavailable ]]; }
nonempty() { [[ -n $1 ]]; }

printf '\n%s\n' '== Platform checks =='
check 'board model' present "$model"
check 'L4T release' present "$l4t"
check 'OS release' present "$os_release"
check 'architecture' nonempty "$arch"
check 'kernel release' nonempty "$kernel"
check 'kernel headers' has_headers

printf '\n%s\n' '== Required tools =='
for tool in gcc g++ cmake make git dtc i2cdetect v4l2-ctl; do
    check "$tool" available "$tool"
done

if [[ -n $record ]]; then
    if snapshot > "$record"; then
        printf '\nRecorded platform snapshot: %s\n' "$record"
    else
        printf 'FAIL writing snapshot: %s\n' "$record" >&2
        exit 2
    fi
fi

exit "$failed"
