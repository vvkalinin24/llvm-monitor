#!/bin/bash
# LLVM Monitor - daily run script
# Add to cron: 0 9 * * * /home/vkalinin/llvm-monitor/run_monitor.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Activate venv if present
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Create reports directory
mkdir -p reports

# Run monitor (report is auto-saved to reports/)
python3 llvm_monitor.py

echo "Done. Report saved to: reports/"
