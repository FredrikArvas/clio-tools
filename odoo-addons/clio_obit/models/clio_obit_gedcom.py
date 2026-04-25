"""
clio_obit_gedcom.py
Lagrar uppladdade GEDCOM-filer och hanterar import till res.partner.
"""

from __future__ import annotations

import base64
import importlib
import io
import logging
import os
import sys
import tempfile
from contextlib import redirect_stdout

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

CLIO_TOOLS = "/mnt/clio-tools"


def _ensure_paths():
    for p in [
        f"{CLIO_TOOLS}/clio-agent-obit",
        f"{CLIO_TOOLS}/clio-partnerdb",
        str(CLIO_TOOLS),
    ]:
        if p not in sys.path:
            sys.path.insert(0, p)


class ClioObitGedcom(models.Model):
    _name        = "clio.obit.gedcom"
    _description = "Clio Obit — GEDCOM-fil"
    _order       = "uploaded_at desc"
    _rec_name    = "name"

    name = fields.Char(
        string   = "Namn",
        required = True,
        help     = "Valfritt visningsnamn, t.ex. 'Arvas-trädet 2026'.",
    )
    filename = fields.Char(string="Filnamn")
    file_data = fields.Binary(
        string     = "GEDCOM-fil",
        required   = True,
        attachment = True,
    )
    file_size = fields.Integer(string="Filstorlek (bytes)", readonly=True)
    uploaded_at = fields.Datetime(
        string   = "Uppladdad",
        default  = fields.Datetime.now,
        readonly = True,
    )
    individual_count = fields.Integer(
        string  = "Individer i trädet",
        readonly = True,
        help    = "Antal levande individer hittade vid senaste analys.",
    )
    last_import_at = fields.Datetime(string="Senaste import", readonly=True)
    last_import_log = fields.Text(string="Importlogg", readonly=True)

    # ── Hooks ─────────────────────────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("file_data"):
                raw = base64.b64decode(vals["file_data"])
                vals["file_size"] = len(raw)
        records = super().create(vals_list)
        for rec in records:
            rec._analyse_gedcom()
        return records

    def write(self, vals):
        if vals.get("file_data"):
            raw = base64.b64decode(vals["file_data"])
            vals["file_size"] = len(raw)
        result = super().write(vals)
        if vals.get("file_data"):
            self._analyse_gedcom()
        return result

    # ── Analyse ───────────────────────────────────────────────────────────────

    def _analyse_gedcom(self):
        """Räknar levande individer i filen och uppdaterar individual_count."""
        self.ensure_one()
        if not self.file_data:
            return
        try:
            _ensure_paths()
            # Import sker här för att undvika modulnivåfel om python-gedcom saknas
            from import_gedcom import _to_utf8_tempfile, _collect_full
            from gedcom.parser import Parser

            raw = base64.b64decode(self.file_data)
            with tempfile.NamedTemporaryFile(suffix=".ged", delete=False) as f:
                f.write(raw)
                tmp = f.name
            try:
                utf8_path, is_temp = _to_utf8_tempfile(tmp)
                parser = Parser()
                parser.parse_file(utf8_path, strict=False)
                if is_temp:
                    os.unlink(utf8_path)
                count = len(_collect_full(parser))
                self.individual_count = count
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
        except Exception as exc:
            _logger.warning("Kunde inte analysera GEDCOM-fil: %s", exc)

    # ── Åtgärder ──────────────────────────────────────────────────────────────

    def action_open_import_wizard(self):
        """Öppnar importguiden för den här filen."""
        self.ensure_one()
        return {
            "type":    "ir.actions.act_window",
            "name":    f"Importera: {self.name}",
            "res_model": "clio.obit.gedcom.wizard",
            "view_mode": "form",
            "target":  "new",
            "context": {"default_gedcom_id": self.id},
        }


