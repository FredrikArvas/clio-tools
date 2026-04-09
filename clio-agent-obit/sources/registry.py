"""
sources/registry.py — Laddar källor från sources.yaml

I 0.2.0 ersätter detta den tidigare hårdkodade listan i run.py.
Nya källor läggs till genom att redigera sources.yaml — ingen Python-ändring.

YAML-format:
    version: 1
    sources:
      - name: familjesidan-stockholm
        enabled: true
        adapter: source_familjesidan_html.FamiljesidanHtmlSource
        config:
          base_url: https://www.familjesidan.se
          newspapers: [461]
"""

from __future__ import annotations

import importlib
import os
from typing import Optional

try:
    import yaml
except ImportError:
    raise ImportError("pyyaml saknas. Kör: pip install pyyaml")

from sources.source_base import ObituarySource

DEFAULT_REGISTRY = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "sources.yaml",
)


class RegistryError(Exception):
    """Fel vid läsning av sources.yaml eller instansiering av en källa."""
    pass


def load_sources(path: Optional[str] = None) -> list[ObituarySource]:
    """
    Läser sources.yaml och returnerar en lista av instansierade källor.
    Skipar entries med enabled: false. En kraschande adapter loggas
    men stoppar inte hela laddningen.
    """
    yaml_path = path or DEFAULT_REGISTRY
    if not os.path.exists(yaml_path):
        raise RegistryError(f"sources.yaml saknas: {yaml_path}")

    with open(yaml_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    entries = data.get("sources", [])
    if not isinstance(entries, list):
        raise RegistryError("sources.yaml: 'sources' måste vara en lista")

    sources: list[ObituarySource] = []
    for entry in entries:
        if not entry.get("enabled", True):
            continue
        name = entry.get("name", "okänd")
        adapter = entry.get("adapter", "")
        config = entry.get("config", {}) or {}

        if "." not in adapter:
            print(f"[registry] '{name}': ogiltig adapter '{adapter}' — hoppar över")
            continue

        module_name, class_name = adapter.rsplit(".", 1)
        try:
            module = importlib.import_module(f"sources.{module_name}")
            cls = getattr(module, class_name)
            instance = cls(**config)
            # Sätt registry-namnet på instansen så loggen blir tydlig
            if not getattr(instance, "name", None) or instance.name == "okänd":
                instance.name = name
            sources.append(instance)
        except Exception as e:
            print(f"[registry] '{name}': kunde inte ladda {adapter}: {e}")

    return sources


def list_sources(path: Optional[str] = None) -> list[dict]:
    """Returnerar alla entries (även disabled) för CLI-listning."""
    yaml_path = path or DEFAULT_REGISTRY
    if not os.path.exists(yaml_path):
        return []
    with open(yaml_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("sources", []) or []


def append_source(entry: dict, path: Optional[str] = None) -> None:
    """
    Appenderar en ny source till sources.yaml. Används av discover.py --add.
    Nya entries skrivs alltid med enabled: false så användaren måste verifiera
    selektorerna manuellt innan första körningen.
    """
    yaml_path = path or DEFAULT_REGISTRY
    if os.path.exists(yaml_path):
        with open(yaml_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    else:
        data = {"version": 1, "sources": []}

    data.setdefault("sources", [])
    entry.setdefault("enabled", False)
    data["sources"].append(entry)

    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
