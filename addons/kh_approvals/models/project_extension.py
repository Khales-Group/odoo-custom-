from odoo import models, fields, api
from odoo.exceptions import UserError

class ProjectProject(models.Model):
    _inherit = 'project.project'

    # --- Existing Fields ---
    contractor_email = fields.Char(string="Contractor Email")
    is_manager = fields.Boolean(compute='_compute_is_manager')

    # --- NEW BOQ Fields ---
    boq_submission_count = fields.Integer(compute='_compute_boq_submission_count')

    # --- BOQ Logic: Count Submissions ---
    def _compute_boq_submission_count(self):
        for project in self:
            # Counts how many submissions differ for this project ID
            project.boq_submission_count = self.env['kh.boq.submission'].search_count([
                ('project_id', '=', project.id)
            ])

    # --- BOQ Logic: Smart Button Action ---
    def action_view_boq_submissions(self):
        self.ensure_one()
        return {
            'name': 'BOQ Submissions',
            'type': 'ir.actions.act_window',
            'res_model': 'kh.boq.submission',
            'view_mode': 'tree,form',
            'domain': [('project_id', '=', self.id)],
            'context': {'default_project_id': self.id},
        }

    # --- BOQ Logic: Website Helper ---
    def _get_boq_sections_for_website(self):
        self.ensure_one()
        # This returns the structure for the website form.
        # Ideally, fetch this from real product categories.
        return [
            {
                'id': 1, 'name': 'PRELIMINARIES / MOBILIZATION', 'items': [
                    {'product_id': 1, 'name': 'Site Preparation', 'description': 'Temp fencing, signage', 'qty': 1, 'uom_name': 'Unit', 'qty_available': 0, 'price': 0.0},
                    {'product_id': 2, 'name': 'Site Admin Facilities', 'description': 'Offices & Supervision', 'qty': 1, 'uom_name': 'Unit', 'qty_available': 0, 'price': 0.0},
                ]
            },
            {
                'id': 2, 'name': 'SITE WORKS / EARTH WORKS', 'items': [
                    {'product_id': 3, 'name': 'Excavation', 'description': 'Up to required level', 'qty': 500, 'uom_name': 'm3', 'qty_available': 0, 'price': 0.0},
                ]
            },
            # You can add the rest of the 15 sections here
        ]

    # --- Existing Security Logic ---
    @api.depends('user_id')
    def _compute_is_manager(self):
        for rec in self:
            rec.is_manager = (rec.user_id == self.env.user)
    def action_view_boq_submissions(self):
        self.ensure_one()
        return {
            'name': 'BOQ Submissions',
            'type': 'ir.actions.act_window',
            'res_model': 'kh.boq.submission',
            'view_mode': 'list,form',  # Changed 'tree' to 'list'
            'views': [(False, 'list'), (False, 'form')], # Changed 'tree' to 'list'
            'domain': [('project_id', '=', self.id)],
            'context': {'default_project_id': self.id},
        }
    def action_open_boq_website(self):
        """ Opens the public BOQ website link for this project in a new tab. """
        self.ensure_one()
        # Get the base URL (e.g., https://your-odoo.com)
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        # Create the link: /boq/fill/PROJECT_ID
        boq_url = f"{base_url}/boq/fill/{self.id}"
        
        return {
            'type': 'ir.actions.act_url',
            'url': boq_url,
            'target': 'new', # Opens in a new tab
        }
    def _get_boq_sections_for_website(self):
        """
        Returns the hardcoded BOQ structure for the website.
        In a real scenario, you would fetch these from 'product.product' records.
        """
        self.ensure_one()
        
        # Helper to create item structure
        def item(name, desc=""):
            # Try to find existing product or return dummy ID for display
            return {
                'product_id': 0, # In real logic, search for product.id
                'name': name,
                'description': desc,
                'qty': 1.0,
                'uom_name': 'Unit',
                'qty_available': 0,
                'price': 0.0
            }

        return [
            {
                'id': 1, 
                'name': '(1) PRELIMINARIES / MOBILIZATION', 
                'items': [
                    item('Site Preparation', 'Temporary Fencing with consultant logo, site sign board, etc.'),
                    item('Site Administration Facilities', 'Engineering Supervision, etc.'),
                    item('Arrangement Of Temporary Electricity & Water', ''),
                    item('Others (Please specify)', 'Included'),
                ]
            },
            {
                'id': 2, 
                'name': '(2) SITE WORKS / EARTH WORKS', 
                'items': [
                    item('Excavation works', 'Up to required level'),
                    item('Leveling & Compaction', ''),
                    item('Backfilling works', ''),
                    item('Disposal of debris', 'Or others if any'),
                    item('Anti-Termite treatment', '20 year guarantee, under all PCC, slabs on grade, and building perimeter'),
                    item('Others (Please specify)', ''),
                ]
            },
            {
                'id': 3, 
                'name': '(3) SUB STRUCTURE CONCRETE WORKS', 
                'items': [
                    item('Polythene Sheet 1000 Gauge', ''),
                    item('P.C.C Under Footings', ''),
                    item('P.C.C under solid blocks', ''),
                    item('Applying Bitumen paint', '2 coats'),
                    item('Footings', ''),
                    item('Neck Columns', ''),
                    item('Solid block', ''),
                    item('Retaining Wall', 'IF ANY'),
                    item('Shoring', 'IF ANY'),
                    item('Tie Beam', ''),
                    item('Grade slab rcc with mesh', ''),
                    item('Others (Please specify)', ''),
                ]
            },
            {
                'id': 4, 
                'name': '(4) SUPER STRUCTURE CONCRETE WORKS', 
                'items': [
                    item('R.C.C columns', ''),
                    item('R.C.C columns Ground Floor', ''),
                    item('R.C.C For Lintels & Sills', ''),
                    item('R.C.C Slab & Beams', ''),
                    item('R.C.C Slab (Roof Slab)', ''),
                    item('Parapet', 'If Concrete'),
                    item('R.C.C Coping Beam', ''),
                    item('Elevator Shaft', 'N/A'),
                    item('Concrete Work For Services', 'AC & RW'),
                    item('RCC Stairs', ''),
                ]
            },
            {
                'id': 5, 
                'name': '(5) BLOCK WORKS', 
                'items': [
                    item('20cm insulated / Thermal blocks', ''),
                    item('20cm Hollow Blocks', ''),
                    item('10cm Hollow Blocks', ''),
                    item('10cm Solid Blocks', ''),
                    item('20cm Parapet', ''),
                ]
            },
            {
                'id': 6, 
                'name': '(6) PLASTER WORKS', 
                'items': [
                    item('INTERNAL: 20 mm thk smooth plaster', 'For walls'),
                    item('EXTERNAL: Smooth plaster for elevation', ''),
                    item('EXTERNAL: Smooth plaster for compound wall', ''),
                    item('CEILING: Smooth plaster for roof', 'If required'),
                    item('Others (Please specify)', ''),
                ]
            },
            {
                'id': 7, 
                'name': '(7) RCC WATER PROOFING WORKS', 
                'items': [
                    item('Bitumen membrane', 'Foundation Water Proofing'),
                    item('Bitumen membrane sheets', 'If required'),
                    item('1" thick protection board', 'If required'),
                    item('Others (Please specify)', ''),
                ]
            },
            {
                'id': 8, 
                'name': '(8) WET AREA WATER PROOFING', 
                'items': [
                    item('Wet area waterproofing work', '10 Year Warranty'),
                    item('Combo roof waterproofing', '25 Year Warranty'),
                    item('Others (Please specify)', ''),
                ]
            },
            {
                'id': 9, 
                'name': '(9) PAINTING WORKS', 
                'items': [
                    item('INTERNAL PAINT', '1x PVA Primer, 1x Stucco, 2x Fenomastic Washable Paint'),
                    item('EXTERNAL PAINT', '1x Acrylic Primer, 1x Texo Compound, 1x Jotunshield Topcoat'),
                    item('Others (Please specify)', ''),
                ]
            },
            {
                'id': 10, 
                'name': '(10) PLUMBING WORKS', 
                'items': [
                    item('Water Meters', 'Supply & Install (DEWA Standards)'),
                    item('PPR and PPX Pipes', 'Internal & External'),
                    item('Water Tanks', 'Ground and Overhead with fittings'),
                    item('Transfer & Booster Pumps', '1 duty + 1 standby, with control panels'),
                    item('Water Heater System', 'Electric and Solar'),
                    item('Water Cooling System', ''),
                    item('Testing & Commissioning', 'Complete Water Supply System'),
                    item('Drainage: UPVC Pipe Connections', 'Internal & External'),
                    item('Sanitary Wares', 'Installation as per specs'),
                    item('Gully Traps and Manhole Covers', ''),
                    item('Vent & Rainwater Pipes', ''),
                    item('Septic Tank & soak away', 'If required'),
                ]
            },
            {
                'id': 11, 
                'name': '(11) ELECTRICAL & ETISALAT WORKS', 
                'items': [
                    item('Shop Drawings & Approvals', 'DEWA Documentation'),
                    item('MDB and DBs', 'Supply & Install (DEWA Standards)'),
                    item('Cables', 'For Power Distribution'),
                    item('Conduits, Wires & Accessories', 'Electrical, Low Current, Fire Alarm'),
                    item('Earth Pits', 'Grounding System'),
                    item('Light Fittings & Sockets', 'Installation'),
                    item('Testing & Commissioning', 'Entire Electrical System'),
                    item('Electrical Manholes', ''),
                    item('Power Point', 'Car Charger'),
                ]
            },
            {
                'id': 12, 
                'name': '(12) MECHANICAL WORKS', 
                'items': [
                    item('Carrier Saudi Arabia DX ducted AC', 'Supply and installation'),
                    item('Grill, Diffuser, Refrigerant pipes', 'All accessories'),
                    item('Inline Exhaust fan', ''),
                ]
            },
            {
                'id': 13, 
                'name': '(13) CCTV WORKS', 
                'items': [
                    item('CCTV System', 'Supply, install, program, test (DPS/SIRA compliant)'),
                    item('IP Security Cameras', 'Weather proof, wall/pole mounted (6 Cameras)'),
                    item('25mm UPVC conduit', 'With CAT6 cable to POE switch'),
                    item('Network video recorder', ''),
                    item('Calling bell screen', 'With speaker'),
                    item('Audio Intercom Panel', 'At main entrance'),
                ]
            },
            {
                'id': 14, 
                'name': '(14) COMPOUND WALLS', 
                'items': [
                    item('Compound wall with Decoration', ''),
                    item('Compound wall (750/RM)', ''),
                    item('Others', ''),
                ]
            },
            {
                'id': 15, 
                'name': '(15) PROVISIONAL SUM', 
                'items': [
                    item('Gypsum Ceiling: Bathrooms', 'MR Gypsum'),
                    item('Gypsum Ceiling: Kitchen', 'FR Gypsum'),
                    item('Gypsum Ceiling: Rest of Villa', 'FR Gypsum'),
                    item('Floor Tiles: Dry Areas', '60x60 Basic Concrete Saint Grey'),
                    item('Floor Tiles: Wet Areas', '60x60 Attractive White'),
                    item('Wall Tiles: Wet Areas', 'Up to Ceiling'),
                    item('Interlock & External Works', '150mm to 250mm Kerbstone'),
                    item('Carpentry: Doors D1, D2, D3, D4', 'Oak Wood'),
                    item('Kitchen Cabinet', 'Granite Top, Sinks, Mixer'),
                    item('Aluminium Windows & Doors', 'W1-W9, D1, D5'),
                    item('Sanitary Ware (RAK)', 'WCs, Wash Basins'),
                    item('Automatic Electrical Main Gate', ''),
                    item('Spiral ladder', 'With Safety Lock'),
                ]
            }
        ]