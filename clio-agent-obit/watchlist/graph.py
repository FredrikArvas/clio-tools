"""
watchlist/graph.py — Interaktiv relationsgraf för clio-agent-obit

Bygger en vis.js-nätverksgraf som HTML-fil och öppnar den i webbläsaren.
Noder: ego (guld stjärna), bevakningslistan (röd/orange/grå), GEDCOM-kontext (blå).
Kanter: partner (tjock röd), förälder (solid), syskon (streckad), mor/farförälder (prickad).

Körning:
    python watchlist/graph.py --gedcom path/to/file.ged --owner fredrik@arvas.se
    python watchlist/graph.py --gedcom path/to/file.ged --owner fredrik@arvas.se --depth 2
    python watchlist/graph.py --gedcom path/to/file.ged --owner fredrik@arvas.se --no-open
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import webbrowser
from typing import Optional

# ── Importera från import_gedcom ──────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    from gedcom.parser import Parser
    from gedcom.element.individual import IndividualElement
    from gedcom.element.family import FamilyElement
except ImportError:
    print("Fel: python-gedcom är inte installerat.")
    print("Installera med: pip install python-gedcom")
    sys.exit(1)

from watchlist.import_gedcom import (
    _to_utf8_tempfile,
    find_ego,
    get_name,
    extract_birth_year,
    is_likely_alive,
    _get_pointer_map,
    _get_fams,
    _get_famc,
    _family_members,
)

WATCHLISTS_DIR = os.path.join(os.path.dirname(__file__), "..", "watchlists")

# ── Konstantor ────────────────────────────────────────────────────────────────

PRIORITET_COLOR = {
    "viktig":       "#e53935",   # röd
    "normal":       "#fb8c00",   # orange
    "bra_att_veta": "#9e9e9e",   # grå
}

VIS_JS_CDN = "https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"


# ── Läs watchlist-CSV ─────────────────────────────────────────────────────────

def load_watchlist(owner: str) -> list[dict]:
    path = os.path.join(WATCHLISTS_DIR, f"{owner}.csv")
    if not os.path.exists(path):
        print(f"[graph] Ingen watchlist hittad: {path}")
        return []
    entries = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Normalisera kolumnnamn (stöd för både 'fornamn' och 'förnamn' etc.)
            entry = {k.strip(): v.strip() for k, v in row.items()}
            entries.append(entry)
    print(f"[graph] Laddade {len(entries)} poster från watchlist/{owner}.csv")
    return entries


def _watchlist_key(efternamn: str, fornamn: str) -> str:
    """Normaliserad nyckel för matchning (lowercase, utan asterisk-varianter)."""
    fn = fornamn.split("*")[0].strip().lower()
    en = efternamn.strip().lower()
    return f"{en}|{fn}"


# ── Traversera GEDCOM och bygg graf ───────────────────────────────────────────

def build_graph(
    ego: IndividualElement,
    parser: Parser,
    depth: int,
    watchlist_entries: list[dict],
    owner: str,
) -> tuple[list[dict], list[dict]]:
    """
    Returnerar (nodes, edges) för vis.js.
    nodes: [{id, label, color, shape, size, title}]
    edges: [{from, to, label, dashes, width, color}]
    """
    ptr_map = _get_pointer_map(parser)
    ego_ptr = ego.get_pointer()

    # Bygg uppslagstabell för watchlist (nyckel → prioritet)
    wl_lookup: dict[str, str] = {}
    for e in watchlist_entries:
        key = _watchlist_key(e.get("efternamn", ""), e.get("fornamn", ""))
        prio = e.get("prioritet", "normal")
        wl_lookup[key] = prio

    nodes: list[dict] = []
    edges: list[dict] = []
    seen_ptrs: set[str] = set()
    added_edges: set[tuple] = set()

    def _node_id(ptr: str) -> str:
        return ptr.strip("@").replace(" ", "_")

    def _normalize_name(s: str) -> str:
        """Title case men bevarar bindestreck och asterisk-varianter."""
        return " ".join(part.capitalize() for part in s.split())

    def _make_label(ind: IndividualElement) -> str:
        name = get_name(ind)
        if name:
            year = extract_birth_year(ind)
            yr_str = f"\n({year})" if year else ""
            fn = _normalize_name(name[0].split("*")[0].strip())
            en = _normalize_name(name[1])
            return f"{fn} {en}{yr_str}"
        return ind.get_pointer()

    def _make_title(ind: IndividualElement, relation: str = "") -> str:
        name = get_name(ind)
        year = extract_birth_year(ind)
        parts = []
        if name:
            parts.append(f"{name[0]} {name[1]}")
        if year:
            parts.append(f"f. {year}")
        if relation:
            parts.append(f"Relation: {relation}")
        return " | ".join(parts)

    def _get_watchlist_prio(ind: IndividualElement) -> Optional[str]:
        name = get_name(ind)
        if not name:
            return None
        key = _watchlist_key(name[1], name[0])
        return wl_lookup.get(key)

    def add_node(ind: IndividualElement, relation: str = "", is_ego: bool = False):
        ptr = ind.get_pointer()
        if ptr in seen_ptrs:
            return
        seen_ptrs.add(ptr)

        node_id = _node_id(ptr)
        label = _make_label(ind)
        title = _make_title(ind, relation)

        if is_ego:
            node = {
                "id": node_id,
                "label": label,
                "title": title,
                "color": {"background": "#FFD700", "border": "#B8860B"},
                "shape": "star",
                "size": 34,
                "font": {"size": 16, "bold": True, "color": "#222"},
            }
        else:
            prio = _get_watchlist_prio(ind)
            if prio is not None:
                color = PRIORITET_COLOR.get(prio, "#fb8c00")
                node = {
                    "id": node_id,
                    "label": label,
                    "title": f"{title}\nBevakningslistan: {prio}",
                    "color": {"background": color, "border": "#555"},
                    "shape": "ellipse",
                    "size": 22,
                    "font": {"size": 15, "color": "#fff"},
                }
            else:
                # Kontextnod (i GEDCOM-nätverket men inte på watchlist)
                node = {
                    "id": node_id,
                    "label": label,
                    "title": f"{title}\n(kontext, ej på bevakningslistan)",
                    "color": {"background": "#90CAF9", "border": "#1565C0"},
                    "shape": "dot",
                    "size": 14,
                    "font": {"size": 13, "color": "#222"},
                }
        nodes.append(node)

    def add_edge(ptr_a: str, ptr_b: str, label: str, dashes: bool = False,
                 width: int = 1, color: str = "#888888"):
        key = (min(ptr_a, ptr_b), max(ptr_a, ptr_b), label)
        if key in added_edges:
            return
        added_edges.add(key)
        edges.append({
            "from": _node_id(ptr_a),
            "to": _node_id(ptr_b),
            "label": label,
            "dashes": dashes,
            "width": width,
            "color": {"color": color},
            "font": {"size": 13, "align": "middle", "color": "#444"},
            "smooth": {"type": "curvedCW", "roundness": 0.1},
        })

    # Ego-nod
    add_node(ego, is_ego=True)

    parents: list[IndividualElement] = []

    # Djup 1: partner + barn + föräldrar
    for fam_ptr in _get_fams(ego):
        fam = ptr_map.get(fam_ptr)
        if not isinstance(fam, FamilyElement):
            continue
        members = _family_members(fam, ptr_map, exclude_ptr=ego_ptr)
        for spouse in [members["husb"], members["wife"]]:
            if spouse and is_likely_alive(spouse):
                add_node(spouse, relation="Partner")
                add_edge(ego_ptr, spouse.get_pointer(), "partner",
                         width=4, color="#e53935")
        for child in members["children"]:
            if is_likely_alive(child):
                add_node(child, relation="Barn")
                add_edge(ego_ptr, child.get_pointer(), "barn",
                         width=2, color="#2e7d32")

    for fam_ptr in _get_famc(ego):
        fam = ptr_map.get(fam_ptr)
        if not isinstance(fam, FamilyElement):
            continue
        members = _family_members(fam, ptr_map)
        for parent in [members["husb"], members["wife"]]:
            if parent and is_likely_alive(parent):
                add_node(parent, relation="Förälder")
                add_edge(ego_ptr, parent.get_pointer(), "förälder",
                         width=2, color="#555555")
                parents.append(parent)

        if depth >= 2:
            for sib in members["children"]:
                if sib.get_pointer() == ego_ptr:
                    continue
                if is_likely_alive(sib):
                    add_node(sib, relation="Syskon")
                    add_edge(ego_ptr, sib.get_pointer(), "syskon",
                             dashes=True, width=2, color="#7B1FA2")

    if depth >= 2:
        for parent in parents:
            for fam_ptr in _get_famc(parent):
                fam = ptr_map.get(fam_ptr)
                if not isinstance(fam, FamilyElement):
                    continue
                members = _family_members(fam, ptr_map)
                for gp in [members["husb"], members["wife"]]:
                    if gp and is_likely_alive(gp):
                        add_node(gp, relation="Mor/farförälder")
                        add_edge(parent.get_pointer(), gp.get_pointer(),
                                 "mor/farförälder",
                                 dashes=False, width=1, color="#888888")

    if depth >= 3:
        for fam_ptr in _get_famc(ego):
            fam = ptr_map.get(fam_ptr)
            if not isinstance(fam, FamilyElement):
                continue
            siblings = [s for s in _family_members(fam, ptr_map)["children"]
                        if s.get_pointer() != ego_ptr]
            for sib in siblings:
                for sib_fam_ptr in _get_fams(sib):
                    sib_fam = ptr_map.get(sib_fam_ptr)
                    if not isinstance(sib_fam, FamilyElement):
                        continue
                    for child in _family_members(sib_fam, ptr_map)["children"]:
                        if is_likely_alive(child):
                            add_node(child, relation="Syskonbarn")
                            add_edge(sib.get_pointer(), child.get_pointer(),
                                     "syskonbarn", width=1, color="#888888")

        for parent in parents:
            for fam_ptr in _get_famc(parent):
                fam = ptr_map.get(fam_ptr)
                if not isinstance(fam, FamilyElement):
                    continue
                for aunt_uncle in _family_members(fam, ptr_map)["children"]:
                    if aunt_uncle.get_pointer() == parent.get_pointer():
                        continue
                    if is_likely_alive(aunt_uncle):
                        add_node(aunt_uncle, relation="Farbror/moster")
                        add_edge(parent.get_pointer(), aunt_uncle.get_pointer(),
                                 "farbror/moster", dashes=True, width=1, color="#888888")

    # Watchlist-poster som INTE hittades i GEDCOM — isolerade noder
    gedcom_labels = {n["label"].split("\n")[0].lower() for n in nodes}
    for e in watchlist_entries:
        fn = e.get("fornamn", "").split("*")[0].strip()
        en = e.get("efternamn", "").strip()
        full_name = f"{fn} {en}".lower()
        if not any(full_name == gl for gl in gedcom_labels):
            prio = e.get("prioritet", "normal")
            color = PRIORITET_COLOR.get(prio, "#fb8c00")
            year = e.get("fodelsear", "") or ""
            yr_str = f"\n({year})" if year else ""
            node_id = f"wl_{en}_{fn}".replace(" ", "_").replace("@", "")
            # Undvik dubletter
            if any(n["id"] == node_id for n in nodes):
                continue
            nodes.append({
                "id": node_id,
                "label": f"{fn} {en}{yr_str}",
                "title": f"{fn} {en} | {prio} | ej i GEDCOM",
                "color": {"background": color, "border": "#555"},
                "shape": "ellipse",
                "size": 16,
                "font": {"size": 12},
                "borderWidth": 2,
                "borderDashes": [5, 5],
            })

    return nodes, edges


# ── Bygger HTML ───────────────────────────────────────────────────────────────

def build_html(nodes: list[dict], edges: list[dict], owner: str, depth: int) -> str:
    nodes_json = json.dumps(nodes, ensure_ascii=False, indent=2)
    edges_json = json.dumps(edges, ensure_ascii=False, indent=2)

    return f"""<!DOCTYPE html>
