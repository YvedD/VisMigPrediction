#!/usr/bin/env bash
set -euo pipefail

cd /home/ubuntu/vismigprediction

git pull --ff-only

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
python -m pip install --upgrade pip

if [ ! -f requirements-oracle.txt ]; then
  grep -v '^libsql$' requirements.txt | grep -v '^libsql-client$' > requirements-oracle.txt
fi

python -m pip install -r requirements-oracle.txt

sudo systemctl restart vismigprediction
sudo systemctl restart nginx
