#!/usr/bin/env bash
#
# Installe / met à jour le service systemd pi-aggregator sur le Raspberry Pi.
#
# À lancer depuis le checkout du repo, sous l'utilisateur qui fera tourner le
# service (ex. « pi ») :
#
#     ./pi-aggregator/deploy/install.sh
#
# Idempotent : peut être relancé après un `git pull` pour mettre à jour les
# dépendances et le unit file. Ne touche jamais à un config.toml existant.
#
# Variables d'environnement optionnelles :
#   SERVICE_USER   utilisateur du service        (défaut : l'utilisateur courant)
#   CONFIG_DIR     dossier de config/secrets     (défaut : /etc/pi-aggregator)
#   SERVICE_NAME   nom du service systemd         (défaut : pi-aggregator)

set -euo pipefail

SERVICE_NAME="${SERVICE_NAME:-pi-aggregator}"
SERVICE_USER="${SERVICE_USER:-$(id -un)}"
SERVICE_GROUP="$(id -gn "$SERVICE_USER")"
CONFIG_DIR="${CONFIG_DIR:-/etc/pi-aggregator}"
CONFIG_FILE="$CONFIG_DIR/config.toml"

# Dossier du paquet = parent du dossier deploy/ (résolu, peu importe le cwd).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG_DIR="$(dirname "$SCRIPT_DIR")"
VENV="$PKG_DIR/.venv"
PYTHON="${PYTHON:-python3}"
UNIT_PATH="/etc/systemd/system/${SERVICE_NAME}.service"

echo "==> pi-aggregator : installation"
echo "    paquet        : $PKG_DIR"
echo "    utilisateur   : $SERVICE_USER:$SERVICE_GROUP"
echo "    config        : $CONFIG_FILE"
echo "    service       : $SERVICE_NAME"

# --- 1. venv + dépendances ---------------------------------------------------
if [ ! -d "$VENV" ]; then
  echo "==> création du venv ($VENV)"
  "$PYTHON" -m venv "$VENV"
fi
echo "==> installation des dépendances (fastapi, uvicorn, httpx)"
"$VENV/bin/pip" install -q -U pip
"$VENV/bin/pip" install -q -e "$PKG_DIR"

# --- 2. config + secrets dans CONFIG_DIR -------------------------------------
sudo install -d -m 755 "$CONFIG_DIR"
if [ ! -f "$CONFIG_FILE" ]; then
  echo "==> création de $CONFIG_FILE depuis config.example.toml"
  sudo install -m 600 -o "$SERVICE_USER" -g "$SERVICE_GROUP" \
    "$PKG_DIR/config.example.toml" "$CONFIG_FILE"
  # Le layout est résolu relativement au config.toml : on pointe explicitement
  # vers celui du repo (éditable sur place, servi sans reflasher l'ESP32).
  sudo sed -i "s|^file = \"layout.json\"|file = \"$PKG_DIR/layout.json\"|" "$CONFIG_FILE"
  CONFIG_IS_NEW=1
else
  echo "==> $CONFIG_FILE existe déjà, laissé intact"
  CONFIG_IS_NEW=0
fi

# --- 3. unit systemd ---------------------------------------------------------
echo "==> écriture de $UNIT_PATH"
sudo tee "$UNIT_PATH" >/dev/null <<UNIT
[Unit]
Description=pi-aggregator (dashboard e-paper ESP32)
Documentation=https://github.com/gurnari/ESP32-Dashboard
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_GROUP
WorkingDirectory=$PKG_DIR
Environment=PI_AGGREGATOR_CONFIG=$CONFIG_FILE
ExecStart=$VENV/bin/python -m pi_aggregator.app
Restart=on-failure
RestartSec=5
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=full
ProtectControlGroups=yes
ProtectKernelTunables=yes
RestrictSUIDSGID=yes

[Install]
WantedBy=multi-user.target
UNIT

# --- 4. activation -----------------------------------------------------------
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"

if [ "$CONFIG_IS_NEW" = "1" ]; then
  echo
  echo "==> Config neuve : édite $CONFIG_FILE (coordonnées météo, clé PKGE),"
  echo "    puis démarre :  sudo systemctl start $SERVICE_NAME"
else
  echo "==> redémarrage du service"
  sudo systemctl restart "$SERVICE_NAME"
fi

echo
echo "État    : sudo systemctl status $SERVICE_NAME"
echo "Logs    : journalctl -u $SERVICE_NAME -f"
echo "Test    : curl -s http://localhost:8080/healthz | python3 -m json.tool"
