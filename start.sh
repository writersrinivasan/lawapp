#!/bin/bash
cd "$(dirname "$0")"
echo "Starting Nyaya Sahayak — Indian Law Assistant..."
echo "Open http://localhost:8000 in your browser"
python3 -m uvicorn server:app --host 0.0.0.0 --port 8000 --reload
