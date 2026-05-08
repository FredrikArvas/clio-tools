from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.addons.clio_mail_admin.models.clio_mail_admin import _call, _call_raw


class ClioMailPermission(models.Model):
    _name        = "clio.mail.permission"
    _description = "Clio — E-postbehörighet"
    _order       = "email"
    _rec_name    = "email"

    email           = fields.Char(required=True, index=True)
    level           = fields.Selection([
        ("admin",       "Admin"),
        ("write",       "Write"),
        ("coded",       "Keyword"),
        ("whitelisted", "Whitelisted"),
        ("denied",      "Denied"),
    ], required=True, default="whitelisted")
    accounts_raw    = fields.Char(string="Konton",
        help="Kommaseparerade account_key, eller * för alla")
    kodord_read_raw = fields.Char(string="Kodord (läs)")
    kodord_rw_raw   = fields.Char(string="Kodord (läs+skriv)")
    synced_at       = fields.Datetime(string="Senast synkad", readonly=True)
    sync_error      = fields.Char(string="Synkfel", readonly=True)

    def _push_to_service(self):
        for rec in self:
            accounts  = [a.strip() for a in (rec.accounts_raw or "").split(",")
                         if a.strip() and a.strip() != "*"]
            read_only = [k.strip() for k in (rec.kodord_read_raw or "").split(",") if k.strip()]
            rw        = [k.strip() for k in (rec.kodord_rw_raw   or "").split(",") if k.strip()]
            try:
                _call(self.env, "/mail/permissions/update", {
                    "email":        rec.email,
                    "level":        rec.level,
                    "accounts":     accounts,
                    "kodord_scope": read_only + rw,
                    "kodord_write": rw,
                })
                rec.with_context(skip_push=True).write({
                    "synced_at":  fields.Datetime.now(),
                    "sync_error": False,
                })
            except UserError as e:
                rec.with_context(skip_push=True).write({"sync_error": str(e)})

    def write(self, vals):
        res = super().write(vals)
        if not self.env.context.get("skip_push"):
            self._push_to_service()
        return res

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        if not self.env.context.get("skip_push"):
            recs._push_to_service()
        return recs

    @api.model
    def action_sync_from_service(self):
        result   = _call_raw(self.env, "/mail/permissions/json")
        existing = {r.email: r for r in self.search([])}

        service_emails = set()
        for u in result.get("users", []):
            email     = u["email"]
            rw_set    = set(u.get("kodord_write", []))
            scope     = u.get("kodord_scope", [])
            read_only = [k for k in scope if k not in rw_set]
            vals = {
                "email":           email,
                "level":           u.get("level", "whitelisted"),
                "accounts_raw":    ",".join(u.get("accounts", [])) or "*",
                "kodord_read_raw": ",".join(read_only),
                "kodord_rw_raw":   ",".join(u.get("kodord_write", [])),
                "synced_at":       fields.Datetime.now(),
                "sync_error":      False,
            }
            service_emails.add(email)
            if email in existing:
                existing[email].with_context(skip_push=True).write(vals)
            else:
                self.with_context(skip_push=True).create(vals)

        # Ta bort rader som inte längre finns i service
        to_delete = [r for e, r in existing.items() if e not in service_emails]
        if to_delete:
            self.browse([r.id for r in to_delete]).unlink()

        return {"type": "ir.actions.client", "tag": "reload"}
