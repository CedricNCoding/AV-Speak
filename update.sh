#!/bin/bash
# AV-Speak — Script de mise a jour
#
# Usage : sudo bash update.sh
#
# Deux modes detectes automatiquement :
#
#  A. Mode "direct"       : /opt/av-speak EST un depot git
#                           -> git pull dans /opt/av-speak
#
#  B. Mode "source + cp"  : update.sh est lance depuis un clone git du repo
#                           AV-Speak, et /opt/av-speak est un install par cp
#                           (cas du install.sh d'origine)
#                           -> git pull dans le clone source, puis copie des
#                              fichiers de l'app vers /opt/av-speak
#
# Etapes communes :
#   1. Detection du mode
#   2. Backup horodate de la base SQLite (rotation 10 derniers)
#   3. Arret du service systemd
#   4. Mise a jour (pull direct ou pull + sync)
#   5. pip install -r requirements.txt
#   6. Redemarrage du service + verification
#   7. En cas d'echec : restauration auto de la base depuis le backup

set -euo pipefail

INSTALL_DIR="/opt/av-speak"
SERVICE_NAME="av-speak"
BACKUP_DIR="$INSTALL_DIR/backups"
DB_FILE="$INSTALL_DIR/av_speak.db"
TS="$(date +%Y%m%d-%H%M%S)"
DB_BACKUP="$BACKUP_DIR/av_speak.db.bak-$TS"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Couleurs
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
fail()  { echo -e "${RED}[ERREUR]${NC} $*" >&2; }

# --- Verifications de base ---

if [ "$EUID" -ne 0 ]; then
    fail "Ce script doit etre execute en root (sudo bash update.sh)."
    exit 1
fi

if [ ! -d "$INSTALL_DIR" ]; then
    fail "Repertoire $INSTALL_DIR introuvable. AV-Speak n'est pas installe ?"
    exit 1
fi

# --- Detection du mode ---

MODE=""
SOURCE_DIR=""

if [ -d "$INSTALL_DIR/.git" ]; then
    MODE="direct"
    SOURCE_DIR="$INSTALL_DIR"
    info "Mode detecte : DIRECT ($INSTALL_DIR est un depot git)"
elif [ -d "$SCRIPT_DIR/.git" ]; then
    MODE="source"
    SOURCE_DIR="$SCRIPT_DIR"
    info "Mode detecte : SOURCE+SYNC"
    info "  Clone source : $SOURCE_DIR"
    info "  Cible install : $INSTALL_DIR"
else
    fail "Aucun depot git trouve."
    fail "  - $INSTALL_DIR/.git absent"
    fail "  - $SCRIPT_DIR/.git absent"
    echo ""
    fail "Pour utiliser ce script vous devez disposer d'un clone du repo :"
    echo ""
    echo "  cd ~"
    echo "  git clone https://github.com/CedricNCoding/AV-Speak.git"
    echo "  cd AV-Speak  # (ou : cd 'AV-Speak/Projet AV-Speak' selon la structure)"
    echo "  sudo bash update.sh"
    echo ""
    fail "Alternative : convertir $INSTALL_DIR en depot git :"
    echo ""
    echo "  cd $INSTALL_DIR"
    echo "  sudo git init"
    echo "  sudo git remote add origin https://github.com/CedricNCoding/AV-Speak.git"
    echo "  sudo git fetch origin"
    echo "  sudo git reset --mixed origin/main"
    echo "  sudo git checkout -- app.py templates static requirements.txt update.sh"
    echo ""
    exit 1
fi

# --- Verifications service ---

if ! systemctl list-unit-files 2>/dev/null | grep -q "^${SERVICE_NAME}.service"; then
    warn "Service systemd ${SERVICE_NAME} introuvable."
    warn "La mise a jour continuera mais sans arret/restart automatique."
fi

cd "$SOURCE_DIR"
info "Branche : $(git rev-parse --abbrev-ref HEAD)"
info "Commit actuel : $(git rev-parse --short HEAD)"

