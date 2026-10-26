# -*- coding: utf-8 -*-
from odoo import api, fields, models

# Tags and source the website puts on calculator leads (xmlid, name). Matched
# by name so existing records are reused - both models have a unique name.
CALC_TAGS = [
    ("tag_calculator_v2", "Calculator v2"),
    ("tag_design_request", "Design request"),
    ("tag_budget_review", "Budget review"),
]
CALC_SOURCES = [
    ("utm_source_website_calculator_v2", "Website Calculator v2"),
]


class CrmLead(models.Model):
    _inherit = "crm.lead"

    # Filled by the website's villa cost calculator over XML-RPC. Names and
    # types must match what the website sends exactly: it skips any field
    # whose type doesn't match, so these stay plain Char/Float/Integer/
    # Boolean/Text (raw code strings, no Selection/Many2one), all optional,
    # no defaults, no onchange. Some may already exist as manual fields -
    # see hooks.py.
    x_calc_reference = fields.Char(string="Calculator reference", index=True, copy=False)
    x_calc_version = fields.Char(string="Calculator version")
    x_calc_source = fields.Char(string="Calculator source")
    x_calc_request_type = fields.Char(string="Calculator request type")
    x_calc_country = fields.Char(string="Calculator country")
    x_calc_city = fields.Char(string="Calculator city")
    x_calc_market_mode = fields.Char(string="Calculator market mode")
    x_calc_market_confidence = fields.Char(string="Calculator market confidence")
    x_calc_pricing_source_date = fields.Char(string="Calculator pricing source date")
    x_calc_anchor_date = fields.Char(string="Calculator price anchor date")
    x_calc_input_mode = fields.Char(string="Calculator input mode")
    x_calc_built_area_sqm = fields.Float(string="Calculator built area (m²)")
    x_calc_budget = fields.Float(string="Calculator budget")
    x_calc_currency = fields.Char(string="Calculator currency")
    x_calc_finish_level = fields.Char(string="Calculator finish level")
    x_calc_result_low = fields.Float(string="Calculator result low")
    x_calc_result_expected = fields.Float(string="Calculator result expected")
    x_calc_result_high = fields.Float(string="Calculator result high")
    x_calc_area_conservative_sqm = fields.Float(string="Calculator conservative area (m²)")
    x_calc_area_reference_sqm = fields.Float(string="Calculator reference area (m²)")
    x_calc_area_max_sqm = fields.Float(string="Calculator maximum area (m²)")
    x_calc_special_items = fields.Char(string="Calculator special items")
    x_calc_land_status = fields.Char(string="Calculator land status")
    x_calc_start_timing = fields.Char(string="Calculator start timing")
    x_calc_has_plan_or_quote = fields.Boolean(string="Calculator has plan or contractor quote")
    x_calc_review_goal = fields.Char(string="Calculator review goal")
    x_calc_preferred_contact = fields.Char(string="Calculator preferred contact")
    x_calc_contact_consent = fields.Boolean(string="Calculator contact consent")
    x_calc_marketing_consent = fields.Boolean(string="Calculator marketing consent")
    x_calc_lead_score = fields.Integer(string="Calculator lead score")
    x_calc_floors = fields.Char(string="Calculator floors")
    x_calc_family_plan = fields.Text(string="Calculator family plan")
    x_calc_lang = fields.Char(string="Calculator language")
    x_calc_created_at = fields.Char(string="Calculator created at")

    @api.model
    def _kh_calc_ensure_records(self):
        # Called once, at install (noupdate data file): reuse a tag/source
        # with the same name (any capitalisation) or create it, and give it
        # this module's xmlid so it can be referenced.
        data_list = []
        for model, entries in (("crm.tag", CALC_TAGS), ("utm.source", CALC_SOURCES)):
            Model = self.env[model]
            for xmlid, name in entries:
                record = Model.search([("name", "=ilike", name)], limit=1) or Model.create({"name": name})
                data_list.append({"xml_id": f"kh_crm_calculator.{xmlid}", "record": record, "noupdate": True})
        self.env["ir.model.data"]._update_xmlids(data_list)
