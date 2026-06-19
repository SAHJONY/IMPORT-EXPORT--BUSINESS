#!/usr/bin/env bash
set -euo pipefail

# Directory where this script resides
BASE_DIR=$(dirname "$(realpath "$0")")
REPORTS_DIR="$BASE_DIR/reports"
mkdir -p "$REPORTS_DIR"

# Helper to run a sub‑agent via Hermes delegating a single task
run_subagent() {
    local name="$1"
    local script="$2"
    local out_file="$REPORTS_DIR/${name}_report.md"
    echo "Running $name sub‑agent..."
    hermes delegate_task --tasks "[{\"goal\":\"Execute $name workflow and write a concise report to $out_file\",\"context\":\"$script is located at $BASE_DIR/$script. The script contains all commands needed for this step.\",\"toolsets\":[\"terminal\",\"browser\",\"search\",\"file\"]}]"
    # The sub‑agent writes its report directly; we just wait a moment for it to finish
    sleep 2
}

run_subagent "legal" "legal.sh"
run_subagent "procurement" "procurement.sh"
run_subagent "logistics" "logistics.sh"
run_subagent "sales" "sales.sh"

echo "All sub‑agents completed. Reports are in $REPORTS_DIR"
