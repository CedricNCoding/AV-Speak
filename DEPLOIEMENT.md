# AV-Speak - Guide de deploiement

## Pre-requis sur le PC cible

- Windows 10/11 (64 bits) ou Linux (Debian/Ubuntu recommande)
- Haut-parleurs connectes et fonctionnels
- Ecran tactile (ou souris pour les tests)
- Pas besoin d'internet en fonctionnement

---

# Installation Windows

## Installation (a faire UNE seule fois, avec internet)

### Etape 1 : Installer Python

1. Telecharger Python 3.11+ depuis https://www.python.org/downloads/
2. Lancer l'installeur
3. **IMPORTANT** : Cocher "Add Python to PATH" en bas de l'ecran
4. Cliquer "Install Now"

### Etape 2 : Copier le projet

Copier tout le dossier `AV-Speak` sur le PC (par cle USB par exemple) dans un endroit simple, ex :
```
C:\AV-Speak\
```

### Etape 3 : Installer Piper TTS

1. Telecharger Piper pour Windows :
   https://github.com/rhasspy/piper/releases
   -> Prendre le fichier `piper_windows_amd64.zip`

2. Extraire le contenu dans `C:\AV-Speak\piper\`
   Vous devez avoir : `C:\AV-Speak\piper\piper.exe`

3. Telecharger la voix francaise :
   https://huggingface.co/rhasspy/piper-voices/resolve/main/fr/fr_FR/siwis/medium/fr_FR-siwis-medium.onnx
   et
   https://huggingface.co/rhasspy/piper-voices/resolve/main/fr/fr_FR/siwis/medium/fr_FR-siwis-medium.onnx.json

4. Placer les 2 fichiers dans `C:\AV-Speak\piper\`

Structure attendue :
```
C:\AV-Speak\
  piper\
    piper.exe
    (autres fichiers extraits du zip)
    fr_FR-siwis-medium.onnx
    fr_FR-siwis-medium.onnx.json
  static\
  templates\
  app.py
  requirements.txt
```

### Etape 4 : Installer les dependances Python

Ouvrir un terminal (cmd) et taper :
```
cd C:\AV-Speak
pip install -r requirements.txt
```

### Etape 5 : Premier lancement (test)

```
cd C:\AV-Speak
python app.py
```

Ouvrir un navigateur sur : http://127.0.0.1:8000

- Page d'accueil = le kiosk (ecran tactile)
- Admin : http://127.0.0.1:8000/admin/login
  - Identifiant : `admin`
  - Mot de passe : `admin`
  - **Changez le mot de passe immediatement !**

## Lancement automatique au demarrage (Windows)

### Option A : Script de lancement (recommande)

Creer un fichier `lancer.bat` dans `C:\AV-Speak\` :

```bat
@echo off
cd /d C:\AV-Speak
start /min python app.py
timeout /t 3 >nul
start "" "http://127.0.0.1:8000"
```

Pour qu'il se lance au demarrage :
1. Appuyer sur `Win + R`
2. Taper `shell:startup` et Entree
3. Copier un raccourci de `lancer.bat` dans ce dossier

### Option B : Navigateur en mode kiosk (Windows)

Pour un affichage plein ecran permanent (ecran tactile) :

```bat
@echo off
cd /d C:\AV-Speak
start /min python app.py
timeout /t 3 >nul
start "" chrome --kiosk --disable-pinch --overscroll-history-navigation=0 "http://127.0.0.1:8000"
```

(Remplacer `chrome` par le chemin complet si necessaire :
`"C:\Program Files\Google\Chrome\Application\chrome.exe"`)

---

# Installation Linux (Debian / Ubuntu)

## Installation (a faire UNE seule fois, avec internet)

### Etape 1 : Installer les dependances systeme

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv libsdl2-mixer-2.0-0 libsdl2-2.0-0 chromium-browser
```

### Etape 2 : Copier le projet

Copier le dossier `AV-Speak` sur le PC (cle USB, scp, etc.) :
```bash
cp -r /media/usb/AV-Speak /opt/av-speak
cd /opt/av-speak
```

### Etape 3 : Installer Piper TTS

