#!/usr/bin/env bash
# Load edge_test.ko from this directory (needs root).
set -euo pipefail
insmod "$(dirname "${BASH_SOURCE[0]}")/edge_test.ko"
