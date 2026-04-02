#!/bin/bash

# Set your registration number and password below
export LMS_USERNAME="AU/2024/0001286"
export LMS_PASSWORD="Sahnik801@"

# Activate the virtual environment if it exists
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# Run the bot (you can add --headful or --dry-run if you want)
python main.py --headful