# --- Etape 1 : fetch et check ---

info "Etape 1/6 : recuperation des modifications distantes..."
git fetch origin
LOCAL_REV="$(git rev-parse HEAD)"
REMOTE_REV="$(git rev-parse @{u} 2>/dev/null || echo "")"

if [ -z "$REMOTE_REV" ]; then
    fail "Aucun upstream configure sur la branche courante."
    exit 1
fi

if [ "$LOCAL_REV" = "$REMOTE_REV" ] && [ "$MODE" = "direct" ]; then
    ok "Deja a jour. Rien a faire."
    exit 0
fi

if [ "$LOCAL_REV" != "$REMOTE_REV" ]; then
    NB_COMMITS="$(git rev-list --count HEAD..@{u})"
    info "$NB_COMMITS nouveau(x) commit(s) a appliquer :"
    git log --oneline HEAD..@{u} | sed 's/^/    /'
else
    info "Clone source deja a jour, on resynchronise quand meme $INSTALL_DIR."
fi

# --- Etape 2 : arret du service ---

info "Etape 2/6 : arret du service ${SERVICE_NAME}..."
if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
    systemctl stop "$SERVICE_NAME"
    ok "Service arrete."
else
    warn "Service deja arrete ou inexistant."
fi

# --- Etape 3 : backup de la base ---

info "Etape 3/6 : backup de la base SQLite..."
mkdir -p "$BACKUP_DIR"
if [ -f "$DB_FILE" ]; then
    cp "$DB_FILE" "$DB_BACKUP"
    [ -f "${DB_FILE}-wal" ] && cp "${DB_FILE}-wal" "${DB_BACKUP}-wal"
    [ -f "${DB_FILE}-shm" ] && cp "${DB_FILE}-shm" "${DB_BACKUP}-shm"
    ok "Backup : $DB_BACKUP"
    # Rotation : on garde les 10 derniers
    ls -1t "$BACKUP_DIR"/av_speak.db.bak-* 2>/dev/null | tail -n +11 | xargs -r rm -f
else
    warn "Aucune base existante a sauvegarder ($DB_FILE absent)."
fi

# --- Etape 4 : pull du code (et eventuellement sync) ---

info "Etape 4/6 : mise a jour du code..."
STASHED=0
if ! git diff --quiet || ! git diff --cached --quiet; then
    warn "Modifications locales detectees dans $SOURCE_DIR, sauvegarde via git stash..."
    git stash push -u -m "update.sh auto-stash $TS" || true
    STASHED=1
fi

if [ "$LOCAL_REV" != "$REMOTE_REV" ]; then
    if ! git pull --ff-only; then
        fail "git pull a echoue (probablement merge non fast-forward)."
        fail "Le service est arrete. Examinez 'git status' dans $SOURCE_DIR puis :"
        fail "    sudo systemctl start $SERVICE_NAME"
        exit 1
    fi
    ok "Code a jour : $(git rev-parse --short HEAD)"
fi

