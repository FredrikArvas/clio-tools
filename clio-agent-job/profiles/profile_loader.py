"""
profile_loader.py
Läser en kandidatprofil från YAML och returnerar en dict.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

try:
    import yaml
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False

_DEFAULT_PROFILE = Path(__file__).parent / "richard.yaml"


def load_profile(path: Optional[Path] = None) -> dict:
    """
    Läser profil-YAML och returnerar en dict.
    Kastar ValueError om YAML saknas eller profilen är ogiltig.
    """
    if not _HAS_YAML:
        raise ImportError("PyYAML saknas — kör: pip install pyyaml")

    profile_path = path or _DEFAULT_PROFILE

    if not profile_path.exists():
        raise ValueError(f"Profilfil hittades inte: {profile_path}")

    with open(profile_path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    if not isinstance(data, dict):
        raise ValueError(f"Ogiltig profilfil (förväntade YAML-dict): {profile_path}")

    required = ["name", "role", "target_roles"]
    missing = [k for k in required if k not in data]
    if missing:
        raise ValueError(f"Profil saknar obligatoriska fält: {missing}")

    return data


def profile_summary(profile: dict) -> str:
    """Kortfattad textsammanfattning av profilen för loggning."""
    name = profile.get("name", "okänd")
    role = profile.get("role", "")
    geo = profile.get("geography", "")
    return f"{name} — {role} ({geo})"
