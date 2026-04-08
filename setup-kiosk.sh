#!/bin/bash
# ============================================================================
# AV-Speak Kiosk Installer (simplifie)
# Transforme un Ubuntu Server 24.04 LTS en borne tactile verrouillee
# L'appli AV-Speak gere son propre demarrage -- ce script ne fait que le kiosque
# ============================================================================
# Usage : sudo bash setup-kiosk.sh
# ============================================================================

set -e

# === CONFIGURATION ===
KIOSK_USER="kiosk"
KIOSK_PASSWORD="kiosk2026"
APP_URL="http://localhost:8000"
# =====================

echo "==========================================="
echo " AV-Speak Kiosk Installer"
echo "==========================================="

if [ "$EUID" -ne 0 ]; then
    echo "ERREUR: Ce script doit etre execute en root (sudo)"
    exit 1
fi

# --- 1. Creation de l'utilisateur kiosk ---
echo "[1/6] Creation de l'utilisateur ${KIOSK_USER}..."
if ! id "$KIOSK_USER" &>/dev/null; then
    useradd -m -s /bin/bash "$KIOSK_USER"
    echo "${KIOSK_USER}:${KIOSK_PASSWORD}" | chpasswd
    usermod -aG audio,video,input "$KIOSK_USER"
fi

# --- 2. Installation des paquets ---
echo "[2/6] Installation des paquets..."
apt update
apt install -y \
    xorg \
    openbox \
    chromium \
    unclutter \
    pulseaudio \
    alsa-utils \
    x11-xserver-utils

# --- 3. Auto-login sur TTY1 ---
echo "[3/6] Configuration de l'auto-login..."
mkdir -p /etc/systemd/system/getty@tty1.service.d
cat > /etc/systemd/system/getty@tty1.service.d/autologin.conf << EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin ${KIOSK_USER} --noclear %I \$TERM
Type=idle
EOF

# --- 4. Demarrage automatique de X ---
echo "[4/6] Configuration du demarrage X..."
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

# --- 5. Configuration Openbox ---
echo "[5/6] Configuration d'Openbox..."
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

# Attendre que l'appli AV-Speak soit prete sur le port 8000
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
    --enable-features=VirtualKeyboard \\
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

# --- 6. Volume audio a 80% ---
echo "[6/6] Configuration audio..."
sudo -u ${KIOSK_USER} amixer sset Master 80% 2>/dev/null || true

echo ""
echo "==========================================="
echo " INSTALLATION TERMINEE"
echo "==========================================="
echo ""
echo " Utilisateur : ${KIOSK_USER} / ${KIOSK_PASSWORD}"
echo " URL kiosque : ${APP_URL}"
echo ""
echo " Au redemarrage, Chromium s'ouvrira en plein"
echo " ecran sur l'appli AV-Speak (port 8000)."
echo " Le clavier virtuel tactile est active."
echo ""
echo " Maintenance :"
echo "   SSH : ssh admin@IP"
echo "   TTY : Ctrl+Alt+F2"
echo "   Volume : amixer sset Master XX%"
echo ""
echo " -> sudo reboot pour tester"
echo "==========================================="
