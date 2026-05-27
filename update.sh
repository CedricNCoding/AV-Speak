#!/bin/bash
# AV-Speak — Script de mise a jour
#
# Usage : sudo bash update.sh
#
# Etapes :
#   1. Verifications (root, repo git, service present)
#   2. Backup horodate de la base SQLite
#   3. Sauvegarde des modifications locales eventuelles (git stash)
#   4. git pull
#   5. Mise a jour des dependances Python (pip install -r requirements.txt)
#   6. Redemarrage du service systemd (la migration de schema tourne au demarrage)
#   7. Verification du statut + tail des derniers logs
#
# En cas d'echec apres le redemarrage, restauration automatique de la base
# depuis le backup et arret de la procedure.

set -euo pipefail

INSTALL_DIR="/opt/av-speak"
SERVICE_NAME="av-speak"
BACKUP_DIR="$INSTALL_DIR/backups"
DB_FILE="$INSTALL_DIR/av_speak.db"
TS="$(date +%Y%m%d-%H%M%S)"
DB_BACKUP="$BACKUP_DIR/av_speak.db.bak-$TS"

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

# --- Verifications ---

if [ "$EUID" -ne 0 ]; then
    fail "Ce script doit etre execute en root (sudo bash update.sh)."
    exit 1
fi

if [ ! -d "$INSTALL_DIR" ]; then
    fail "Repertoire $INSTALL_DIR introuvable. Avez-vous deja installe AV-Speak ?"
    exit 1
fi

cd "$INSTALL_DIR"

if [ ! -d ".git" ]; then
    fail "$INSTALL_DIR n'est pas un depot git. Mise a jour manuelle requise."
    exit 1
fi

if ! systemctl list-unit-files | grep -q "^${SERVICE_NAME}.service"; then
    warn "Service systemd ${SERVICE_NAME} introuvable. La mise a jour continuera"
    warn "mais le service ne sera ni arrete ni redemarre automatiquement."
fi

info "Repertoire : $INSTALL_DIR"
info "Branche actuelle : $(git rev-parse --abbrev-ref HEAD)"
info "Commit actuel    : $(git rev-parse --short HEAD)"

# --- Etape 1 : check des modifications distantes ---

info "Etape 1/6 : recuperation des modifications distantes..."
git fetch origin
LOCAL_REV="$(git rev-parse HEAD)"
REMOTE_REV="$(git rev-parse @{u} 2>/dev/null || echo "")"

if [ -z "$REMOTE_REV" ]; then
    fail "Aucun upstream configure sur la branche courante."
    exit 1
fi

if [ "$LOCAL_REV" = "$REMOTE_REV" ]; then
    ok "Deja a jour. Rien a faire."
    exit 0
fi

NB_COMMITS="$(git rev-list --count HEAD..@{u})"
info "$NB_COMMITS nouveau(x) commit(s) a appliquer :"
git log --oneline HEAD..@{u} | sed 's/^/    /'

# --- Etape 2 : arret du service ---

info "Etape 2/6 : arret du service ${SERVICE_NAME}..."
if systemctl is-active --quiet "$SERVICE_NAME"; then
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
    # Backup aussi les fichiers WAL/SHM s'ils existent (transactions en vol)
    [ -f "${DB_FILE}-wal" ] && cp "${DB_FILE}-wal" "${DB_BACKUP}-wal"
    [ -f "${DB_FILE}-shm" ] && cp "${DB_FILE}-shm" "${DB_BACKUP}-shm"
    ok "Backup : $DB_BACKUP"
    # Rotation : on garde les 10 derniers backups
    ls -1t "$BACKUP_DIR"/av_speak.db.bak-* 2>/dev/null | tail -n +11 | xargs -r rm -f
else
    warn "Aucune base existante a sauvegarder ($DB_FILE absent)."
fi

# --- Etape 4 : sauvegarde des modifs locales puis pull ---

info "Etape 4/6 : mise a jour du code..."
STASHED=0
if ! git diff --quiet || ! git diff --cached --quiet; then
    warn "Modifications locales detectees, sauvegarde dans git stash..."
    git stash push -u -m "update.sh auto-stash $TS" || true
    STASHED=1
fi

if ! git pull --ff-only; then
    fail "git pull a echoue (probablement merge non fast-forward)."
    fail "Le service est arrete. Examinez 'git status' puis redemarrez :"
    fail "    sudo systemctl start $SERVICE_NAME"
    exit 1
fi
ok "Code a jour : $(git rev-parse --short HEAD)"

# --- Etape 5 : dependances Python ---

info "Etape 5/6 : mise a jour des dependances Python..."
if [ -d "venv" ] && [ -f "requirements.txt" ]; then
    ./venv/bin/pip install -q -r requirements.txt
    ok "Dependances a jour."
else
    warn "venv ou requirements.txt manquant, etape sautee."
fi

# --- Etape 6 : redemarrage et verification ---

info "Etape 6/6 : redemarrage du service..."
if systemctl list-unit-files | grep -q "^${SERVICE_NAME}.service"; then
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
        fail "Le code est sur le nouveau commit mais le service est en echec."
        fail "Pour revenir au commit precedent :"
        fail "    cd $INSTALL_DIR && git reset --hard $LOCAL_REV && sudo systemctl start $SERVICE_NAME"
        exit 1
    fi
else
    warn "Pas de service systemd : demarrez l'app manuellement."
fi

# --- Recap ---

echo ""
ok "==== Mise a jour terminee ===="
echo "  Commit precedent : $LOCAL_REV"
echo "  Nouveau commit   : $(git rev-parse HEAD)"
echo "  Backup base      : $DB_BACKUP"
if [ "$STASHED" -eq 1 ]; then
    warn "Vos modifications locales sont dans git stash."
    echo "  Pour les recuperer : cd $INSTALL_DIR && git stash pop"
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
