"""
portal.py
Portal-controller för clio_job — låter kandidater se och redigera sin profil
samt se matchningshistoriken via Odoos webbportal.

Routes:
  GET  /my/clio-job            → Profil (läsläge)
  GET  /my/clio-job/edit       → Profil (redigeringsläge)
  POST /my/clio-job/edit       → Spara redigerad profil
  GET  /my/clio-job/matches    → Matchningshistorik
"""

from odoo import http
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal


class ClioJobPortal(CustomerPortal):

    def _prepare_portal_layout_values(self):
        """Lägger till Clio Job-länk i portal-sidofältet."""
        values = super()._prepare_portal_layout_values()
        partner = request.env.user.partner_id
        profile = request.env["clio.job.profile"].sudo().search(
            [("partner_id", "=", partner.id)], limit=1
        )
        values["clio_job_profile"] = profile
        values["clio_job_match_count"] = len(profile.match_ids) if profile else 0
        return values

    # ------------------------------------------------------------------
    # Profil — läsläge
    # ------------------------------------------------------------------
    @http.route("/my/clio-job", type="http", auth="user", website=True)
    def clio_job_profile(self, **kw):
        partner = request.env.user.partner_id
        profile = request.env["clio.job.profile"].search(
            [("partner_id", "=", partner.id)], limit=1
        )
        values = self._prepare_portal_layout_values()
        values["profile"] = profile
        values["page_name"] = "clio_job"
        return request.render("clio_job.portal_profile", values)

    # ------------------------------------------------------------------
    # Profil — redigeringsläge (GET)
    # ------------------------------------------------------------------
    @http.route("/my/clio-job/edit", type="http", auth="user", website=True)
    def clio_job_profile_edit(self, **kw):
        partner = request.env.user.partner_id
        profile = request.env["clio.job.profile"].search(
            [("partner_id", "=", partner.id)], limit=1
        )
        values = self._prepare_portal_layout_values()
        values["profile"] = profile
        values["page_name"] = "clio_job_edit"
        values["error"] = kw.get("error", "")
        values["success"] = kw.get("success", "")
        return request.render("clio_job.portal_profile_edit", values)

    # ------------------------------------------------------------------
    # Profil — spara (POST)
    # ------------------------------------------------------------------
    @http.route("/my/clio-job/edit", type="http", auth="user", website=True,
                methods=["POST"], csrf=True)
    def clio_job_profile_save(self, **post):
        partner = request.env.user.partner_id
        profile = request.env["clio.job.profile"].search(
            [("partner_id", "=", partner.id)], limit=1
        )
        if not profile:
            return request.redirect("/my/clio-job?error=no_profile")

        profile.sudo().write({
            "report_email":    post.get("report_email", "").strip() or False,
            "role":            post.get("role", "").strip() or False,
            "seniority":       post.get("seniority", "").strip() or False,
            "geography":       post.get("geography", "").strip() or False,
            "hybrid_ok":       bool(post.get("hybrid_ok")),
            "background":      post.get("background", "").strip() or False,
            "education":       post.get("education", "").strip() or False,
            "target_roles":    post.get("target_roles", "").strip() or False,
            "signal_keywords": post.get("signal_keywords", "").strip() or False,
        })
        return request.redirect("/my/clio-job?success=saved")

    # ------------------------------------------------------------------
    # Matchningshistorik
    # ------------------------------------------------------------------
    @http.route("/my/clio-job/matches", type="http", auth="user", website=True)
    def clio_job_matches(self, **kw):
        partner = request.env.user.partner_id
        profile = request.env["clio.job.profile"].search(
            [("partner_id", "=", partner.id)], limit=1
        )
        matches = profile.match_ids if profile else []
        values = self._prepare_portal_layout_values()
        values["profile"] = profile
        values["matches"] = matches
        values["page_name"] = "clio_job_matches"
        return request.render("clio_job.portal_matches", values)
