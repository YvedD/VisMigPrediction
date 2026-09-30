#!/usr/bin/env bash
set -euo pipefail

REPO="/home/ubuntu/vismigprediction"
cd "$REPO"

# Keep the remote exactly in sync with origin/master.
git fetch origin
git checkout master
git reset --hard origin/master
git pull --ff-only origin master

# Ensure Python environment exists.
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi

# Install dependencies.
. .venv/bin/activate
python -m pip install --upgrade pip

if [ -f requirements-oracle.txt ]; then
  python -m pip install -r requirements-oracle.txt
else
  if [ -f requirements.txt ]; then
    grep -v '^libsql$' requirements.txt | grep -v '^libsql-client$' > requirements-oracle.txt || true
    python -m pip install -r requirements-oracle.txt
  fi
fi

# Restart the app so the latest code is used.
pkill -f "streamlit run main.py" || true
sleep 2
nohup .venv/bin/streamlit run main.py --server.address 0.0.0.0 --server.port 8501 > /tmp/vismigprediction.log 2>&1 &

# Optional service/HTTP restart if available.
if command -v systemctl >/dev/null 2>&1; then
  if systemctl list-unit-files --type=service | grep -q '^vismigprediction\.service'; then
    sudo systemctl restart vismigprediction || true
  fi
fi

if command -v nginx >/dev/null 2>&1; then
  sudo nginx -t >/dev/null 2>&1 || true
  sudo systemctl restart nginx || true
fi

echo "Deploy complete. App is running at http://144.21.35.64:8501"
