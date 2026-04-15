"""
registry.py
Laddar källinstanser från sources.yaml dynamiskt.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Optional

try:
    import yaml
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False

_SOURCES_DIR = Path(__file__).parent
if str(_SOURCES_DIR) not in sys.path:
    sys.path.insert(0, str(_SOURCES_DIR))

from source_base import BaseSource  # noqa: E402

_SOURCES_YAML = _SOURCES_DIR / "sources.yaml"


def load_sources(yaml_path: Optional[Path] = None) -> list[BaseSource]:
    """
    Läser sources.yaml och returnerar instantierade källobjekt (enabled: true).
    Fel vid enstaka källa loggas men stoppar inte övriga.
    """
    if not _HAS_YAML:
        raise ImportError("PyYAML saknas — kör: pip install pyyaml")

    path = yaml_path or _SOURCES_YAML
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    sources: list[BaseSource] = []

    for entry in data.get("sources", []):
        if not entry.get("enabled", False):
            continue

        adapter_str: str = entry["adapter"]   # t.ex. "source_rss.RssSource"
        config: dict = entry.get("config", {})

        try:
            module_name, class_name = adapter_str.rsplit(".", 1)
            module = importlib.import_module(module_name)
            cls = getattr(module, class_name)
            instance = cls(**config)
            sources.append(instance)
        except Exception as e:
            print(f"[VARNING] Kunde inte ladda källa '{entry.get('name', adapter_str)}': {e}")

    return sources
