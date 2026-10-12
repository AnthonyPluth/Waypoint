#!/usr/bin/env bash
set -eo pipefail
cpus="$(nproc 2>/dev/null || getconf _NPROCESSORS_ONLN 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)"
floor=4
cap=16
jobs=$(( cpus < floor ? floor : cpus > cap ? cap : cpus ))
echo "$jobs"
