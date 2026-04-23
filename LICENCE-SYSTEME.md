# AV-Speak - Systeme de licence

Documentation du systeme d'abonnement base sur des codes signes HMAC.

---

## Principe

- AV-Speak fonctionne hors-ligne (aucune communication serveur).
- Chaque installation client a une **date d'expiration** stockee en base.
- A l'expiration, le kiosque est bloque par une popup rouge.
- Le client saisit un **code de licence** dans l'admin pour etendre la duree.
- Les codes sont generes par le vendeur avec une cle secrete partagee.

---

## Architecture

### Cle secrete (`license_secret.key`)

- Fichier binaire place a la racine du projet : `/opt/av-speak/license_secret.key`
- **Gitignore** : ce fichier N'EST JAMAIS commite sur Git
- Meme contenu sur :
  - La machine du vendeur (pour generer les codes)
  - Chaque installation client (pour valider les codes)
- Sans ce fichier, le logiciel tourne en **mode essai** avec une cle aleatoire
  (aucun code vendeur ne fonctionnera).

### Format des codes

```
AVSP-A3F2B9C8-365-1E7F9A2D
```

| Partie | Contenu |
|--------|---------|
| `AVSP` | Prefixe fixe |
| `A3F2B9C8` | Numero de serie unique (8 hex) |
| `365` | Nombre de jours ajoutes |
| `1E7F9A2D` | Signature HMAC-SHA256 tronquee |

### Base de donnees

Table `used_licenses` dans `av_speak.db` :

```sql
serial TEXT PRIMARY KEY
days INTEGER
activated_at TEXT
```

Settings lies :
- `license_expiry` : date ISO (YYYY-MM-DD)
- `license_last_seen` : derniere date vue par l'app (anti-recul d'horloge)

---

## Workflow vendeur (premiere fois)

### 1. Generer votre cle secrete (UNE SEULE FOIS)

Sur votre machine :

```bash
cd /chemin/vers/AV-Speak
python3 -c "import secrets; open('license_secret.key','wb').write(secrets.token_hex(32).encode())"
```

**IMPORTANT** :
- Sauvegardez ce fichier dans un endroit sur (coffre-fort numerique, pas sur Git)
- Si vous le perdez, tous les codes generes precedemment seront inutilisables
- Si vous le changez, tous les anciens codes deviennent invalides

### 2. Generer des codes

```bash
# Un code de 1 an
python3 generate-license.py --days 365

# 10 codes de 1 an
python3 generate-license.py --days 365 --count 10

# Un code d'essai de 30 jours
python3 generate-license.py --days 30

# Un code de 1 mois
python3 generate-license.py --days 30

# Un code de 3 ans
python3 generate-license.py --days 1095
```

Chaque appel genere des codes uniques (numero de serie aleatoire).

### 3. Livrer les codes aux clients

Transmettez le code au client par email, SMS, ou papier. Format :

```
AVSP-A3F2B9C8-365-1E7F9A2D
```

---

## Workflow deploiement client

### Premiere installation

1. Installer AV-Speak (voir `DEPLOIEMENT.md`)
2. Par defaut : **essai de 30 jours** (cle aleatoire auto-generee)
3. Deployer votre cle secrete sur le poste :

```bash
# Copier license_secret.key vers le serveur client (SCP, SSH, USB...)
scp license_secret.key utilisateur@ip-client:/tmp/
ssh utilisateur@ip-client "sudo mv /tmp/license_secret.key /opt/av-speak/ && sudo systemctl restart av-speak"
```

4. Le client entre son code dans Admin > Licence

### Renouvellement

Le client entre simplement un nouveau code dans Admin > Licence. Les jours
s'ajoutent a la date d'expiration actuelle (ou a la date du jour si expire).

---

## Comportement en cas d'expiration

### Kiosque visiteur
- **Popup rouge bloquante** : "Licence d'utilisation expiree"
- Impossible d'annoncer un visiteur
- Bouton "Acces administrateur" pour aller sur l'admin

### Administration
- Reste **accessible normalement**
- Bandeau rouge dans l'onglet Licence
- Possibilite de saisir un nouveau code

### Bannieres d'avertissement
- **7 jours avant expiration** : bandeau jaune sur le kiosque et l'admin

---

## Sécurité et limites connues

| Risque | Mitigation |
|--------|-----------|
| Code partage entre plusieurs clients | Serial unique trace en base, chaque code ne sert qu'une fois par install |
| Client recule l'horloge pour gagner du temps | `license_last_seen` stocke la derniere date vue — l'app utilise le max entre now et last_seen |
| Restauration d'une ancienne sauvegarde SQLite | Non detecte — le client retrouve l'ancienne expiration. Risque accepte. |
| Extraction de la cle secrete | La cle n'est pas dans le code source. Elle doit etre deployee manuellement. Protegez l'acces SSH/root du serveur client. |
| Reverse-engineering pour generer des codes | L'algorithme est public (HMAC-SHA256) mais sans la cle, impossible de generer un code valide. |

---

## Fichiers du systeme de licence

| Fichier | Role | Sur Git ? |
|---------|------|-----------|
| `app.py` | Validation + routes admin (`/admin/license/activate`) | Oui |
| `generate-license.py` | Script generateur de codes (vendeur) | Oui |
| `license_secret.key` | Cle HMAC partagee | **NON** (gitignore) |
| `templates/admin.html` | Onglet "Licence" | Oui |
| `templates/kiosk.html` | Popup rouge et banniere jaune | Oui |

---

## API

### `GET /api/license` (public)
```json
{
  "expiry": "2027-04-23",
  "days_left": 365,
  "expired": false,
  "warning": false
}
```

### `POST /admin/license/activate` (admin)
Form : `code=AVSP-...`

Reponses :
```json
{"status": "ok", "message": "Licence etendue de 365 jours", "new_expiry": "2028-04-23"}
{"status": "error", "message": "Code invalide"}
{"status": "error", "message": "Ce code a deja ete utilise"}
```

---

## Depannage

| Symptome | Cause probable | Solution |
|----------|---------------|----------|
| "Mode essai" dans les logs | `license_secret.key` manquant | Deployer le fichier sur `/opt/av-speak/` |
| Code refuse "Code invalide" | Cle secrete differente entre vendeur et client | Verifier que les deux fichiers ont le meme contenu |
| Code refuse "Deja utilise" | Le numero de serie existe en base | Generer un nouveau code avec `generate-license.py` |
| Kiosque bloque en permanence | Expiration depassee ET pas de code | Aller sur `/admin/login` et saisir un code valide |
| Changer la cle secrete apres vente | Tous les anciens codes deviennent invalides | Eviter absolument. Garder la cle initiale. |

---

## Changer la politique d'essai

Editer dans `app.py` :

```python
TRIAL_DAYS = 30           # Duree essai (jours)
EXPIRY_WARNING_DAYS = 7   # Duree avant expiration pour afficher le bandeau
```

Puis redemarrer : `sudo systemctl restart av-speak`.

**Note** : cela n'affecte que les NOUVELLES installations. Pour modifier
l'expiration d'une installation existante, il faut editer la base SQLite
manuellement ou entrer un code.