<html lang="sv">
<head>
  <meta charset="UTF-8">
  <title>Relationsgraf — {owner}</title>
  <script src="{VIS_JS_CDN}"></script>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: Georgia, serif; background: #f5f0e8; color: #222; }}
    #header {{
      padding: 12px 20px;
      background: #fff;
      border-bottom: 1px solid #ddd;
      display: flex;
      align-items: center;
      gap: 20px;
    }}
    #header h1 {{ font-size: 1.2rem; font-weight: 700; color: #333; }}
    #header span {{ font-size: 0.9rem; color: #666; }}
    #legend {{
      display: flex;
      gap: 16px;
      flex-wrap: wrap;
      margin-left: auto;
      font-size: 0.78rem;
    }}
    .legend-item {{ display: flex; align-items: center; gap: 5px; }}
    .legend-dot {{
      width: 14px; height: 14px; border-radius: 50%;
      border: 1px solid #555; flex-shrink: 0;
    }}
    #network {{ width: 100%; height: calc(100vh - 56px); }}
    #tooltip {{
      position: absolute;
      background: rgba(255,255,255,0.97);
      border: 1px solid #ccc;
      border-radius: 6px;
      padding: 8px 12px;
      font-size: 0.85rem;
      pointer-events: none;
      display: none;
      max-width: 260px;
      color: #222;
      box-shadow: 0 2px 8px rgba(0,0,0,0.15);
    }}
  </style>
