#!/usr/bin/env python3
"""
AV-Speak - Generateur de codes de licence

Usage :
    python3 generate-license.py --days 365
    python3 generate-license.py --days 365 --count 10

IMPORTANT : ce script doit contenir la MEME cle secrete que app.py.
Ne PAS distribuer ce script aux clients.
"""

import argparse
import hmac
import hashlib
import secrets
import sys
from pathlib import Path

# La cle est lue depuis license_secret.key (dans le meme dossier).
# Ce fichier doit etre IDENTIQUE a celui utilise par app.py sur les installations client.
SECRET_FILE = Path(__file__).resolve().parent / "license_secret.key"

if not SECRET_FILE.exists():
    print(f"ERREUR : {SECRET_FILE} introuvable.", file=sys.stderr)
    print("Creez ce fichier (contenu = votre cle secrete binaire) et deployez-le", file=sys.stderr)
    print("aux installations client pour que les codes soient valides.", file=sys.stderr)
    sys.exit(1)

LICENSE_SECRET = SECRET_FILE.read_bytes().strip()


def generate_code(days: int) -> str:
    """Genere un code de licence de `days` jours."""
    if days <= 0 or days > 36500:
        raise ValueError("days doit etre entre 1 et 36500")
    serial = secrets.token_hex(4).upper()  # 8 chars hex
    payload = f"{serial}-{days}".encode()
    sig = hmac.new(LICENSE_SECRET, payload, hashlib.sha256).hexdigest()[:8].upper()
    return f"AVSP-{serial}-{days}-{sig}"


def main():
    parser = argparse.ArgumentParser(description="Generateur de codes de licence AV-Speak")
    parser.add_argument("--days", type=int, required=True,
                        help="Nombre de jours de validite (ex: 365 pour 1 an)")
    parser.add_argument("--count", type=int, default=1,
                        help="Nombre de codes a generer (defaut: 1)")
    args = parser.parse_args()

    print(f"# {args.count} code(s) AV-Speak - {args.days} jours")
    print("#" + "=" * 48)
    for _ in range(args.count):
        print(generate_code(args.days))


if __name__ == "__main__":
    main()
