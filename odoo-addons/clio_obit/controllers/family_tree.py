"""
family_tree.py
HTTP-controller för interaktiv familjeträdsgraf (vis.js).

Routes:
  /clio/family-tree/<int:partner_id>        — HTML-sida med grafen
  /clio/api/family-tree/<int:partner_id>    — JSON-data (noder + kanter)
"""

import json
from odoo import http
from odoo.http import request


class FamilyTreeController(http.Controller):

    @http.route("/clio/api/family-tree/<int:partner_id>",
                auth="user", type="http", methods=["GET"])
    def api_family_tree(self, partner_id, depth=2, **_kw):
        depth = min(int(depth), 3)
        nodes, edges = _build_graph(request.env, partner_id, depth)
        return request.make_response(
            json.dumps({"nodes": nodes, "edges": edges}),
            headers=[("Content-Type", "application/json")],
        )

    @http.route("/clio/family-tree/<int:partner_id>",
                auth="user", type="http", methods=["GET"])
    def family_tree(self, partner_id, **_kw):
        partner = request.env["res.partner"].browse(partner_id)
        if not partner.exists():
            return request.not_found()
        return request.render(
            "clio_obit.family_tree_page",
            {"partner": partner, "partner_id": partner_id},
        )


# ── Grafbyggare ───────────────────────────────────────────────────────────────

def _build_graph(env, root_id: int, depth: int):
    """
    BFS från root_id via clio.partner.link upp till `depth` steg.
    Returnerar (nodes, edges) för vis.js.
    """
    visited_partners = set()
    visited_edges    = set()
    nodes = []
    edges = []

    queue = [(root_id, 0)]
    visited_partners.add(root_id)

    while queue:
        pid, level = queue.pop(0)

        partner = env["res.partner"].browse(pid)
        if not partner.exists():
            continue

        birth = partner.clio_obit_birth_year or 0
        death = partner.clio_obit_death_year or 0
        label = partner.name or "?"
        if birth:
            label += f"\n{birth}"
            if death:
                label += f"–{death}"

        nodes.append({
            "id":    pid,
            "label": label,
            "title": _tooltip(partner),
            "group": _group(partner, pid == root_id),
            "font":  {"multi": "html"},
        })

        if level >= depth:
            continue

        links = env["clio.partner.link"].search([("from_partner_id", "=", pid)])
        for lnk in links:
            to_id = lnk.to_partner_id.id
            edge_key = (pid, to_id, lnk.relation_label)
            if edge_key in visited_edges:
                continue
            visited_edges.add(edge_key)
            edges.append({
                "from":   pid,
                "to":     to_id,
                "label":  lnk.relation_label or "",
                "arrows": "to",
                "color":  _edge_color(lnk.relation_label),
            })
            if to_id not in visited_partners:
                visited_partners.add(to_id)
                queue.append((to_id, level + 1))

    return nodes, edges


def _tooltip(p) -> str:
    parts = [f"<b>{p.name}</b>"]
    if p.clio_obit_birth_name and p.clio_obit_birth_name != p.name:
        parts.append(f"Född: {p.clio_obit_birth_name}")
    if p.clio_obit_birth_year:
        parts.append(f"f. {p.clio_obit_birth_year}")
    if p.clio_obit_death_year:
        parts.append(f"d. {p.clio_obit_death_year}")
    if p.city:
        parts.append(p.city)
    return "<br>".join(parts)


def _group(p, is_root: bool) -> str:
    if is_root:
        return "root"
    if p.clio_obit_death_year:
        return "deceased"
    return "living"


def _edge_color(label: str) -> str:
    return {
        "make/maka": "#e74c3c",
        "barn":      "#2ecc71",
        "förälder":  "#3498db",
        "syskon":    "#9b59b6",
    }.get(label or "", "#95a5a6")