</head>
<body>
  <div id="header">
    <h1>Relationsgraf</h1>
    <span>{owner} · djup {depth}</span>
    <div id="legend">
      <div class="legend-item"><div class="legend-dot" style="background:#FFD700"></div>Ego</div>
      <div class="legend-item"><div class="legend-dot" style="background:#e53935"></div>Viktig</div>
      <div class="legend-item"><div class="legend-dot" style="background:#fb8c00"></div>Normal</div>
      <div class="legend-item"><div class="legend-dot" style="background:#9e9e9e"></div>Bra att veta</div>
      <div class="legend-item"><div class="legend-dot" style="background:#90CAF9"></div>Kontext (GEDCOM)</div>
    </div>
  </div>
  <div id="network"></div>
  <div id="tooltip"></div>

  <script>
    const nodes = new vis.DataSet({nodes_json});
    const edges = new vis.DataSet({edges_json});

    const container = document.getElementById("network");
    const options = {{
      nodes: {{
        borderWidth: 1,
        shadow: {{ enabled: true, size: 6, x: 2, y: 2, color: "rgba(0,0,0,0.4)" }},
      }},
      edges: {{
        arrows: {{ to: {{ enabled: false }} }},
        shadow: false,
        font: {{ color: "#444", strokeWidth: 2, strokeColor: "#f5f0e8" }},
      }},
      physics: {{
        enabled: true,
        barnesHut: {{
          gravitationalConstant: -8000,
          centralGravity: 0.3,
          springLength: 150,
          springConstant: 0.04,
          damping: 0.09,
        }},
        stabilization: {{ iterations: 300 }},
      }},
      interaction: {{
        hover: true,
        tooltipDelay: 100,
        navigationButtons: true,
        keyboard: true,
        zoomView: true,
      }},
      layout: {{ improvedLayout: true }},
      background: {{ color: "#1a1a2e" }},
    }};

    const network = new vis.Network(container, {{ nodes, edges }}, options);

    // Visa tooltip vid hover
    const tooltip = document.getElementById("tooltip");
    network.on("hoverNode", function(params) {{
      const node = nodes.get(params.node);
      if (node && node.title) {{
        tooltip.innerHTML = node.title.replace(/\\|/g, "<br>").replace(/\\n/g, "<br>");
        tooltip.style.display = "block";
        tooltip.style.left = (params.event.center.x + 12) + "px";
        tooltip.style.top  = (params.event.center.y - 10) + "px";
      }}
    }});
    network.on("blurNode", function() {{
      tooltip.style.display = "none";
    }});
    network.on("dragStart", function() {{
      tooltip.style.display = "none";
    }});

    // Stabilisering klar
    network.once("stabilizationIterationsDone", function() {{
      network.setOptions({{ physics: {{ enabled: false }} }});
    }});
  </script>
