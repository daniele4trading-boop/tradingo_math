"""Genera hash password + secret_key per webapp_config.json.

Uso (da C:\\TG_TradinGo):
    python -m webapp.hash_password
"""

from __future__ import annotations

import getpass
import secrets

from webapp.auth import hash_password


def main() -> None:
    pwd = getpass.getpass("Password da hashare: ")
    if len(pwd) < 8:
        print("ATTENZIONE: password corta (<8 caratteri).")
    confirm = getpass.getpass("Ripeti password: ")
    if pwd != confirm:
        print("Le password non coincidono.")
        raise SystemExit(1)
    print()
    print("password_hash:")
    print(f"  {hash_password(pwd)}")
    print()
    print("secret_key (nuovo, usalo se non ne hai gia' uno):")
    print(f"  {secrets.token_hex(32)}")


if __name__ == "__main__":
    main()
