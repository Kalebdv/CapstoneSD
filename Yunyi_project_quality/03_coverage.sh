#!/usr/bin/env bash
# M5b unit-test coverage for ComfyUI at commit c194dd00.
# Needs a venv with CPU torch (NO triton), the repo requirements, the test
# requirements, and coverage==7.6.1. tests-unit is the CPU suite (CI runs it on
# CPU); inference/execution GPU suites are intentionally excluded.
set -euo pipefail
COMFY="${1:?usage: 03_coverage.sh <comfyui_dir> <venv_bin>}"
BIN="${2:?pass the venv bin dir, e.g. .venv/bin}"
SRC="comfy,comfy_execution,comfy_api,comfy_api_nodes,comfy_config,comfy_extras,app,api_server,middleware,utils"
cd "$COMFY"
"$BIN/coverage" run --branch --source="$SRC" -m pytest tests-unit -q -p no:cacheprovider -o addopts=""
"$BIN/coverage" report | tail -1
