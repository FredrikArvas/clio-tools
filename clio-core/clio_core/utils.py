"""
clio_core.utils
Shared utility functions for the clio-tools ecosystem.
"""

import json
import os
import re
from pathlib import Path

__version__ = "1.0.0"

# ── Filename sanitization ─────────────────────────────────────────────────────

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

FORBIDDEN_CHARS = r'[(),\[\]|:;!?\'\"#&@$%^*+=<>{}\\]'


def sanitize_filename(name: str) -> str:
    """
    Sanitizes a filename by removing forbidden characters.
    Spaces, åäö and hyphens are preserved.
    """
    if '.' in name:
        parts = name.rsplit('.', 1)
        base, ext = parts[0], '.' + parts[1]
    else:
        base, ext = name, ''
    base = re.sub(FORBIDDEN_CHARS, '', base)
    base = re.sub(r' +', ' ', base).strip()
    return base + ext


def propose_rename(original: str) -> tuple:
    """Returns (needs_rename: bool, new_name: str)."""
    new = sanitize_filename(original)
    return (new != original, new)


def has_non_ascii(s: str) -> bool:
    return bool(re.search(r'[^\x00-\x7F]', s))


# ── i18n ──────────────────────────────────────────────────────────────────────

_LOCALE_DIR = Path(__file__).parent / "locales"
_STRINGS: dict = {}
_LANGUAGE: str = "sv"


def set_language(lang: str) -> None:
    """Set the UI language. Loads strings from clio_core/locales/{lang}.json."""
    global _STRINGS, _LANGUAGE
    locale_file = _LOCALE_DIR / f"{lang}.json"
    fallback = _LOCALE_DIR / "sv.json"

    for path in [locale_file, fallback]:
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                _STRINGS = {k: v for k, v in data.items() if not k.startswith("_")}
                _LANGUAGE = lang
                return
            except Exception:
                pass


def t(key: str, **kwargs) -> str:
    """
    Translate a UI string by key. Falls back to the key itself if not found.
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
        val = os.environ.get(env_var, "")
        if val.startswith("sv"):
            return "sv"
        if val.startswith("en"):
            return "en"
    return "sv"


# Load language on import
set_language(detect_language())
