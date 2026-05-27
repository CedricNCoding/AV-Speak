#!/bin/bash
# ============================================================================
# AV-Speak - Installation Complete
# Installe l'application + transforme la machine en borne kiosque
# Compatible Ubuntu Server 24.04 LTS
# ============================================================================
# Usage :
#   git clone https://github.com/CedricNCoding/AV-Speak.git
#   cd AV-Speak
#   sudo bash installation-complete.sh
# ============================================================================

set -e

# === CONFIGURATION ===
INSTALL_DIR="/opt/av-speak"
SERVICE_NAME="av-speak"
KIOSK_USER="kiosk"
KIOSK_PASSWORD="kiosk2026"
APP_URL="http://localhost:8000"
PIPER_VERSION="2023.11.14-2"
PIPER_URL="https://github.com/rhasspy/piper/releases/download/${PIPER_VERSION}/piper_linux_x86_64.tar.gz"
VOICE_BASE="https://huggingface.co/rhasspy/piper-voices/resolve/main/fr/fr_FR/siwis/medium"
# =====================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERREUR]${NC} $1"; exit 1; }

if [ "$EUID" -ne 0 ]; then
    error "Ce script doit etre lance avec sudo : sudo bash installation-complete.sh"
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo ""
echo -e "${GREEN}==============================================${NC}"
echo -e "${GREEN}  AV-Speak - Installation Complete${NC}"
echo -e "${GREEN}==============================================${NC}"
echo ""

# ===================================================================
# PARTIE 1 : APPLICATION AV-SPEAK
# ===================================================================

echo -e "${YELLOW}--- PARTIE 1/2 : Application AV-Speak ---${NC}"
echo ""

# --- 1.1 Dependances systeme ---
info "[1/10] Installation des dependances systeme..."
apt update -qq
apt install -y -qq \
    python3 python3-pip python3-venv python3-dev build-essential \
    wget curl git \
    xorg openbox chromium unclutter \
    pulseaudio alsa-utils x11-xserver-utils > /dev/null 2>&1
info "Dependances installees."

# --- 1.2 Copie du projet ---
info "[2/10] Installation du projet dans ${INSTALL_DIR}..."
if [ "$SCRIPT_DIR" != "$INSTALL_DIR" ]; then
    mkdir -p "$INSTALL_DIR"
    cp "$SCRIPT_DIR/app.py" "$INSTALL_DIR/"
    cp "$SCRIPT_DIR/requirements.txt" "$INSTALL_DIR/"
    cp -r "$SCRIPT_DIR/static" "$INSTALL_DIR/"
    cp -r "$SCRIPT_DIR/templates" "$INSTALL_DIR/"
    # Copier les scripts pour reference
    cp "$SCRIPT_DIR/installation-complete.sh" "$INSTALL_DIR/" 2>/dev/null || true
    mkdir -p "$INSTALL_DIR/tts_cache"
else
    info "Deja dans ${INSTALL_DIR}, pas de copie necessaire."
fi
info "Projet copie."

# --- 1.3 Piper TTS ---
info "[3/10] Installation de Piper TTS..."
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
    # Verification
    if "$INSTALL_DIR/piper/piper" --help > /dev/null 2>&1; then
        info "Piper installe et fonctionnel."
    else
        warn "Piper installe mais verification echouee (librairies manquantes ?)."
    fi
fi

# --- 1.4 Voix francaise ---
info "[4/10] Telechargement de la voix francaise..."
if [ -f "$INSTALL_DIR/piper/fr_FR-siwis-medium.onnx" ]; then
    info "Voix deja presente, etape ignoree."
else
    wget -q --show-progress "${VOICE_BASE}/fr_FR-siwis-medium.onnx" \
        -O "$INSTALL_DIR/piper/fr_FR-siwis-medium.onnx"
    wget -q --show-progress "${VOICE_BASE}/fr_FR-siwis-medium.onnx.json" \
        -O "$INSTALL_DIR/piper/fr_FR-siwis-medium.onnx.json"
    info "Voix francaise installee."
fi

# --- 1.5 Environnement Python ---
info "[5/10] Creation de l'environnement Python..."
cd "$INSTALL_DIR"
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install -q -r requirements.txt
deactivate
info "Environnement Python pret."

# --- 1.6 Service systemd AV-Speak ---
info "[6/10] Configuration du service AV-Speak (demarrage auto)..."
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
info "Service AV-Speak cree, active et demarre."

# ===================================================================
# PARTIE 2 : KIOSQUE
# ===================================================================

echo ""
echo -e "${YELLOW}--- PARTIE 2/2 : Configuration Kiosque ---${NC}"
echo ""

# --- 2.1 Utilisateur kiosk ---
info "[7/10] Creation de l'utilisateur ${KIOSK_USER}..."
if ! id "$KIOSK_USER" &>/dev/null; then
    useradd -m -s /bin/bash "$KIOSK_USER"
    echo "${KIOSK_USER}:${KIOSK_PASSWORD}" | chpasswd
    usermod -aG audio,video,input "$KIOSK_USER"
    info "Utilisateur cree."
else
    info "Utilisateur ${KIOSK_USER} existe deja."
fi

# Ensure the home directory exists even if the account was created earlier without -m.
if [ ! -d "/home/${KIOSK_USER}" ]; then
    info "Repertoire /home/${KIOSK_USER} absent, creation..."
    mkdir -p "/home/${KIOSK_USER}"
    chown "${KIOSK_USER}:${KIOSK_USER}" "/home/${KIOSK_USER}"
    chmod 755 "/home/${KIOSK_USER}"
