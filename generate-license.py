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

# IDENTIQUE a LICENSE_SECRET dans app.py
LICENSE_SECRET = b"5ed1966ecbfabb763c5bf26a54d6d7009804138ebb61dfc032e46ede38a84e1e"


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
