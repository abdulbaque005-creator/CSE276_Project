#!/bin/bash

# Navigate to project root
cd "$(dirname "$0")"

echo "🚀 Starting DocuMind AI Server..."
cd backend

# Clean up any old running instances
pkill -f "uvicorn main:app" 2>/dev/null
pkill -f "localtunnel" 2>/dev/null
sleep 1

# Start the Python Backend
source venv/bin/activate
TRANSFORMERS_VERBOSITY=error HF_HUB_DISABLE_PROGRESS_BARS=1 uvicorn main:app --host 0.0.0.0 --port 8000 > backend.log 2>&1 &
echo "✅ Backend running locally."
sleep 3

echo "🌐 Creating Secure Internet Tunnel..."
# Create a secure tunnel so the world can reach the local backend
URL="https://documind-api-cse276.loca.lt"

cd ../frontend
# Update app.js to point to the new live tunnel URL
sed -i '' "s|const API = '.*';|const API = '$URL';|" app.js

# Push to GitHub
git add app.js
git commit -m "Auto-update API URL to $URL" --quiet
git push origin main --quiet

echo ""
echo "=========================================================="
echo "🎉 SUCCESS! YOUR AI IS ONLINE AND READY TO SHARE!"
echo "=========================================================="
echo "It takes GitHub about 60 seconds to update the website."
echo "Tell your friend to go to:"
echo "👉 https://abdulbaque005-creator.github.io/CSE276_Project/frontend/"
echo ""
echo "⚠️ IMPORTANT: DO NOT CLOSE THIS TERMINAL WINDOW!"
echo "As long as this window is open, your friend can use the AI."
echo "Press Ctrl+C when you want to turn the server off."
echo "=========================================================="

# Run localtunnel in the foreground
npx localtunnel --port 8000 --subdomain documind-api-cse276