fi
# Make sure the audio/video/input groups are present (idempotent).
usermod -aG audio,video,input "$KIOSK_USER" 2>/dev/null || true

# --- 2.2 Auto-login sur TTY1 ---
info "[8/10] Configuration de l'auto-login..."
mkdir -p /etc/systemd/system/getty@tty1.service.d
cat > /etc/systemd/system/getty@tty1.service.d/autologin.conf << EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin ${KIOSK_USER} --noclear %I \$TERM
Type=idle
EOF

# --- 2.3 Demarrage automatique de X ---
info "[9/10] Configuration du demarrage X + Openbox..."

cat > /home/${KIOSK_USER}/.bash_profile << 'BASHPROFILE'
if [ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then
    exec startx -- -nocursor 2>/dev/null
fi
BASHPROFILE
chown ${KIOSK_USER}:${KIOSK_USER} /home/${KIOSK_USER}/.bash_profile

cat > /home/${KIOSK_USER}/.xinitrc << 'XINITRC'
exec openbox-session
XINITRC
chown ${KIOSK_USER}:${KIOSK_USER} /home/${KIOSK_USER}/.xinitrc

# --- 2.4 Configuration Openbox ---
mkdir -p /home/${KIOSK_USER}/.config/openbox

cat > /home/${KIOSK_USER}/.config/openbox/autostart << EOF
# Desactiver veille / ecran de veille / DPMS
xset s off
xset s noblank
xset -dpms

# Masquer le curseur apres 1s d'inactivite
unclutter -idle 1 -root &

# Demarrer PulseAudio
pulseaudio --start 2>/dev/null &
sleep 2

# Forcer le jack (sortie analogique) comme sortie par defaut et demuter
# Detecte automatiquement le sink analog-stereo (jack) parmi les sinks disponibles
ANALOG_SINK=\$(pactl list sinks short | awk '/analog-stereo/ {print \$2; exit}')
if [ -n "\$ANALOG_SINK" ]; then
    pactl set-default-sink "\$ANALOG_SINK"
    pactl set-sink-mute "\$ANALOG_SINK" 0
    pactl set-sink-volume "\$ANALOG_SINK" 85%
fi

# Attendre que l'appli AV-Speak soit prete (max 60s)
echo "Attente de AV-Speak sur ${APP_URL}..."
for i in \$(seq 1 60); do
    if curl -s -o /dev/null ${APP_URL} 2>/dev/null; then
        break
    fi
    sleep 1
done

# Chromium en mode kiosque tactile
chromium \\
    --noerrdialogs \\
    --disable-infobars \\
    --kiosk \\
    --no-first-run \\
    --disable-translate \\
    --disable-features=TranslateUI \\
    --disable-session-crashed-bubble \\
    --disable-component-update \\
    --autoplay-policy=no-user-gesture-required \\
    --disable-pinch \\
    --overscroll-history-navigation=0 \\
    --check-for-update-interval=31536000 \\
    "${APP_URL}"
EOF

# Verrouillage des raccourcis clavier
cat > /home/${KIOSK_USER}/.config/openbox/rc.xml << 'RCXML'
<?xml version="1.0" encoding="UTF-8"?>
<openbox_config xmlns="http://openbox.org/3.4/rc">
  <keyboard>
    <chainQuitKey>C-g</chainQuitKey>
  </keyboard>
  <mouse>
    <context name="Frame">
      <mousebind button="A-Left" action="Press"/>
      <mousebind button="A-Right" action="Press"/>
    </context>
  </mouse>
  <applications>
    <application class="*">
      <decor>no</decor>
      <fullscreen>yes</fullscreen>
    </application>
  </applications>
</openbox_config>
RCXML

chown -R ${KIOSK_USER}:${KIOSK_USER} /home/${KIOSK_USER}/.config

# --- 2.5 Audio ---
info "[10/10] Configuration audio..."
sudo -u ${KIOSK_USER} amixer sset Master 80% 2>/dev/null || true

# ===================================================================
# RESUME
# ===================================================================

echo ""
echo -e "${GREEN}==============================================${NC}"
echo -e "${GREEN}  INSTALLATION TERMINEE AVEC SUCCES${NC}"
echo -e "${GREEN}==============================================${NC}"
echo ""
echo "  AV-Speak"
echo "    Application : ${APP_URL}"
echo "    Admin       : ${APP_URL}/admin/login"
echo "    Identifiant : admin / admin  (a changer !)"
echo "    Service     : sudo systemctl status ${SERVICE_NAME}"
echo ""
echo "  Kiosque"
echo "    Utilisateur : ${KIOSK_USER} / ${KIOSK_PASSWORD}"
echo "    Auto-login  : oui (TTY1)"
echo "    Chromium    : plein ecran, clavier virtuel actif"
echo ""
echo "  Demarrage automatique :"
echo "    - AV-Speak demarre via systemd (boot)"
echo "    - Kiosque demarre via auto-login TTY1 (boot)"
echo ""
echo "  Commandes utiles :"
echo "    sudo systemctl status  ${SERVICE_NAME}"
echo "    sudo systemctl restart ${SERVICE_NAME}"
echo "    sudo journalctl -u ${SERVICE_NAME} -f"
echo ""
echo -e "${YELLOW}  -> sudo reboot pour demarrer la borne${NC}"
echo ""
