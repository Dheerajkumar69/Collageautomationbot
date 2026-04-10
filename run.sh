#!/bin/bash

# Set your registration number and password below
export LMS_USERNAME="REGISTRATION_NUMBER"
export LMS_PASSWORD="PASSWORD"

# Activate the virtual environment if it exists
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# Run the bot (you can add --headful or --dry-run if you want)
python main.py --headful
