#!/bin/bash

# Set your registration number and password below
export LMS_USERNAME="YOUR_REGISTRATION_NO_HERE"
export LMS_PASSWORD="YOUR_PASSWORD_HERE"

# Activate the virtual environment if it exists
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# Run the bot (you can add --headful or --dry-run if you want)
python main.py
