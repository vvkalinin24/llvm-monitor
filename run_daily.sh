#!/bin/bash
# LLVM Monitor - Daily cron job
# Runs the multi-agent monitoring system

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Log file
LOG_FILE="$SCRIPT_DIR/logs/monitor_$(date +%Y-%m-%d).log"
mkdir -p "$SCRIPT_DIR/logs"

echo "=== LLVM Monitor started at $(date) ===" >> "$LOG_FILE"

# Activate venv if present
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Run monitor
python3 monitor.py --format markdown >> "$LOG_FILE" 2>&1

echo "=== LLVM Monitor finished at $(date) ===" >> "$LOG_FILE"

# Clean up old logs (keep 30 days)
find "$SCRIPT_DIR/logs" -name "monitor_*.log" -mtime +30 -delete 2>/dev/null

# Clean up old reports (keep 30 days)
find "$SCRIPT_DIR/reports" -name "report_*.md" -mtime +30 -delete 2>/dev/null