```bash
# Telecharger Piper
wget https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_x86_64.tar.gz
tar xzf piper_linux_x86_64.tar.gz -C /opt/av-speak/
# Le binaire se retrouve dans /opt/av-speak/piper/piper

# Telecharger la voix francaise
wget -P /opt/av-speak/piper/ \
  https://huggingface.co/rhasspy/piper-voices/resolve/main/fr/fr_FR/siwis/medium/fr_FR-siwis-medium.onnx
wget -P /opt/av-speak/piper/ \
  https://huggingface.co/rhasspy/piper-voices/resolve/main/fr/fr_FR/siwis/medium/fr_FR-siwis-medium.onnx.json

# Rendre le binaire executable
chmod +x /opt/av-speak/piper/piper
```

### Etape 4 : Creer un environnement virtuel et installer les dependances

```bash
cd /opt/av-speak
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Etape 5 : Premier lancement (test)

```bash
cd /opt/av-speak
source venv/bin/activate
python app.py
```

Ouvrir un navigateur sur : http://127.0.0.1:8000

- Identifiants admin par defaut : `admin` / `admin`
- **Changez le mot de passe immediatement !**

## Lancement automatique au demarrage (Linux)

### Option A : Service systemd (recommande)

Creer le fichier `/etc/systemd/system/av-speak.service` :

```ini
[Unit]
Description=AV-Speak Accueil
After=network.target sound.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/av-speak
ExecStart=/opt/av-speak/venv/bin/python app.py
Restart=always
RestartSec=5
Environment=DISPLAY=:0
Environment=SDL_AUDIODRIVER=alsa

[Install]
WantedBy=multi-user.target
```

Activer et demarrer :
```bash
sudo systemctl daemon-reload
sudo systemctl enable av-speak
sudo systemctl start av-speak
```

### Option B : Navigateur en mode kiosk (Linux)

Creer un fichier `/opt/av-speak/lancer.sh` :

```bash
#!/bin/bash
cd /opt/av-speak
source venv/bin/activate
python app.py &
sleep 3
chromium-browser --kiosk --disable-pinch --noerrdialogs \
  --disable-infobars --disable-session-crashed-bubble \
  "http://127.0.0.1:8000"
```

```bash
chmod +x /opt/av-speak/lancer.sh
```

Pour lancer au demarrage avec le bureau (autostart) :

```bash
mkdir -p ~/.config/autostart
cat > ~/.config/autostart/av-speak.desktop << 'EOF'
[Desktop Entry]
Type=Application
Name=AV-Speak
Exec=/opt/av-speak/lancer.sh
X-GNOME-Autostart-enabled=true
EOF
```

## Depannage Linux

| Probleme | Solution |
|----------|----------|
| Pas de son | `aplay -l` pour lister les cartes son, verifier `alsamixer` |
| pygame erreur SDL | `sudo apt install libsdl2-mixer-2.0-0` |
| Permission piper | `chmod +x /opt/av-speak/piper/piper` |
| Service ne demarre pas | `sudo journalctl -u av-speak -f` pour voir les logs |
| Chromium ne s'ouvre pas en kiosk | Verifier que `DISPLAY=:0` est defini |

## Configuration

### Ajouter des contacts
1. Aller sur http://127.0.0.1:8000/admin/login
2. Se connecter
3. Onglet "Contacts" : ajouter manuellement ou importer un CSV

### Format CSV pour import
Fichier `.csv` avec separateur point-virgule :
```
Nom;Prenom;Email;Telephone
Dupont;Jean;jean@mail.com;0612345678
Martin;Marie;marie@mail.com;0698765432
```

### Personnaliser les couleurs
1. Admin > Onglet "Apparence"
2. Choisir les couleurs
3. Enregistrer

## Depannage

| Probleme | Solution |
|----------|----------|
| "piper non trouve" | Verifier que `piper.exe` est dans `C:\AV-Speak\piper\` |
| Pas de son | Verifier les haut-parleurs dans les parametres Windows |
| Page ne charge pas | Verifier que `python app.py` tourne dans le terminal |
| Erreur au `pip install` | Verifier que Python est installe et dans le PATH |

## Architecture

```
Navigateur (kiosk plein ecran)
    |
    v
FastAPI (port 8000) --- SQLite (av_speak.db)
    |
    v
Piper TTS --> WAV --> pygame --> Haut-parleurs
```

Tout tourne en local sur le meme PC. Aucune connexion internet necessaire en fonctionnement.