</body>
</html>
"""


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Genererar interaktiv relationsgraf (vis.js HTML) för watchlist-ägaren.",
    )
    p.add_argument("--gedcom", required=True,
                   help="Sökväg till .ged-fil")
    p.add_argument("--owner", required=True,
                   help="Bevakarens e-post (t.ex. fredrik@arvas.se)")
    p.add_argument("--depth", type=int, default=2, choices=[1, 2, 3],
                   help="Relationsdjup 1–3 (standard: 2)")
    p.add_argument("--open", dest="open_browser", action="store_true", default=True,
                   help="Öppna grafen i webbläsaren (standard: ja)")
    p.add_argument("--no-open", dest="open_browser", action="store_false",
                   help="Öppna inte webbläsaren automatiskt")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    # Ladda watchlist
    watchlist_entries = load_watchlist(args.owner)

    # Ladda GEDCOM
    actual_path = _to_utf8_tempfile(args.gedcom)
    is_temp = actual_path != args.gedcom
    parser = Parser()
    parser.parse_file(actual_path)
    if is_temp:
        os.unlink(actual_path)

    ego = find_ego(parser, args.owner)
    if ego is None:
        print("[graph] Ingen ego-person hittad i GEDCOM — grafen visar bara watchlist-poster.")
        nodes = []
        edges = []
        # Lägg till watchlist-poster som isolerade noder utan ego
        for e in watchlist_entries:
            fn = e.get("fornamn", "").split("*")[0].strip()
            en = e.get("efternamn", "").strip()
            prio = e.get("prioritet", "normal")
            color = PRIORITET_COLOR.get(prio, "#fb8c00")
            year = e.get("fodelsear", "") or ""
            yr_str = f"\n({year})" if year else ""
            node_id = f"wl_{en}_{fn}".replace(" ", "_").replace("@", "")
            nodes.append({
                "id": node_id,
                "label": f"{fn} {en}{yr_str}",
                "title": f"{fn} {en} | {prio} | ej i GEDCOM",
                "color": {"background": color, "border": "#555"},
                "shape": "ellipse",
                "size": 16,
                "font": {"size": 12},
            })
    else:
        nodes, edges = build_graph(ego, parser, args.depth, watchlist_entries, args.owner)

    # Generera HTML
    html = build_html(nodes, edges, args.owner, args.depth)

    os.makedirs(WATCHLISTS_DIR, exist_ok=True)
    out_path = os.path.join(WATCHLISTS_DIR, f"graph_{args.owner}.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"[graph] Graf sparad: {out_path}")
    print(f"[graph] {len(nodes)} noder, {len(edges)} kanter (djup {args.depth})")

    if args.open_browser:
        webbrowser.open(f"file:///{os.path.abspath(out_path).replace(os.sep, '/')}")
        print("[graph] Öppnar i webbläsaren...")


if __name__ == "__main__":
    main()
