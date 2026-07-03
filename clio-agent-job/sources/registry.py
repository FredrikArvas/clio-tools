"""
registry.py
Laddar källinstanser — primärt från Odoo (clio.media.source),
med fallback till sources.yaml om Odoo ej är tillgängligt.
"""

from __future__ import annotations

import importlib
import logging
import sys
from pathlib import Path
from typing import Optional

_logger = logging.getLogger(__name__)

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

_ADAPTER_MAP = {
    "rss": "source_rss.RssSource",
}


def _instantiate(name: str, adapter_str: str, url: str) -> Optional[BaseSource]:
    try:
        module_name, class_name = adapter_str.rsplit(".", 1)
        module = importlib.import_module(module_name)
        cls = getattr(module, class_name)
        return cls(url=url, name=name)
    except Exception as e:
        print(f"[VARNING] Kunde inte ladda källa '{name}': {e}")
        return None


def _load_from_odoo(env) -> Optional[list[BaseSource]]:
    """Läser aktiva källor från clio.media.source i Odoo."""
    try:
        rows = env["clio.media.source"].search_read(
            [("enabled", "=", True)],
            ["name", "url", "source_type"],
            order="sequence asc",
        )
        sources = []
        for r in rows:
            adapter_str = _ADAPTER_MAP.get(r["source_type"])
            if not adapter_str:
                _logger.warning("Okänd source_type '%s' för '%s'", r["source_type"], r["name"])
                continue
            inst = _instantiate(r["name"], adapter_str, r["url"])
            if inst:
                sources.append(inst)
        _logger.info("registry: %d källor laddade från Odoo", len(sources))
        return sources
    except Exception as exc:
        _logger.warning("registry: kunde inte läsa källor från Odoo: %s", exc)
        return None


def _load_from_yaml(yaml_path: Optional[Path] = None) -> list[BaseSource]:
    """Fallback: läser sources.yaml."""
    if not _HAS_YAML:
        raise ImportError("PyYAML saknas — kör: pip install pyyaml")
    path = yaml_path or _SOURCES_YAML
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    sources: list[BaseSource] = []
    for entry in data.get("sources", []):
        if not entry.get("enabled", False):
            continue
        adapter_str: str = entry["adapter"]
        config: dict = entry.get("config", {})
        try:
            module_name, class_name = adapter_str.rsplit(".", 1)
            module = importlib.import_module(module_name)
            cls = getattr(module, class_name)
            sources.append(cls(**config))
        except Exception as e:
            print(f"[VARNING] Kunde inte ladda källa '{entry.get('name', adapter_str)}': {e}")
    _logger.info("registry: %d källor laddade från YAML (fallback)", len(sources))
    return sources


def load_sources(
    yaml_path: Optional[Path] = None,
    env=None,
) -> list[BaseSource]:
    """
    Returnerar aktiva källinstanser.
    Försöker Odoo först (om env är satt), faller tillbaka på sources.yaml.
    """
    if env is not None:
        result = _load_from_odoo(env)
        if result is not None:
            return result
    return _load_from_yaml(yaml_path)