if [ "$MODE" = "source" ]; then
    info "Synchronisation des fichiers vers $INSTALL_DIR..."
    # On copie les fichiers de l'app, en preservant la base, le venv, le cache TTS et piper.
    # rsync --exclude est plus sur que cp.
    if command -v rsync >/dev/null 2>&1; then
        rsync -a --delete \
            --exclude='.git/' \
            --exclude='venv/' \
            --exclude='av_speak.db' \
            --exclude='av_speak.db-wal' \
            --exclude='av_speak.db-shm' \
            --exclude='backups/' \
            --exclude='tts_cache/' \
            --exclude='piper/' \
            --exclude='.env' \
            --exclude='__pycache__/' \
            --exclude='*.pyc' \
            --exclude='.DS_Store' \
            "$SOURCE_DIR/" "$INSTALL_DIR/"
        ok "Fichiers synchronises (rsync)."
    else
        warn "rsync absent, fallback en cp (moins precis)..."
        cp -f "$SOURCE_DIR/app.py" "$INSTALL_DIR/"
        cp -f "$SOURCE_DIR/requirements.txt" "$INSTALL_DIR/"
        [ -f "$SOURCE_DIR/update.sh" ] && cp -f "$SOURCE_DIR/update.sh" "$INSTALL_DIR/"
        cp -rf "$SOURCE_DIR/templates"/* "$INSTALL_DIR/templates/" 2>/dev/null || true
        cp -rf "$SOURCE_DIR/static"/* "$INSTALL_DIR/static/" 2>/dev/null || true
        ok "Fichiers copies (cp)."
    fi
fi

# --- Etape 5 : dependances Python ---

info "Etape 5/6 : mise a jour des dependances Python..."
if [ -d "$INSTALL_DIR/venv" ] && [ -f "$INSTALL_DIR/requirements.txt" ]; then
    "$INSTALL_DIR/venv/bin/pip" install -q -r "$INSTALL_DIR/requirements.txt"
    ok "Dependances a jour."
else
    warn "venv ou requirements.txt manquant dans $INSTALL_DIR, etape sautee."
fi

# --- Etape 6 : redemarrage ---

info "Etape 6/6 : redemarrage du service..."
if systemctl list-unit-files 2>/dev/null | grep -q "^${SERVICE_NAME}.service"; then
    systemctl start "$SERVICE_NAME"
    sleep 3
    if systemctl is-active --quiet "$SERVICE_NAME"; then
        ok "Service ${SERVICE_NAME} demarre."
    else
        fail "Le service n'a pas demarre. Tentative de rollback de la base..."
        if [ -f "$DB_BACKUP" ]; then
            cp "$DB_BACKUP" "$DB_FILE"
            [ -f "${DB_BACKUP}-wal" ] && cp "${DB_BACKUP}-wal" "${DB_FILE}-wal"
            [ -f "${DB_BACKUP}-shm" ] && cp "${DB_BACKUP}-shm" "${DB_FILE}-shm"
            warn "Base restauree depuis $DB_BACKUP."
        fi
        fail "Logs des dernieres erreurs :"
        journalctl -u "$SERVICE_NAME" -n 30 --no-pager | sed 's/^/    /'
        fail "Pour revenir au commit precedent dans $SOURCE_DIR :"
        fail "    cd $SOURCE_DIR && git reset --hard $LOCAL_REV"
        if [ "$MODE" = "source" ]; then
            fail "    puis relancer : sudo bash $SOURCE_DIR/update.sh"
        else
            fail "    puis : sudo systemctl start $SERVICE_NAME"
        fi
        exit 1
    fi
else
    warn "Pas de service systemd : demarrez l'app manuellement."
fi

# --- Recap ---

echo ""
ok "==== Mise a jour terminee ===="
echo "  Mode             : $MODE"
echo "  Source git       : $SOURCE_DIR"
echo "  Install cible    : $INSTALL_DIR"
echo "  Commit precedent : $LOCAL_REV"
echo "  Nouveau commit   : $(git -C "$SOURCE_DIR" rev-parse HEAD)"
echo "  Backup base      : $DB_BACKUP"
if [ "$STASHED" -eq 1 ]; then
    warn "Vos modifications locales sont dans git stash."
    echo "  Pour les recuperer : cd $SOURCE_DIR && git stash pop"
fi
echo ""
info "Verifier le bon fonctionnement :"
echo "  sudo systemctl status $SERVICE_NAME"
echo "  sudo journalctl -u $SERVICE_NAME -f"
echo ""
warn "Rappels post-mise-a-jour :"
echo "  - Toutes les sessions admin ont ete invalidees (reconnectez-vous)."
echo "  - Les champs mots de passe SMTP / secrets OVH apparaissent vides"
echo "    dans l'admin : c'est normal, ils sont conserves si vous laissez vide."
echo "  - Pour activer l'alerte evacuation : definir code 6 chiffres,"
echo "    activer SMTP et configurer au moins un destinataire."
echo ""
