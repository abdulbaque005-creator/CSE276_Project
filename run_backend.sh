#!/bin/bash

echo "Starting DocuMind API locally..."
cd backend || exit

# Check if port 8000 is already in use and try to kill it
if lsof -Pi :8000 -sTCP:LISTEN -t >/dev/null ; then
    echo "Port 8000 is already in use. Stopping old process..."
    lsof -Pi :8000 -sTCP:LISTEN -t | xargs kill -9
fi

# Start uvicorn in the background using the virtual environment
echo "Starting Uvicorn Server..."
venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 &
UVICORN_PID=$!

# Make sure we kill uvicorn when this script exits
trap 'kill $UVICORN_PID; echo "Shutting down..."' EXIT

echo ""
echo "========================================================"
echo "Starting Localtunnel Bridge for GitHub Pages Frontend..."
echo "Your API URL is: https://documind-api-cse276.loca.lt"
echo "Keep this window open to keep your backend online!"
echo "========================================================"
echo ""

# Run localtunnel with fixed subdomain
npx localtunnel --port 8000 --subdomain documind-api-cse276
