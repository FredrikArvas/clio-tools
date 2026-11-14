"""
patch_source_ref.py — Lägger till source_ref på uap.encounter

Kör på servern:
  python3 patch_source_ref.py
"""
import re

# --- 1. Modell ---
MODEL_PATH = '/home/clioadmin/clio-tools/odoo-addons/clio_uap/models/uap_encounter.py'
with open(MODEL_PATH, encoding='utf-8') as f:
    src = f.read()

OLD = (
    '    # --- Ursprung ---\n'
    '    database_id = fields.Many2one(\n'
    '        comodel_name="uap.database",\n'
    '        string="Source Database",\n'
    '        index=True,\n'
    '        ondelete="restrict",\n'
    '        help="Databas som detta encounter importerades från",\n'
    '    )'
)
NEW = (
    '    # --- Ursprung ---\n'
    '    database_id = fields.Many2one(\n'
    '        comodel_name="uap.database",\n'
    '        string="Source Database",\n'
    '        index=True,\n'
    '        ondelete="restrict",\n'
    '        help="Databas som detta encounter importerades från",\n'
    '    )\n'
    '    source_ref = fields.Char(\n'
    '        string="Source Reference",\n'
    '        index=True,\n'
    '        help="Extern nyckel från ursprungsdatabasen, t.ex. \'GEIPAN:2023-12-51504\'",\n'
    '    )'
)
assert OLD in src, "Hittade inte database_id-blocket"
src = src.replace(OLD, NEW, 1)
with open(MODEL_PATH, 'w', encoding='utf-8') as f:
    f.write(src)
print("uap_encounter.py: source_ref tillagd OK")

# --- 2. Vy: lägg till source_ref i Technical-fliken och i sökvy ---
VIEW_PATH = '/home/clioadmin/clio-tools/odoo-addons/clio_uap/views/uap_encounter_views.xml'
with open(VIEW_PATH, encoding='utf-8') as f:
    vsrc = f.read()

# 2a. Form: lägg till source_ref i Technical-fliken
OLD_TECH = (
    '            <page string="Technical">\n'
    '              <group>\n'
    '                <field name="neo4j_node_id"/>\n'
    '              </group>\n'
    '            </page>'
)
NEW_TECH = (
    '            <page string="Technical">\n'
    '              <group>\n'
    '                <field name="neo4j_node_id"/>\n'
    '                <field name="source_ref"/>\n'
    '              </group>\n'
    '            </page>'
)
assert OLD_TECH in vsrc, "Hittade inte Technical-fliken"
vsrc = vsrc.replace(OLD_TECH, NEW_TECH, 1)

# 2b. Sökvy: lägg till source_ref som sökbart fält
OLD_SEARCH = '        <field name="database_id"/>'
NEW_SEARCH = (
    '        <field name="database_id"/>\n'
    '        <field name="source_ref"/>'
)
# Bara första förekomsten (kan redan vara patchad med series_id efter)
assert OLD_SEARCH in vsrc, "Hittade inte database_id i sökvyn"
vsrc = vsrc.replace(OLD_SEARCH, NEW_SEARCH, 1)

with open(VIEW_PATH, 'w', encoding='utf-8') as f:
    f.write(vsrc)
print("uap_encounter_views.xml: source_ref i Technical + sökvy OK")
print()
print("Starta om Odoo för att aktivera fältet:")
print("  sudo systemctl restart odoo")
