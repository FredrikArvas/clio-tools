# -*- coding: utf-8 -*-
{
    'name': 'AIAB — Installationsprofil',
    'version': '19.0.4.1.0',
    'summary': 'Meta-modul: installerar alla moduler för AIAB-databasen',
    'author': 'Arvas International AB',
    'license': 'LGPL-3',
    'depends': [
        'clio_cockpit',          # Dashboard och startvy
        'clio_discuss',          # Diskussioner och meddelandefunktioner
        'clio_event_log',        # Händelselogg
        'clio_graph',            # Relationsgrafer mellan kontakter
        'clio_interview',        # Intervjuer och anställningsprocess
        'clio_job',              # Rekrytering och tjänster
        'clio_mail_admin',       # E-postadministration
        'clio_mail_permissions', # Behörighetsstyrning för e-post
        'clio_ncc_project',      # NCC-projektkort i Odoo
        'clio_theme',            # AIAB-färgtema
        'clio_vigil',            # Bevakning och uppföljning
        'l10n_se_partner',       # Svenska adressformat och fält
        'l10n_se_ssn',           # Personnummer på kontakter
        'partner_autocomplete',  # Företagssökning via VAT/org.nr (Odoo standard)
        'partner_firstname',     # Förnamn och efternamn som separata fält (OCA)
        'partner_multi_relation', # Relationstyper mellan kontakter (OCA)
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'auto_install': False,
}
