#!/bin/bash
# Start script for Agentic GitHub Issue Response System

set -e

echo "Starting Agentic GitHub Issue Response System..."

# Check if .env file exists
if [ ! -f .env ]; then
    echo "Warning: .env file not found. Copying from .env.example"
    if [ -f .env.example ]; then
        cp .env.example .env
        echo "Please edit .env file with your configuration before running again."
        exit 1
    else
        echo "Error: .env.example file not found"
        exit 1
    fi
fi

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Install/update dependencies
echo "Installing dependencies..."
pip install -r requirements.txt

# Create necessary directories
echo "Creating directories..."
mkdir -p worktrees logs

# Start the server
echo "Starting FastAPI server..."
python main.py
