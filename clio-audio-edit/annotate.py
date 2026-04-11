"""
annotate.py — Claude-annotering för clio-audio-edit.
Skickar transkript till Claude API och returnerar annoterat manus.
"""

import os
import sys
from pathlib import Path


def annotate_with_claude(transcript_text: str, profile_name: str) -> str:
    """
    Skickar transkript till Claude API med vald profil.
    Returnerar annoterat manus som sträng.
    """
    import anthropic
    from profiles import get_profile

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("\n[FEL] ANTHROPIC_API_KEY saknas i miljövariabler eller .env")
        print("      PowerShell: $env:ANTHROPIC_API_KEY = 'sk-ant-...'")
        sys.exit(1)

    profile = get_profile(profile_name)
    print(f"\n[INFO] Annoterar med Claude (profil: {profile_name})...")

    client = anthropic.Anthropic(api_key=api_key)

    user_message = f"""Här är transkriptet att annotera:

{transcript_text}

Gå igenom varje segment och markera BEHÅLL eller KLIPP enligt instruktionerna.
Skriv klippmarkeringar på en separat rad direkt under segmentet.
"""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        system=profile["system_prompt"],
        messages=[{"role": "user", "content": user_message}],
    )

    annotated = message.content[0].text
    print("       Annotering klar")
    return annotated


def save_annotated(annotated_text: str, output_path: Path) -> None:
    header = """# Annoterat manus — clio-audio-edit
#
# Granska och justera klippmarkeringarna nedan.
# Format: [KLIPP_START: HH:MM:SS | KLIPP_SLUT: HH:MM:SS]
# Ta bort en KLIPP-rad för att behålla det segmentet.
# Spara filen och kör sedan:
#   python clio-audio-edit.py --apply <den här filen> --input <originalljud>
#
# -----------------------------------------------------------------------

"""
    output_path.write_text(header + annotated_text, encoding="utf-8")
    print(f"       Annoterat manus sparat: {output_path.name}")
    print(f"\n[OK]  Öppna {output_path.name}, granska och justera.")
    print(f"      Kör sedan: python clio-audio-edit.py --apply {output_path.name} --input {output_path.stem.replace('_annotated', '')}.wav")
