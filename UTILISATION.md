# AV-Speak - Guide d'utilisation

Guide pour les **administrateurs** du logiciel (personne responsable de la
configuration et de la maintenance au quotidien).

---

## Premiere connexion

### 1. Acceder a l'interface admin

Sur n'importe quel ordinateur **sur le meme reseau** que la borne, ouvrez un
navigateur et allez a :

```
http://IP-DE-LA-BORNE:8000/admin/login
```

(Pour trouver l'IP de la borne : sur la borne, appuyez `Ctrl+Alt+F2`, connectez-vous
avec votre compte et tapez `ip addr`.)

### 2. Se connecter

- **Identifiant** : `admin`
- **Mot de passe** : `admin`

### 3. Accepter les CGU

A la premiere connexion (et a chaque nouvelle connexion ensuite), vous devez
lire et accepter les conditions generales d'utilisation. Cliquez sur
**"J'accepte"** en bas de la page.

### 4. Changer le mot de passe

Allez dans l'onglet **Mot de passe** et changez-le immediatement. Minimum 4
caracteres, mais choisissez un mot de passe robuste.

### 5. Activer votre licence

Allez dans l'onglet **Licence** et saisissez le code fourni par le vendeur.
Format du code : `AVSP-XXXXXXXX-XXX-XXXXXXXX`.

- Sans activation : 30 jours d'essai
- A l'expiration : le kiosque visiteur est **bloque** (popup rouge), l'admin reste accessible

---

## Gestion des contacts

Onglet **Contacts**.

### Ajouter un contact manuellement

Remplissez le formulaire :
- **Civilite** : Monsieur / Madame / Non precise
- **Nom** (obligatoire)
- **Prenom** (obligatoire)
- **Email** (optionnel, pour les notifications)
- **Telephone** (optionnel, pour les SMS)

Cliquez sur **Ajouter**.

### Importer des contacts en masse (CSV)

Creez un fichier Excel / LibreOffice avec les colonnes :

```
Nom;Prenom;Civilite;Email;Telephone
Dupont;Jean;M;jean.dupont@mail.com;0612345678
Martin;Marie;Mme;marie.martin@mail.com;0698765432
Tran;Kim;X;;
```

Enregistrez en **CSV separe par point-virgule** (`;`). Puis :
1. Cliquez **Choisir un fichier**
2. Selectionnez votre `.csv`
3. Cliquez **Importer**

Les contacts sont ajoutes en masse. Pas de mise a jour : si vous reimportez
avec des modifications, vous aurez des doublons. Pour mettre a jour, editez
ou supprimez les contacts existants d'abord.

### Modifier un contact

Dans le tableau, cliquez **Modifier** sur la ligne du contact. Les champs
deviennent editables. Modifiez et cliquez **Sauver**.

### Supprimer un contact

Cliquez **Supprimer** sur la ligne voulue. Une confirmation est demandee.

### Ordre d'affichage sur le kiosque

Les 6 contacts les plus appeles sont affiches en gros boutons "Contacts frequents"
sur le kiosque. Ce classement est automatique (colonne **Appels** dans le tableau).

Pour remettre les compteurs a zero : actuellement il faut passer par SQLite
directement (fonctionnalite a venir si besoin).

---

## Personnaliser l'apparence du kiosque

Onglet **Apparence**.

### Logo

Uploadez un fichier PNG, JPG, SVG ou WebP. Il s'affichera en haut du kiosque
au-dessus du nom de l'entreprise. Dimensions recommandees : 300x100 max.

### Nom de l'entreprise

Affiche en gros titre sur le kiosque.

### Couleurs

Six couleurs personnalisables :
- **Couleur principale** : titres, cadre de focus
- **Fond de page** : background general
- **Fond des cartes** : cartes de contact
- **Texte** : couleur des textes
- **Boutons** : fond des boutons d'action
- **Texte des boutons** : couleur du texte dans les boutons

Utilisez un pipette de couleur pour assortir a votre charte graphique.

### Phrase d'annonce

C'est ce que Piper va prononcer. Modeles disponibles :
- `{civilite}` : remplace par "Monsieur", "Madame" ou rien
- `{prenom}` : prenom du contact
- `{nom}` : nom du contact

