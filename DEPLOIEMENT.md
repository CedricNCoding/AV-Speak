# AV-Speak - Guide de deploiement

## Pre-requis

- **Ubuntu Server 24.04 LTS** (64 bits)
- Connexion internet (pour l'installation uniquement)
- Haut-parleurs connectes et fonctionnels
- Ecran tactile (ou souris pour les tests)

---

## Installation rapide (recommande)

Un seul script installe tout : application, TTS, kiosque, demarrage automatique.

```bash
# 1. Cloner le projet
git clone https://github.com/CedricNCoding/AV-Speak.git
cd AV-Speak

# 2. Lancer l'installation complete
sudo bash installation-complete.sh

# 3. Redemarrer
sudo reboot
```

C'est tout. Au redemarrage :
- **AV-Speak** demarre automatiquement (service systemd)
- **L'ecran kiosque** s'ouvre en plein ecran sur l'application

---

## Acces a l'application

| Page | URL |
|------|-----|
| Kiosque (visiteurs) | `http://IP-DE-LA-MACHINE:8000` |
| Administration | `http://IP-DE-LA-MACHINE:8000/admin/login` |

**Identifiants par defaut** : `admin` / `admin` — **a changer immediatement !**

---

## Ce que fait le script d'installation

1. Installe les dependances systeme (Python 3, Chromium, X11, PulseAudio, etc.)
2. Copie l'application dans `/opt/av-speak`
3. Telecharge et installe Piper TTS + voix francaise
4. Cree un environnement virtuel Python et installe les dependances
5. Cree un service systemd `av-speak` (demarrage automatique au boot)
6. Cree un utilisateur `kiosk` avec auto-login sur TTY1
7. Configure X11/Openbox/Chromium en mode kiosque verrouille
8. Regle le volume audio a 80%

---

## Structure des fichiers installes

```
/opt/av-speak/
  app.py                    # Application FastAPI
  requirements.txt          # Dependances Python
  av_speak.db               # Base de donnees SQLite (creee au 1er lancement)
  venv/                     # Environnement virtuel Python
  piper/
    piper                   # Binaire TTS
    fr_FR-siwis-medium.onnx # Modele de voix francaise
  static/                   # Fichiers statiques (CSS, logos)
  templates/                # Templates HTML
  tts_cache/                # Cache des fichiers audio generes
```

---

## Commandes utiles

### Application AV-Speak

```bash
# Statut du service
sudo systemctl status av-speak

# Redemarrer l'application
sudo systemctl restart av-speak

# Arreter l'application
sudo systemctl stop av-speak

# Voir les logs en direct
sudo journalctl -u av-speak -f
```

### Kiosque

```bash
# Acceder au terminal (depuis l'ecran kiosque)
Ctrl+Alt+F2

# Revenir au kiosque
Ctrl+Alt+F1

# Regler le volume
amixer sset Master 90%
```

### Mise a jour

```bash
cd /chemin/vers/AV-Speak   # ou le repo a ete clone
git pull
sudo cp app.py /opt/av-speak/
sudo cp -r templates/ /opt/av-speak/
sudo cp -r static/ /opt/av-speak/
sudo systemctl restart av-speak
```

---

## Maintenance / Acces distant

L'administration se fait a distance via :

- **SSH** : `ssh utilisateur@IP-DE-LA-MACHINE`
- **Interface admin** : `http://IP-DE-LA-MACHINE:8000/admin/login`

Pour acceder au terminal local depuis la borne : `Ctrl+Alt+F2`

---

## Configuration initiale

1. Se connecter a l'admin (`admin` / `admin`)
2. Accepter les CGU
3. **Changer le mot de passe** (onglet Mot de passe)
4. Ajouter les contacts (onglet Contacts) : manuellement ou import CSV
5. Personnaliser l'apparence (onglet Apparence) : logo, couleurs, phrase d'annonce
6. Configurer les notifications email/SMS si necessaire (onglet Notifications)
7. Activer le registre de securite si souhaite (onglet Registre)

### Format CSV pour import de contacts

Fichier `.csv` avec separateur point-virgule :
```
Nom;Prenom;Civilite;Email;Telephone
Dupont;Jean;M;jean@mail.com;0612345678
Martin;Marie;Mme;marie@mail.com;0698765432
```

---

## Depannage

| Probleme | Solution |
|----------|----------|
| Pas de son | `aplay -l` pour lister les cartes son, `amixer sset Master 80%` |
| Piper ne fonctionne pas | `chmod +x /opt/av-speak/piper/piper` puis tester : `/opt/av-speak/piper/piper --help` |
| Service ne demarre pas | `sudo journalctl -u av-speak -f` pour voir les erreurs |
| Chromium ne s'ouvre pas | Verifier que X est lance : `Ctrl+Alt+F1`, verifier les logs Openbox |
| Ecran de veille s'active | Les commandes `xset` dans Openbox autostart doivent etre presentes |
| Clavier virtuel absent | Chromium doit etre lance avec `--enable-features=VirtualKeyboard` |
| Base corrompue | Supprimer `/opt/av-speak/av_speak.db` et redemarrer (repart a zero) |

---

## Architecture

```
Ecran tactile (Chromium kiosk)
    |
    v
FastAPI (port 8000) --- SQLite (av_speak.db)
    |
    v
Piper TTS --> WAV --> Navigateur (audio HTML5)
```

Tout tourne en local sur la meme machine. Aucune connexion internet necessaire en fonctionnement.
