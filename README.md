# AV-Speak

Systeme d'annonce vocale de visiteurs pour l'accueil d'entreprise, fonctionnant
100% hors-ligne sur une borne tactile.

![Licence](https://img.shields.io/badge/usage-commercial-blue)
![Plateforme](https://img.shields.io/badge/platform-Ubuntu%2024.04%20LTS-orange)
![Statut](https://img.shields.io/badge/statut-production-green)

---

## A quoi ca sert

Un visiteur arrive a l'accueil. Il cherche la personne qu'il vient voir sur un ecran
tactile, la selectionne, et une voix annonce :

> "Monsieur Jean Dupont est demande a l'accueil"

En parallele, un email et/ou un SMS sont envoyes a la personne visitee pour la
prevenir. Un registre de securite (optionnel) permet de suivre les visiteurs presents.

---

## Fonctionnalites principales

### Cote visiteur (kiosque tactile)
- **Recherche de contact** avec suggestions en temps reel
- **Contacts frequents** affiches en gros boutons
- **Annonce vocale** (TTS francais offline via Piper)
- **Repetition** configurable du message (1 a illimite)
- **Bouton Valider** pour stopper les repetitions
- **Clavier virtuel** integre (5 tailles ajustables, AZERTY)
- **Champs visiteur** optionnels (nom, email) pour la notification
- **Registre de securite** (optionnel) avec bouton "Quitter" pour chaque visiteur present

### Cote administrateur (interface web)
- Gestion des contacts (ajout, import CSV, edition, suppression)
- Personnalisation (logo, couleurs, phrase d'annonce)
- Notifications email (SMTP) et SMS (OVH API)
- Parametres de diffusion (nombre de repetitions, delai entre repetitions)
- Registre de securite avec historique
- Licence d'utilisation sur abonnement
- CGU avec acceptation obligatoire

### Cote technique
- **100% offline** : aucune donnee ne sort de la machine
- **Base SQLite** locale
- **Demarrage automatique** au boot (service systemd + kiosque auto-login)
- **Ecran de veille desactive** sur la borne
- **Cache audio** pour reduire la latence des annonces repetees

---

## Documentation

| Fichier | Pour qui ? | Contenu |
|---------|-----------|---------|
| [DEPLOIEMENT.md](DEPLOIEMENT.md) | Integrateur / technicien | Installation sur Ubuntu Server, configuration systeme |
| [UTILISATION.md](UTILISATION.md) | Administrateur / utilisateur final | Prise en main de l'interface admin, gestion quotidienne |
| [LICENCE-SYSTEME.md](LICENCE-SYSTEME.md) | Vendeur | Generation de codes, gestion des abonnements |

---

## Installation rapide

Sur un Ubuntu Server 24.04 LTS fraichement installe :

```bash
sudo apt update && sudo apt install git -y
git clone https://github.com/CedricNCoding/AV-Speak.git
cd AV-Speak
sudo bash installation-complete.sh
sudo reboot
```

Apres redemarrage, la borne est operationnelle. Acces admin :
`http://IP-DE-LA-MACHINE:8000/admin/login` (admin / admin).

Guide detaille : [DEPLOIEMENT.md](DEPLOIEMENT.md).

---

## Stack technique

| Composant | Role |
|-----------|------|
| Python 3.11+ / FastAPI | Serveur web et API |
| SQLite | Base de donnees locale |
| Piper TTS | Synthese vocale offline (voix francaise) |
| Jinja2 | Templates HTML |
| bcrypt | Hash des mots de passe |
| OVH SDK | Envoi de SMS |
| smtplib | Envoi d'emails |
| Chromium (kiosk) | Affichage plein ecran tactile |
| Openbox / X.org | Environnement graphique minimal |
| systemd | Demarrage automatique |

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│               ECRAN TACTILE (borne)                     │
│          Chromium --kiosk plein ecran                   │
└──────────────────────────┬──────────────────────────────┘
                           │ HTTP (localhost:8000)
                           ▼
┌─────────────────────────────────────────────────────────┐
│                    FastAPI / app.py                     │
│   ┌──────────┐  ┌─────────────┐  ┌──────────────────┐   │
│   │  Routes  │  │  Templates  │  │  API JSON (TTS)  │   │
│   └──────────┘  └─────────────┘  └──────────────────┘   │
└───────┬──────────────────┬─────────────────────┬────────┘
        │                  │                     │
        ▼                  ▼                     ▼
┌───────────────┐  ┌──────────────┐  ┌──────────────────┐
│ SQLite        │  │ Piper TTS    │  │ SMTP / OVH API   │
│ (contacts,    │  │ --> WAV      │  │ (notifications)  │
│  visitors,    │  │ tts_cache/   │  │                  │
│  settings)    │  │              │  │                  │
└───────────────┘  └──────────────┘  └──────────────────┘
```

Toute la stack tourne sur **une seule machine**. Aucune connexion internet
n'est necessaire en fonctionnement (les notifications email/SMS sont optionnelles).

---

## Structure du depot

```
AV-Speak/
├── app.py                        # Application FastAPI (point d'entree)
├── requirements.txt              # Dependances Python
├── installation-complete.sh      # Script d'installation tout-en-un
├── install.sh                    # Installation de l'appli seule
├── setup-kiosk.sh                # Configuration kiosque seule
├── generate-license.py           # Generateur de codes licence (vendeur)
├── templates/                    # Templates HTML
│   ├── kiosk.html                # Interface visiteur
│   ├── admin.html                # Interface administrateur
│   ├── login.html                # Page de connexion admin
│   └── cgu.html                  # Acceptation des CGU
├── static/
│   └── style.css                 # Styles communs
├── DEPLOIEMENT.md                # Guide de deploiement
├── UTILISATION.md                # Guide utilisateur admin
├── LICENCE-SYSTEME.md            # Systeme de licence
└── README.md                     # Ce fichier
```

---

## Licence et conditions d'utilisation

- **Usage commercial** sur abonnement (voir [LICENCE-SYSTEME.md](LICENCE-SYSTEME.md))
- **CGU** integrees et acceptees a chaque connexion admin
- Le client est **seul responsable** de la conformite RGPD des donnees qu'il saisit
- La fonctionnalite "Registre de securite" **n'est pas un registre de securite conforme**
  aux normes reglementaires (outil d'aide uniquement)

---

## Support

- **Issues / bugs** : via le systeme d'issues du depot (ou email vendeur)
- **Mise a jour** : `git pull` dans le repo, puis redeployer (voir DEPLOIEMENT.md)
