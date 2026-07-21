"""
clio-vigil — ocr.py
=====================
Hanterar bildfiler som laddats ned istället för audio.

Flöde:
  downloaded-bild → ocr_image() → transkript i whisper-format → transcribed

Använder Claude Vision (claude-haiku) för att extrahera text och beskriva
bilden. Resultatet skrivs i samma JSON-format som whisper-transkript
(lista av segment med start/end/text) för att resten av pipelinen ska
kunna behandla det utan ändringar.
"""

import base64
import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

_here = Path(__file__).parent
load_dotenv(_here / ".env", override=True) or load_dotenv(_here.parent / ".env", override=True)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

logger = logging.getLogger(__name__)

TRANSCRIPTS_DIR = _here / "data" / "transcripts"

# Magic bytes för vanliga bildformat
_IMAGE_SIGNATURES = [
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG",      "image/png"),
    (b"GIF8",         "image/gif"),
    (b"RIFF",         "image/webp"),
]


def is_image_file(path: Path) -> bool:
    """Returnerar True om filen är ett känt bildformat."""
    try:
        header = path.read_bytes()[:12]
        return any(header[: len(sig)] == sig for sig, _ in _IMAGE_SIGNATURES)
    except OSError:
        return False


def _media_type(path: Path) -> str:
    header = path.read_bytes()[:12]
    for sig, mime in _IMAGE_SIGNATURES:
        if header[: len(sig)] == sig:
            return mime
    return "image/jpeg"


def ocr_image(path: Path, item_id: int, title: str = "") -> str | None:
    """
    OCR:ar en bild med Claude Vision.
    Returnerar extraherad text (eller bildbeskriving) som sträng, eller None vid fel.
    """
    if not ANTHROPIC_API_KEY:
        logger.error("ANTHROPIC_API_KEY saknas — kan inte OCR:a bild")
        return None

    try:
        import anthropic
    except ImportError:
        logger.error("anthropic saknas — kör: pip install anthropic")
        return None

    try:
        image_data = base64.standard_b64encode(path.read_bytes()).decode()
        media_type = _media_type(path)

        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_data,
                        },
                    },
                    {
                        "type": "text",
                        "text": (
                            "Extract all visible text from this image. "
                            "If there is little or no text, briefly describe what you see "
                            "(max two sentences). "
                            "Return only the text or description — no preamble."
                        ),
                    },
                ],
            }],
        )
        text = response.content[0].text.strip()
        logger.info(f"OCR klar för item {item_id}: {len(text)} tecken")
        return text

    except Exception as e:
        logger.error(f"OCR misslyckades för item {item_id}: {e}")
        return None


def write_image_transcript(item_id: int, ocr_text: str) -> tuple[Path, Path]:
    """
    Skriver OCR-texten som transkript i whisper-format (JSON + TXT).
    Returnerar (json_path, txt_path).
    """
    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)

    json_path = TRANSCRIPTS_DIR / f"vigil_{item_id}.json"
    txt_path  = TRANSCRIPTS_DIR / f"vigil_{item_id}.txt"

    segments = [{"start": 0.0, "end": 0.0, "text": ocr_text}]
    json_path.write_text(json.dumps(segments, ensure_ascii=False, indent=2), encoding="utf-8")
    txt_path.write_text(ocr_text, encoding="utf-8")

    return json_path, txt_path
