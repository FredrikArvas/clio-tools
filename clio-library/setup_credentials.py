#!/usr/bin/env python3
"""
Sparar Notion API-token till .env i samma mapp.
Kör en gång — enrich_books.py läser .env automatiskt vid start.

Användning:
    python setup_credentials.py
"""

import os
from pathlib import Path

ENV_FILE = Path(__file__).parent / ".env"


def main():
    print("\nNotion API-token setup")
    print("─" * 40)

    existing = None
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if line.startswith("NOTION_TOKEN="):
                existing = line.split("=", 1)[1].strip().strip('"').strip("'")
                break

    if existing:
        masked = existing[:10] + "..." + existing[-4:]
        print(f"Befintlig token: {masked}")
        overwrite = input("Skriv över? (j/N): ").strip().lower()
        if overwrite != "j":
            print("Avbrutet — befintlig token behålls.")
            return

    token = input("Klistra in din Notion Internal Integration Token: ").strip()
    if not token.startswith("secret_"):
        print("Varning: token ser inte rätt ut (ska börja med 'secret_'). Fortsätter ändå.")

    ENV_FILE.write_text(f"NOTION_TOKEN={token}\n", encoding="utf-8")
    print(f"\nToken sparad till: {ENV_FILE}")
    print("Kör nu: python enrich_books.py")


if __name__ == "__main__":
    main()
