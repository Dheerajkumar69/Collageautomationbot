#!/bin/bash
# run.sh — local development helper
# DO NOT hardcode credentials here. Use a .env file or pass them interactively.

# Load .env if it exists
if [ -f ".env" ]; then
    export $(grep -v '^#' .env | xargs)
fi

# Activate the virtual environment if it exists
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# Run the bot (add --headful to see the browser, --dry-run to skip submitting)
python main.py "$@"
