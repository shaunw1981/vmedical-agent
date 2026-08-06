#!/usr/bin/env bash
#
# setup.sh — one-command setup for the vmedical-agent droplet.
#
# WHAT THIS DOES (in plain English):
#   1. Installs the software the app needs (Python, nginx, etc.)
#   2. Copies your project into /opt/vmedical-agent
#   3. Sets up an isolated Python environment and installs dependencies
#   4. Turns the app into a background service that starts on boot
#   5. Sets up nginx so the app is reachable from the internet
#
# HOW TO RUN IT (on the droplet, as root):
#   cd /root/vmedical-agent          # wherever you cloned the project
#   bash deploy/setup.sh
#
# It is safe to run this more than once. Running it again just updates things.

set -euo pipefail

APP_NAME="vmedical-agent"
APP_DIR="/opt/${APP_NAME}"
APP_USER="vmedical"
# The folder this script is being run from (the project you cloned).
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> Step 1/6: Installing system software (this can take a minute)..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y python3 python3-venv python3-pip nginx rsync

echo "==> Step 2/6: Creating the '${APP_USER}' user the service will run as..."
if ! id "${APP_USER}" >/dev/null 2>&1; then
    useradd --system --create-home --shell /usr/sbin/nologin "${APP_USER}"
fi

echo "==> Step 3/6: Copying your project into ${APP_DIR}..."
mkdir -p "${APP_DIR}"
# Copy the code, but never overwrite an existing .env (your secrets).
rsync -a --exclude='.git' --exclude='.venv' --exclude='.env' \
    "${SOURCE_DIR}/" "${APP_DIR}/"

# If there is no .env yet, create one from the example so the service can start.
if [ ! -f "${APP_DIR}/.env" ]; then
    cp "${APP_DIR}/.env.example" "${APP_DIR}/.env"
    echo "    NOTE: A starter .env was created. You MUST edit it and add your"
    echo "          real ANTHROPIC_API_KEY before the agent will work:"
    echo "          nano ${APP_DIR}/.env"
fi

echo "==> Step 4/6: Installing Python dependencies..."
python3 -m venv "${APP_DIR}/.venv"
"${APP_DIR}/.venv/bin/pip" install --upgrade pip
"${APP_DIR}/.venv/bin/pip" install -r "${APP_DIR}/requirements.txt"

# The service user needs to own its files.
chown -R "${APP_USER}:${APP_USER}" "${APP_DIR}"
# Lock down the secrets file so only the service user can read it.
chmod 600 "${APP_DIR}/.env"

echo "==> Step 5/6: Setting up the background service..."
cp "${APP_DIR}/deploy/${APP_NAME}.service" "/etc/systemd/system/${APP_NAME}.service"
systemctl daemon-reload
systemctl enable "${APP_NAME}"
systemctl restart "${APP_NAME}"

echo "==> Step 6/6: Setting up nginx (the internet 'front door')..."
cp "${APP_DIR}/deploy/nginx.conf.example" "/etc/nginx/sites-available/${APP_NAME}"
ln -sf "/etc/nginx/sites-available/${APP_NAME}" "/etc/nginx/sites-enabled/${APP_NAME}"
# Remove the default nginx welcome page so ours takes over.
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl restart nginx

echo ""
echo "============================================================"
echo " Done! Your ${APP_NAME} service is installed."
echo ""
echo " Check it is running:   systemctl status ${APP_NAME}"
echo " See its logs:          journalctl -u ${APP_NAME} -f"
echo " Test it locally:       curl http://localhost/health"
echo ""
echo " If you have not added your API key yet:"
echo "   nano ${APP_DIR}/.env    then    systemctl restart ${APP_NAME}"
echo "============================================================"
