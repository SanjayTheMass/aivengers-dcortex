#!/usr/bin/env bash
# One-time EC2 bootstrap for the Crew Ops Advisor backend.
# Run on the instance:  bash setup-ec2.sh <git-repo-url>
set -euo pipefail

REPO_URL="${1:?Usage: setup-ec2.sh <git-repo-url>}"
APP_DIR="$HOME/aivengers"

sudo yum install -y git python3.12 python3.12-pip 2>/dev/null || { sudo apt-get update -y && sudo apt-get install -y git python3 python3-venv python3-pip; }

if [ ! -d "$APP_DIR/.git" ]; then
  git clone "$REPO_URL" "$APP_DIR"
fi
cd "$APP_DIR"

PY=$(command -v python3.12 || command -v python3)
"$PY" -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

# systemd service (runs uvicorn on port 8000)
sudo cp deploy/crewops.service /etc/systemd/system/crewops.service
sudo sed -i "s|__APP_DIR__|$APP_DIR|g; s|__USER__|$USER|g" /etc/systemd/system/crewops.service
sudo systemctl daemon-reload
sudo systemctl enable --now crewops

echo "Done. Check: sudo systemctl status crewops ; curl -s localhost:8000/health"
