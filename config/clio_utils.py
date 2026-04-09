"""
clio_utils.py
Shared utility functions for the clio-tools ecosystem.
"""

import re

__version__ = "2.2.0"

# Character mapping for Swedish/European characters
CHAR_MAP = str.maketrans({
    'å': 'a', 'ä': 'a', 'ö': 'o',
    'Å': 'A', 'Ä': 'A', 'Ö': 'O',
    'é': 'e', 'è': 'e', 'ê': 'e', 'ë': 'e',
    'á': 'a', 'à': 'a', 'â': 'a',
    'ü': 'u', 'ú': 'u', 'û': 'u',
    'ï': 'i', 'í': 'i', 'î': 'i',
    'ó': 'o', 'ô': 'o',
    'ñ': 'n',
    'ç': 'c',
})

# Characters not allowed in filenames
FORBIDDEN_CHARS = r'[(),\[\]|:;!?\'\"#&@$%^*+=<>{}\\]'


def sanitize_filename(name: str) -> str:
    """
    Sanitizes a filename by removing forbidden characters.
    Spaces, åäö and hyphens are preserved.

    Example:
        "Enuma Elish (Svensk översättning).pdf"
        → "Enuma Elish Svensk översättning.pdf"
    """
    if '.' in name:
        parts = name.rsplit('.', 1)
        base, ext = parts[0], '.' + parts[1]
    else:
        base, ext = name, ''

    # Remove forbidden characters
    base = re.sub(FORBIDDEN_CHARS, '', base)

    # Collapse multiple spaces
    base = re.sub(r' +', ' ', base).strip()

    return base + ext


def propose_rename(original: str) -> tuple:
    """
    Compares original name with sanitized version.
    Returns (needs_rename: bool, new_name: str).
    """
    new = sanitize_filename(original)
    return (new != original, new)


def has_non_ascii(s: str) -> bool:
    """Returns True if string contains non-ASCII characters."""
    return bool(re.search(r'[^\x00-\x7F]', s))


if __name__ == "__main__":
    # Quick test
    test_cases = [
        "Enuma Elish (Svensk översättning).pdf",
        "2024-08-03  Enuma Elish (Svensk översättning).pdf",
        "Secrets of Antigravity Propulsion_ Tesla, UFOs ( PDFDrive ).pdf",
        "2023-09-23 Forntida Astronauter - Gudarna Måste Vara Tokiga.pdf",
        "2024-07-15 Jättarnas Bok.pdf",
        "already_ok_name.pdf",
    ]
    print(f"clio_utils v{__version__} – sanitize_filename test\n")
    for t in test_cases:
        needs, new = propose_rename(t)
        status = "RENAME" if needs else "OK    "
        print(f"  {status}  {t}")
        if needs:
            print(f"         → {new}")


# ── i18n (internationalization) ───────────────────────────────────────────────

import json as _json
import os as _os
from pathlib import Path as _Path

_LOCALE_DIR = _Path(__file__).parent / "locales"
_STRINGS: dict = {}
_LANGUAGE: str = "sv"


def set_language(lang: str):
    """Set the UI language. Loads strings from config/locales/{lang}.json."""
    global _STRINGS, _LANGUAGE
    locale_file = _LOCALE_DIR / f"{lang}.json"
    fallback    = _LOCALE_DIR / "sv.json"

    for path in [locale_file, fallback]:
        if path.exists():
            try:
                data = _json.loads(path.read_text(encoding="utf-8"))
                _STRINGS = {k: v for k, v in data.items() if not k.startswith("_")}
                _LANGUAGE = lang
                return
            except:
                pass


def t(key: str, **kwargs) -> str:
    """
    Translate a UI string by key.
    Falls back to the key itself if not found.
    Supports named placeholders: t("files_found", n=5)
    """
    global _STRINGS
    if not _STRINGS:
        set_language(_LANGUAGE)
    text = _STRINGS.get(key, key)
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, ValueError):
            pass
    return text


def detect_language() -> str:
    """Auto-detect language from environment (LANG, LANGUAGE, LC_ALL)."""
    for env_var in ["LANG", "LANGUAGE", "LC_ALL"]:
        val = _os.environ.get(env_var, "")
        if val.startswith("sv"):
            return "sv"
        if val.startswith("en"):
            return "en"
    return "sv"  # Default to Swedish


def _load_language_from_state() -> str:
    """Read saved language from clio_state.json if available."""
    try:
        state_file = _Path(__file__).parent / "clio_state.json"
        if state_file.exists():
            data = _json.loads(state_file.read_text(encoding="utf-8"))
            lang = data.get("language")
            if lang:
                return lang
    except:
        pass
    return detect_language()


# Load language on import – state file takes priority over environment
set_language(_load_language_from_state())
