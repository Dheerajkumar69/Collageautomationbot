#!/bin/bash

# Set your registration number and password below
export LMS_USERNAME="AU/2025/0000143"
export LMS_PASSWORD="Sudip@2006"

# Activate the virtual environment if it exists
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# Run the bot (you can add --headful or --dry-run if you want)
python main.py --headful