Exemple : `{civilite} {prenom} {nom} est demande a l'accueil` →
"Monsieur Jean Dupont est demande a l'accueil"

### Diffusion du message

- **Nombre de diffusions** : 1, 2, 3, 5 ou illimite
  - 1 fois : annonce unique, retour automatique
  - Plusieurs fois : repetition avec un bouton Valider sur le kiosque
  - Illimite : repetition jusqu'a ce que le visiteur valide
- **Delai entre diffusions** : 10, 20, 30, 60 ou 90 secondes

Pendant la repetition, le kiosque affiche un compte a rebours et un bouton
**Valider** rouge pour stopper.

### Prise de contact visiteur

Si **activee** : au moment de l'annonce, le visiteur peut entrer son nom et
email. Ces infos apparaissent dans l'email/SMS envoye a la personne visitee
mais ne sont **pas stockees** en base.

Si **desactivee** : champs caches, uniquement l'annonce vocale.

### Texte d'instruction (kiosk)

Texte libre affiche en haut du kiosque pour expliquer la procedure au visiteur.
Exemple : "Bienvenue, recherchez votre contact et validez votre appel".

Supporte les retours a la ligne.

### Image d'instruction (kiosk)

Upload d'une image (PNG, JPG, SVG, WebP, GIF) affichee sous le texte d'instruction.
Utile pour un schema, un pictogramme, etc.

### Taille du contenu kiosk

Trois tailles : **Classique** (par defaut), **Petit**, **Tres petit**.
Utile si vous avez un ecran peu haut.

### Taille du clavier virtuel

Cinq tailles :
- **S** : petit ecran
- **M** : ecran standard (par defaut)
- **L** : grand ecran
- **XL** : tres grand ecran
- **XXL** : ecran 4K / panneau tactile

Le clavier apparait automatiquement au clic sur un champ texte, ou en cliquant
sur le bouton rond en bas a droite du kiosque.

---

## Notifications email / SMS

Onglet **Notifications**.

### Activer les notifications

**Envoyer lors d'une annonce** : Oui / Non.

Si Non, aucun email/SMS n'est envoye, meme si les parametres SMTP/OVH sont remplis.

### Configuration SMTP (email)

Pour Gmail, Outlook, ou votre serveur d'entreprise :
- **Activer** : Oui
- **Serveur SMTP** : ex. `smtp.gmail.com`
- **Port** : 587 (TLS) ou 465 (SSL)
- **TLS** : Oui (recommande)
- **Identifiant** : votre email (ex. `accueil@entreprise.com`)
- **Mot de passe** : mot de passe ou mot de passe d'application (Gmail, etc.)
- **Adresse expediteur** : email qui apparaitra comme expediteur

Puis renseignez le **modele d'email** :
- **Objet** : utilise les variables comme la phrase d'annonce
- **Corps** : variables disponibles : `{civilite}`, `{nom}`, `{prenom}`, `{entreprise}`,
  `{visiteur_nom}`, `{visiteur_email}`

Cliquez **Tester l'envoi email** : un email test est envoye a l'adresse
expediteur. Si vous voyez "Email de test envoye", c'est bon.

### Configuration SMS (OVH API)

Vous devez avoir un compte OVH avec des credits SMS.