class ClioObitGedcomWizard(models.TransientModel):
    _name        = "clio.obit.gedcom.wizard"
    _description = "Clio Obit — GEDCOM-importguide"

    gedcom_id = fields.Many2one(
        comodel_name = "clio.obit.gedcom",
        string       = "GEDCOM-fil",
        required     = True,
    )
    owner_email = fields.Char(
        string      = "Notifiera e-post",
        required    = True,
        default     = lambda self: self.env.user.email or "",
        help        = "E-post som får notiser för alla importerade bevakningar.",
    )
    ego_name = fields.Char(
        string      = "Ego (startperson)",
        help        = "Namn på startpersonen i trädet. Lämna tomt = helträd.",
    )
    depth = fields.Selection(
        selection = [("1", "Djup 1 — make/maka, barn, föräldrar"),
                     ("2", "Djup 2 — + syskon, far/morföräldrar  [standard]"),
                     ("3", "Djup 3 — + syskonbarn, fastrar/morbröder")],
        string    = "Djup",
        default   = "2",
        required  = True,
    )
    full_import = fields.Boolean(
        string = "Helträd (ignorera djup och ego)",
        help   = "Importerar alla levande individer i trädet.",
    )
    dry_run = fields.Boolean(
        string  = "Torrkörning",
        default = False,
        help    = "Simulerar utan att skapa/ändra partners i Odoo.",
    )
    state = fields.Selection(
        selection = [("draft", "Klar att köra"), ("done", "Klar")],
        default   = "draft",
    )
    result_text = fields.Text(string="Resultat", readonly=True)

    # ── Import ────────────────────────────────────────────────────────────────

    def action_run_import(self):
        self.ensure_one()
        _logger.info("GEDCOM-import START wizard=%s fil=%s", self.id, self.gedcom_id.name)

        if not self.gedcom_id.file_data:
            raise UserError("Den valda filen har ingen data.")

        _ensure_paths()
        _logger.info("GEDCOM-import: sys.path OK, laddar importscript")

        try:
            from import_gedcom_to_odoo import run_import
        except ImportError as exc:
            raise UserError(
                f"Kunde inte importera importscriptet: {exc}\n"
                f"Kontrollera att /mnt/clio-tools är monterat och att python-gedcom är installerat."
            )

        _logger.info("GEDCOM-import: importscript laddat, dekoderar fil (%d bytes base64)", len(self.gedcom_id.file_data))
        raw = base64.b64decode(self.gedcom_id.file_data)
        if raw.startswith(b"\xef\xbb\xbf"):
            _logger.info("GEDCOM-import: UTF-8 BOM strippad")
            raw = raw[3:]

        _logger.info("GEDCOM-import: rå filstorlek %d bytes", len(raw))
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".ged", delete=False) as f:
                f.write(raw)
                tmp_path = f.name
            _logger.info("GEDCOM-import: tempfil skapad %s", tmp_path)

            buf = io.StringIO()
            fake_stdin = io.StringIO("0\n")
            _logger.info("GEDCOM-import: anropar run_import (ego=%r full=%s dry=%s)",
                         self.ego_name, self.full_import, self.dry_run)
            with redirect_stdout(buf):
                old_stdin = sys.stdin
                sys.stdin = fake_stdin
                try:
                    run_import(
                        gedcom_path  = tmp_path,
                        owner_email  = self.owner_email,
                        ego_name     = self.ego_name or None,
                        depth        = int(self.depth),
                        full         = self.full_import,
                        dry_run      = self.dry_run,
                    )
                finally:
                    sys.stdin = old_stdin
            output = buf.getvalue()
            _logger.info("GEDCOM-import: run_import klar, output %d tecken", len(output))
        except Exception as exc:
            output = f"FEL: {exc}"
            _logger.exception("GEDCOM-import misslyckades")
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

        self.gedcom_id.write({
            "last_import_at":  fields.Datetime.now(),
            "last_import_log": output,
        })
        self.write({"state": "done", "result_text": output})

        # Håll dialogen öppen med resultatet
        return {
            "type":      "ir.actions.act_window",
            "name":      "Importresultat",
            "res_model": "clio.obit.gedcom.wizard",
            "res_id":    self.id,
            "view_mode": "form",
            "target":    "new",
        }
