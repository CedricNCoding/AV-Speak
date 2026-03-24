#!/bin/bash
# =============================================================================
# AV-Speak - Script d'installation Linux (Debian/Ubuntu)
# Usage : sudo bash install.sh
# =============================================================================

set -e

INSTALL_DIR="/opt/av-speak"
SERVICE_NAME="av-speak"
PIPER_VERSION="2023.11.14-2"
PIPER_URL="https://github.com/rhasspy/piper/releases/download/${PIPER_VERSION}/piper_linux_x86_64.tar.gz"
VOICE_BASE="https://huggingface.co/rhasspy/piper-voices/resolve/main/fr/fr_FR/siwis/medium"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERREUR]${NC} $1"; exit 1; }

# --- Verifications ---
if [ "$EUID" -ne 0 ]; then
    error "Ce script doit etre lance avec sudo : sudo bash install.sh"
fi

info "=== Installation de AV-Speak ==="
echo ""

# --- Etape 1 : Dependances systeme ---
info "Etape 1/6 : Installation des dependances systeme..."
apt update -qq
apt install -y -qq python3 python3-pip python3-venv \
    libsdl2-mixer-2.0-0 libsdl2-2.0-0 wget > /dev/null 2>&1
info "Dependances systeme installees."

# --- Etape 2 : Copie du projet ---
info "Etape 2/6 : Installation du projet dans ${INSTALL_DIR}..."
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ "$SCRIPT_DIR" != "$INSTALL_DIR" ]; then
    mkdir -p "$INSTALL_DIR"
    cp "$SCRIPT_DIR/app.py" "$INSTALL_DIR/"
    cp "$SCRIPT_DIR/requirements.txt" "$INSTALL_DIR/"
    cp -r "$SCRIPT_DIR/static" "$INSTALL_DIR/"
    cp -r "$SCRIPT_DIR/templates" "$INSTALL_DIR/"
    mkdir -p "$INSTALL_DIR/tts_cache"
else
    info "Deja dans ${INSTALL_DIR}, pas de copie necessaire."
fi
info "Projet copie."

# --- Etape 3 : Piper TTS ---
info "Etape 3/6 : Installation de Piper TTS..."
if [ -f "$INSTALL_DIR/piper/piper" ]; then
    info "Piper deja installe, etape ignoree."
else
    mkdir -p "$INSTALL_DIR/piper"
    cd /tmp
    info "  Telechargement de Piper..."
    wget -q --show-progress "$PIPER_URL" -O piper.tar.gz
    tar xzf piper.tar.gz -C "$INSTALL_DIR/"
    rm piper.tar.gz
    chmod +x "$INSTALL_DIR/piper/piper"
    info "  Piper installe."
fi

# --- Etape 4 : Voix francaise ---
info "Etape 4/6 : Telechargement de la voix francaise..."
if [ -f "$INSTALL_DIR/piper/fr_FR-siwis-medium.onnx" ]; then
    info "Voix deja presente, etape ignoree."
else
    wget -q --show-progress "${VOICE_BASE}/fr_FR-siwis-medium.onnx" \
        -O "$INSTALL_DIR/piper/fr_FR-siwis-medium.onnx"
    wget -q --show-progress "${VOICE_BASE}/fr_FR-siwis-medium.onnx.json" \
        -O "$INSTALL_DIR/piper/fr_FR-siwis-medium.onnx.json"
    info "Voix francaise installee."
fi

# --- Etape 5 : Environnement Python ---
info "Etape 5/6 : Creation de l'environnement Python..."
cd "$INSTALL_DIR"
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install -q -r requirements.txt
deactivate
info "Environnement Python pret."

# --- Etape 6 : Service systemd ---
info "Etape 6/6 : Configuration du service systemd..."
cat > "/etc/systemd/system/${SERVICE_NAME}.service" << EOF
[Unit]
Description=AV-Speak - Systeme d'annonce accueil
After=network.target sound.target

[Service]
Type=simple
WorkingDirectory=${INSTALL_DIR}
ExecStart=${INSTALL_DIR}/venv/bin/python app.py
Restart=always
RestartSec=5
Environment=SDL_AUDIODRIVER=alsa

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME" > /dev/null 2>&1
systemctl restart "$SERVICE_NAME"
info "Service systemd cree et demarre."

# --- Script de lancement kiosk ---
cat > "$INSTALL_DIR/lancer-kiosk.sh" << 'KIOSK'
#!/bin/bash
# Lance le navigateur en mode kiosk (plein ecran tactile)
# Utilisation : bash /opt/av-speak/lancer-kiosk.sh
sleep 2

# Chercher un navigateur disponible
if command -v chromium-browser &> /dev/null; then
    BROWSER="chromium-browser"
elif command -v chromium &> /dev/null; then
    BROWSER="chromium"
elif command -v google-chrome &> /dev/null; then
    BROWSER="google-chrome"
elif command -v firefox &> /dev/null; then
    BROWSER="firefox"
else
    echo "Aucun navigateur trouve. Installez chromium-browser."
    exit 1
fi

$BROWSER --kiosk --disable-pinch --noerrdialogs \
    --disable-infobars --disable-session-crashed-bubble \
    "http://127.0.0.1:8000"
KIOSK
chmod +x "$INSTALL_DIR/lancer-kiosk.sh"

# --- Resume ---
echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  AV-Speak installe avec succes !${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo "  Application : http://127.0.0.1:8000"
echo "  Admin       : http://127.0.0.1:8000/admin/login"
echo "  Identifiant : admin"
echo "  Mot de passe: admin  (a changer !)"
echo ""
echo "  Commandes utiles :"
echo "    sudo systemctl status  ${SERVICE_NAME}   # Voir le statut"
echo "    sudo systemctl restart ${SERVICE_NAME}   # Redemarrer"
echo "    sudo systemctl stop    ${SERVICE_NAME}   # Arreter"
echo "    sudo journalctl -u ${SERVICE_NAME} -f    # Voir les logs"
echo ""
echo "  Mode kiosk (plein ecran) :"
echo "    bash ${INSTALL_DIR}/lancer-kiosk.sh"
echo ""
echo -e "${YELLOW}  N'oubliez pas de changer le mot de passe admin !${NC}"
echo ""