1. Sur [api.ovh.com/createToken](https://api.ovh.com/createToken/), generez
   **Application Key**, **Application Secret** et **Consumer Key** avec les
   droits : `GET /sms`, `POST /sms/*/jobs`
2. Recuperez le **nom du service SMS** (format `sms-xxxxx-1`) dans votre
   manager OVH

Remplissez :
- **Activer** : Oui
- **Endpoint** : `ovh-eu` (Europe) ou `ovh-ca` (Canada)
- **Application Key** / **Application Secret** / **Consumer Key**
- **Nom du service SMS**
- **Expediteur** (optionnel, max 11 caracteres, sans espaces)

Modele SMS : variables disponibles : `{civilite}`, `{nom}`, `{prenom}`,
`{entreprise}`, `{visiteur_nom}`.

Testez avec **Tester l'envoi SMS** + un numero de telephone.

---

## Registre de securite

Onglet **Registre**.

### A quoi ca sert

Tracer les visiteurs **presents sur site** avec un bouton "Quitter" sur le kiosque.
Utile pour un suivi ERP, une PPMS, etc.

**ATTENTION** : ce n'est pas un registre de securite conforme aux normes
reglementaires. C'est un outil d'aide au suivi.

### Activation

- **Activer le registre de securite** : Oui
- **Conserver l'historique des visites** : Oui (garde les departs) / Non (supprime au depart)

### Consequences cote kiosque

Quand active, le visiteur DOIT saisir son **nom, prenom** (et entreprise en
option) pour declencher une annonce. Une fois l'annonce faite, son nom apparait
sur le kiosque dans la section "Visiteurs presents" avec un bouton rouge
**Quitter**.

Au depart, il appuie sur **Quitter** → sa fiche disparait (ou passe dans
l'historique selon le reglage).

### Consultation

Dans l'onglet Registre, vous voyez :
- **Visiteurs presents** en temps reel avec nom, entreprise, personne visitee, heure d'arrivee
- **Historique** (si active) : jusqu'a 100 dernieres visites cloturees

Bouton **Purger l'historique** pour vider l'historique (confirmation requise).

---

## Licence / abonnement

Onglet **Licence**.

### Statut actuel

Affiche :
- **Active** (vert) : date d'expiration + jours restants
- **Bientot expiree** (jaune) : moins de 7 jours restants
- **Expiree** (rouge) : kiosque bloque

### Renouveler

Saisissez le code recu du vendeur au format `AVSP-XXXXXXXX-XXX-XXXXXXXX`.
Cliquez **Activer**. Les jours s'ajoutent a la date d'expiration actuelle.

Si expiree : les jours s'ajoutent a la **date du jour**.

### A savoir

- Un code ne peut etre utilise qu'une seule fois par installation
- Si vous changez de machine, votre ancien code reste valide (nouvelle base = nouvelle activation)
- Pendant la periode de grace (7 derniers jours) : bandeau jaune sur le kiosque

---

## CGU

Onglet **CGU**. Lecture des conditions generales d'utilisation, acceptees a chaque
connexion admin. Rappelle notamment :
- Vous etes seul responsable de la conformite RGPD des donnees saisies
- Le registre de securite n'est pas conforme aux normes reglementaires
- Le logiciel est fourni en l'etat, sans garantie

---

## Mot de passe

Onglet **Mot de passe**.

Changement du mot de passe admin. Il faut entrer le mot de passe actuel + le nouveau (min 4 caracteres).

---

## Utilisation cote visiteur (kiosque)

### Parcours standard

1. Le visiteur arrive devant la borne
2. Il **tape les premieres lettres** du nom de sa personne contact
3. La liste des contacts correspondants apparait
4. Il **touche le bon contact**
5. Une **popup de confirmation** s'affiche
6. (Si active) Il saisit son nom / email
7. (Si registre) Il saisit son nom / prenom / entreprise (obligatoire)
8. Il touche **Confirmer**
9. La voix annonce "Monsieur Jean Dupont est demande a l'accueil"
10. Si repetition activee : un compte a rebours et le bouton Valider apparaissent
11. Si registre actif : sa fiche reste visible avec un bouton Quitter

### Parcours "contacts frequents"

Au lieu de taper, le visiteur touche directement l'un des 6 boutons
"Contacts frequents" affiches en dessous de la barre de recherche.

### Remise a zero automatique

Si personne ne touche l'ecran pendant 30 secondes, le kiosque revient a
l'accueil (sauf si une annonce est en cours).

---

## Mise a jour du logiciel

Sur la borne, en SSH ou au terminal (`Ctrl+Alt+F2`) :

```bash
cd /chemin/vers/AV-Speak      # ou vous avez clone le repo
git pull
sudo cp app.py /opt/av-speak/
sudo cp -r templates/ /opt/av-speak/
sudo cp -r static/ /opt/av-speak/
sudo systemctl restart av-speak
```

Ou, pour faciliter, relancez le script d'installation (il est idempotent) :

```bash
sudo bash installation-complete.sh
```

Les donnees (contacts, visiteurs, licence, parametres) sont preservees.

---

## Sauvegarde et restauration

### Fichiers a sauvegarder

```
/opt/av-speak/av_speak.db          # Tout : contacts, visiteurs, parametres, licence
/opt/av-speak/static/logo.*        # Logo (si uploade)
/opt/av-speak/static/kiosk_instruction.*  # Image d'instruction (si uploadee)
```

### Commande de sauvegarde

```bash
sudo tar czf /tmp/av-speak-backup-$(date +%Y%m%d).tar.gz \
  /opt/av-speak/av_speak.db \
  /opt/av-speak/static/logo.* \
  /opt/av-speak/static/kiosk_instruction.* 2>/dev/null
```

Copiez le fichier `.tar.gz` en lieu sur.

### Restauration

```bash
sudo systemctl stop av-speak
sudo tar xzf /tmp/av-speak-backup-YYYYMMDD.tar.gz -C /
sudo systemctl start av-speak
```

---

## Problemes courants

### "Licence expiree" alors que j'ai saisi un code

- Le code est-il valide (format `AVSP-XXXXXXXX-XXX-XXXXXXXX`) ?
- A-t-il deja ete utilise sur cette installation ?
- Contactez le vendeur pour un nouveau code.

### L'annonce n'est pas prononcee

- Verifier que les haut-parleurs fonctionnent : `aplay -l`
- Regler le volume : `amixer sset Master 90%`
- Tester Piper : `/opt/av-speak/piper/piper --help`
- Regarder les logs : `sudo journalctl -u av-speak -f`

### L'email ne part pas

- Cliquez **Tester l'envoi email** dans l'onglet Notifications
- Verifiez identifiant/mot de passe SMTP
- Pour Gmail : activez un mot de passe d'application (pas votre mot de passe principal)
- Pensez aux blocages pare-feu sur le port 587

### Le SMS ne part pas

- Cliquez **Tester l'envoi SMS** + un numero valide
- Verifiez le solde de credits SMS chez OVH
- Verifiez les cles API (y compris le Consumer Key, souvent oublie)
- Verifiez que le numero est au bon format : `+33612345678`

### Le kiosque ne demarre pas au boot

- Verifier le service : `sudo systemctl status av-speak`
- Verifier les logs : `sudo journalctl -u av-speak -f`
- Verifier que le kiosque Chromium se lance : passer sur TTY1 avec `Ctrl+Alt+F1`
- Relancer manuellement : `sudo systemctl restart av-speak`

### Le clavier virtuel n'apparait pas

- Cliquez dans un champ texte
- Ou cliquez sur le bouton rond en bas a droite de l'ecran
- Sinon : augmentez la taille dans Admin > Apparence > Clavier virtuel

### J'ai oublie le mot de passe admin

Par SSH :

```bash
sudo sqlite3 /opt/av-speak/av_speak.db "DELETE FROM users WHERE username='admin';"
sudo systemctl restart av-speak
```

Le mot de passe sera reinitialise a `admin` / `admin` au prochain demarrage.

---

## Acces technique

### Terminal local sur la borne

- `Ctrl+Alt+F2` : acceder au terminal
- `Ctrl+Alt+F1` : revenir au kiosque

### SSH distant

Depuis un autre ordinateur sur le meme reseau :

```bash
ssh utilisateur@IP-DE-LA-BORNE
```

(L'utilisateur `kiosk` est celui qui affiche le kiosque, pas pour se connecter
en SSH — utilisez votre compte admin.)

### Fichiers importants

| Chemin | Contenu |
|--------|---------|
| `/opt/av-speak/app.py` | Code principal |
| `/opt/av-speak/av_speak.db` | Base de donnees |
| `/opt/av-speak/tts_cache/` | Cache des fichiers audio |
| `/opt/av-speak/static/` | Logos, CSS |
| `/opt/av-speak/templates/` | Pages HTML |
| `/etc/systemd/system/av-speak.service` | Service systemd |
| `/home/kiosk/.config/openbox/autostart` | Config kiosque |

---

## Comportement en cas de coupure

- **Coupure electrique** : au retour du courant, la borne redemarre automatiquement
  et le kiosque reprend apres ~30 secondes
- **Coupure reseau** : aucun impact sur le fonctionnement du kiosque (tout est local).
  Seuls les emails/SMS ne partent pas si pas d'internet.
- **Panne de Piper** : les annonces vocales ne se font pas, mais l'application
  reste fonctionnelle et les notifications continuent de partir
