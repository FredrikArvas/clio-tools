"""ollama_screen.py — Lokal LLaVA-screening av UAP-kandidat-frames.

Skickar frames till Ollama (localhost:11434) med llava-modellen.
Används som billigt pre-filter innan Claude-analys.
Inga API-kostnader — allt lokalt på servern.
"""

from __future__ import annotations

import base64
import json
import urllib.request
import urllib.error
from pathlib import Path

from pipeline.motion_delta import AnomalyEvent

# Ollama API-endpoint (lokal server)
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llava:latest"

_SCREEN_PROMPT = """\
Look carefully at this image. It may be a frame from a slow-motion sky video.
Is there any object visible in the sky that cannot be identified as:
- a bird
- a conventional aircraft (airplane, helicopter)
- a drone
- a cloud or weather phenomenon
- lens flare or camera artifact

Answer with JSON only: {"uap_candidate": true/false, "confidence": 0.0-1.0, "description": "brief description of what you see"}
If the sky is empty or only contains identifiable objects, answer false.
"""


def _encode_image(path: str) -> str:
    with open(path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("utf-8")


def screen_frame(image_path: str, model: str = OLLAMA_MODEL) -> dict:
    """Skicka en frame till LLaVA. Returnerar {"uap_candidate": bool, "confidence": float, "description": str}."""
    payload = json.dumps({
        "model": model,
        "prompt": _SCREEN_PROMPT,
        "images": [_encode_image(image_path)],
        "stream": False,
        "format": "json",
    }).encode("utf-8")

    req = urllib.request.Request(
        OLLAMA_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = json.loads(resp.read())
            text = raw.get("response", "{}")
            data = json.loads(text) if isinstance(text, str) else text
            return {
                "uap_candidate": bool(data.get("uap_candidate", False)),
                "confidence": float(data.get("confidence", 0.0)),
                "description": str(data.get("description", "")),
            }
    except (urllib.error.URLError, json.JSONDecodeError, KeyError):
        # Ollama ej tillgänglig eller parse-fel → passa vidare till Claude ändå
        return {"uap_candidate": True, "confidence": 0.0, "description": "ollama_error"}


def screen_event(event: AnomalyEvent, model: str = OLLAMA_MODEL) -> dict:
    """Screena ett event: analysera peak-framen (starkast delta).

    Returnerar:
        {"keep": bool, "confidence": float, "description": str, "screened_frame": str}
    """
    if not event.frames:
        return {"keep": False, "confidence": 0.0, "description": "tomt event", "screened_frame": ""}

    # Välj framen med högst peak_delta som representant för eventet
    best = max(event.frames, key=lambda f: f.peak_delta)
    result = screen_frame(best.frame_path, model=model)

    return {
        "keep": result["uap_candidate"],
        "confidence": result["confidence"],
        "description": result["description"],
        "screened_frame": best.frame_path,
    }


def screen_events(
    events: list[AnomalyEvent],
    model: str = OLLAMA_MODEL,
    verbose: bool = True,
) -> list[tuple[AnomalyEvent, dict]]:
    """Screena alla events med LLaVA. Returnerar lista med (event, screen_result) för de som klarar filtret."""
    kept = []
    for ev in events:
        if verbose:
            print(f"  [ollama] Event {ev.event_id}/{len(events)} (peak={ev.peak:.1f})...", end="\r")
        result = screen_event(ev, model=model)
        if result["keep"]:
            kept.append((ev, result))
            if verbose:
                print(f"  [ollama] Event {ev.event_id} → BEHÅLLS  conf={result['confidence']:.2f} — {result['description'][:60]}")
        elif verbose:
            print(f"  [ollama] Event {ev.event_id} → filtreras (conf={result['confidence']:.2f})")

    if verbose:
        print(f"\n  LLaVA: {len(kept)}/{len(events)} events klarade pre-screen.\n")
    return kept
