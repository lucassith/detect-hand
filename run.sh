#!/bin/bash
# ==============================================================================
# Open Palm Detection Add-on
# Starts the palm detection service with configuration from Home Assistant
# ==============================================================================

set -e

echo "======================================"
echo "Open Palm Detection Add-on Starting"
echo "======================================"

# Configuration is read directly by Python from /data/options.json
CONFIG_PATH="/data/options.json"

if [ -f "$CONFIG_PATH" ]; then
    echo "Configuration file found at $CONFIG_PATH"
else
    echo "WARNING: Configuration file not found at $CONFIG_PATH"
    echo "Using environment variables or defaults"
fi

# Start the Python detection script
echo "Starting palm detection service..."
exec python3 /app/detect_hand.py
