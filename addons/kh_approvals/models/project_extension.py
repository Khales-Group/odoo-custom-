from odoo import models, fields, api

class ProjectProject(models.Model):
    _inherit = 'project.project'

    # --- Existing Fields ---
    contractor_email = fields.Char(string="Contractor Email")
    is_manager = fields.Boolean(compute='_compute_is_manager')
    boq_submission_count = fields.Integer(compute='_compute_boq_submission_count')

    # --- NEW: BOQ PLANNING FIELDS ---
    # هذا الجدول يعبئه الموظف الداخلي بالكميات
    boq_plan_ids = fields.One2many('kh.project.boq.plan', 'project_id', string="Master BOQ Plan")
    
    # حالة الـ BOQ
    boq_state = fields.Selection([
        ('draft', 'Draft (Editing Quantities)'),
        ('published', 'Published (Ready for Pricing)')
    ], default='draft', string="BOQ Status", tracking=True)

    # --- ACTIONS ---
    def action_publish_boq(self):
        """ يمنع التعديل وينشر الرابط """
        self.boq_state = 'published'

    def action_reset_boq(self):
        """ إعادة للوضع المسودة للتعديل """
        self.boq_state = 'draft'

    def action_load_default_boq_template(self):
        """ زر لتحميل جميع بنود الإكسل الـ 15 قسم وتفريغ الكميات """
        self.ensure_one()
        if self.boq_plan_ids:
            return # لا تفعل شيئاً إذا كان هناك بنود بالفعل لكي لا نكررها
        
        # القائمة الكاملة بناءً على ملف الإكسل
        default_items = [
            # (1) PRELIMINARIES/MOBILIZATION
            ('(1) PRELIMINARIES', 'Site Preparation, Temp Fencing, Site Sign Board', 'Unit'),
            ('(1) PRELIMINARIES', 'Site Administration Facilities & Engg Supervision', 'Unit'),
            ('(1) PRELIMINARIES', 'Arrangement Of Temporary Electricity & Water', 'Unit'),
            ('(1) PRELIMINARIES', 'Others (Please specify)', 'Unit'),

            # (2) SITE WORKS / EARTH WORKS
            ('(2) SITE WORKS', 'Excavation works up to required level', 'Unit'),
            ('(2) SITE WORKS', 'Leveling & Compaction', 'Unit'),
            ('(2) SITE WORKS', 'Backfilling works', 'Unit'),
            ('(2) SITE WORKS', 'Disposal of debris or others', 'Unit'),
            ('(2) SITE WORKS', 'Anti-Termite treatment (20 year guarantee)', 'Unit'),
            ('(2) SITE WORKS', 'Others (Please specify)', 'Unit'),

            # (3) SUB STRUCTURE CONCRETE WORKS
            ('(3) SUB STRUCTURE', 'Polythene Sheet 1000 Gauge', 'Unit'),
            ('(3) SUB STRUCTURE', 'P.C.C Under Footings', 'Unit'),
            ('(3) SUB STRUCTURE', 'P.C.C under solid blocks', 'Unit'),
            ('(3) SUB STRUCTURE', 'Applying Bitumen paint (2 coats)', 'Unit'),
            ('(3) SUB STRUCTURE', 'Footings', 'Unit'),
            ('(3) SUB STRUCTURE', 'Neck Columns', 'Unit'),
            ('(3) SUB STRUCTURE', 'Solid block', 'Unit'),
            ('(3) SUB STRUCTURE', 'Retaining Wall (IF ANY)', 'Unit'),
            ('(3) SUB STRUCTURE', 'Shoring (IF ANY)', 'Unit'),
            ('(3) SUB STRUCTURE', 'Tie Beam', 'Unit'),
            ('(3) SUB STRUCTURE', 'Grade slab rcc with mesh', 'Unit'),
            ('(3) SUB STRUCTURE', 'Others (Please specify)', 'Unit'),

            # (4) SUPER STRUCTURE CONCRETE WORKS
            ('(4) SUPER STRUCTURE', 'R.C.C columns', 'Unit'),
            ('(4) SUPER STRUCTURE', 'R.C.C columns Ground Floor', 'Unit'),
            ('(4) SUPER STRUCTURE', 'R.C.C For Lintels & Sills', 'Unit'),
            ('(4) SUPER STRUCTURE', 'R.C.C Slab & Beams', 'Unit'),
            ('(4) SUPER STRUCTURE', 'R.C.C Slab (Roof Slab)', 'Unit'),
            ('(4) SUPER STRUCTURE', 'Parapet (If Concrete)', 'Unit'),
            ('(4) SUPER STRUCTURE', 'R.C.C Coping Beam', 'Unit'),
            ('(4) SUPER STRUCTURE', 'Elevator Shaft', 'Unit'),
            ('(4) SUPER STRUCTURE', 'Concrete Work For Services (AC & RW)', 'Unit'),
            ('(4) SUPER STRUCTURE', 'RCC Stairs', 'Unit'),

            # (5) BLOCK WORKS
            ('(5) BLOCK WORKS', '20cm insulated / Thermal blocks', 'Unit'),
            ('(5) BLOCK WORKS', '20cm Hollow Blocks', 'Unit'),
            ('(5) BLOCK WORKS', '10cm Hollow Blocks', 'Unit'),
            ('(5) BLOCK WORKS', '10cm Solid Blocks', 'Unit'),
            ('(5) BLOCK WORKS', '20cm Parapet', 'Unit'),

            # (6) PLASTER WORKS
            ('(6) PLASTER WORKS', 'INTERNAL: 20 mm thk smooth plaster for walls', 'Unit'),
            ('(6) PLASTER WORKS', 'EXTERNAL: Smooth plaster for elevation', 'Unit'),
            ('(6) PLASTER WORKS', 'EXTERNAL: Smooth plaster for compound wall', 'Unit'),
            ('(6) PLASTER WORKS', 'CEILING: Smooth plaster for roof (If Required)', 'Unit'),
            ('(6) PLASTER WORKS', 'Others (Please specify)', 'Unit'),

            # (7) RCC WATER PROOFING WORKS
            ('(7) RCC WATER PROOFING', 'FOUNDATION: Bitumen membrane', 'Unit'),
            ('(7) RCC WATER PROOFING', 'Bitumen membrane sheets (if required)', 'Unit'),
            ('(7) RCC WATER PROOFING', '1 inch thick protection board (if required)', 'Unit'),
            ('(7) RCC WATER PROOFING', 'Others (Please specify)', 'Unit'),

            # (8) WET AREA WATER PROOFING WORKS
            ('(8) WET AREA PROOFING', 'Wet area waterproofing work (10 Year Warranty)', 'Unit'),
            ('(8) WET AREA PROOFING', 'ROOF: Combo roof waterproofing (25 Year Warranty)', 'Unit'),
            ('(8) WET AREA PROOFING', 'Others (Please specify)', 'Unit'),

            # (9) PAINTING WORKS
            ('(9) PAINTING WORKS', 'INTERNAL: PVA Primer + Stucco + Fenomastic Washable', 'Unit'),
            ('(9) PAINTING WORKS', 'EXTERNAL: Acrylic Primer + Texo Compound + Jotunshield', 'Unit'),
            ('(9) PAINTING WORKS', 'Others (Please specify)', 'Unit'),

            # (10) PLUMBING WORKS
            ('(10) PLUMBING', 'Water Supply: Meters (DEWA Standards)', 'Unit'),
            ('(10) PLUMBING', 'PPR and PPX Pipes (Internal & External)', 'Unit'),
            ('(10) PLUMBING', 'Ground and Overhead Water Tanks', 'Unit'),
            ('(10) PLUMBING', 'Transfer & Booster Pumps (1 duty + 1 standby)', 'Unit'),
            ('(10) PLUMBING', 'Electric and Solar Water Heater System', 'Unit'),
            ('(10) PLUMBING', 'Water Cooling System', 'Unit'),
            ('(10) PLUMBING', 'Testing & Commissioning (Water Supply)', 'Unit'),
            ('(10) PLUMBING', 'Drainage: Internal & External UPVC Pipe', 'Unit'),
            ('(10) PLUMBING', 'Sanitary Wares Installation', 'Unit'),
            ('(10) PLUMBING', 'Gully Traps and Manhole Covers', 'Unit'),
            ('(10) PLUMBING', 'Vent Pipes & Rainwater Pipes', 'Unit'),
            ('(10) PLUMBING', 'Septic Tank & soak away (if required)', 'Unit'),
            ('(10) PLUMBING', 'Submission of Shop Drawings', 'Unit'),
            ('(10) PLUMBING', 'Testing & Commissioning (Drainage)', 'Unit'),

            # (11) ELECTRICAL & ETISALAT WORKS
            ('(11) ELECTRICAL', 'Shop Drawings & As Built Drawings', 'Unit'),
            ('(11) ELECTRICAL', 'Meter Cabinets, MDB, DBs (DEWA Standards)', 'Unit'),
            ('(11) ELECTRICAL', 'Cables For Power Distribution', 'Unit'),
            ('(11) ELECTRICAL', 'Conduits, Wires, Low Current, Fire Alarm', 'Unit'),
            ('(11) ELECTRICAL', 'Earth Pits (Grounding)', 'Unit'),
            ('(11) ELECTRICAL', 'Light Fittings, Sockets, Isolators', 'Unit'),
            ('(11) ELECTRICAL', 'Testing & Commissioning (Electrical)', 'Unit'),
            ('(11) ELECTRICAL', 'Electrical Manholes', 'Unit'),
            ('(11) ELECTRICAL', 'Power Point For Car Charger', 'Unit'),

            # (12) MECHANICAL WORKS
            ('(12) MECHANICAL', 'AC System: Carrier Saudi Arabia DX ducted', 'Unit'),
            ('(12) MECHANICAL', 'Grill, Diffuser, Refrigerant pipes', 'Unit'),
            ('(12) MECHANICAL', 'Inline Exhaust fan', 'Unit'),

            # (13) CCTV WORKS
            ('(13) CCTV', 'CCTV System (Supply, Install, Program, Test)', 'Unit'),
            ('(13) CCTV', 'IP Security Cameras (6 Cameras)', 'Unit'),
            ('(13) CCTV', '25mm UPVC conduit with CAT6', 'Unit'),
            ('(13) CCTV', 'Network video recorder', 'Unit'),
            ('(13) CCTV', 'Calling bell screen with speaker', 'Unit'),
            ('(13) CCTV', 'Intercom system panel at main entrance', 'Unit'),

            # (14) COMPOUND WALLS
            ('(14) COMPOUND WALLS', 'Compound wall with Decoration', 'Unit'),
            ('(14) COMPOUND WALLS', 'Compound wall (750/RM)', 'Unit'),

            # (15) PROVISIONAL SUM
            ('(15) PROVISIONAL', 'Gypsum Ceiling: Bath Rooms & WCs (MR)', 'Unit'),
            ('(15) PROVISIONAL', 'Gypsum Ceiling: Kitchen (FR)', 'Unit'),
            ('(15) PROVISIONAL', 'Gypsum Ceiling: Rest of Villa (FR)', 'Unit'),
            ('(15) PROVISIONAL', 'Floor Tiles: Dry Areas (60x60 Basic Concrete)', 'm2'),
            ('(15) PROVISIONAL', 'Skirting For All Area', 'Unit'),
            ('(15) PROVISIONAL', 'Floor Tiles: Wet Areas (60x60 Attractive White)', 'Unit'),
            ('(15) PROVISIONAL', 'Wall Tiles: Wet Areas Upto Ceiling', 'Unit'),
            ('(15) PROVISIONAL', 'Threshold (Marble/Granite)', 'Unit'),
            ('(15) PROVISIONAL', 'Interlock & Kerbstone (Inside & Outside)', 'Unit'),
            ('(15) PROVISIONAL', 'Carpentry: Doors (D1, D2, D3, D4)', 'Unit'),
            ('(15) PROVISIONAL', 'Kitchen Cabinet (Granite Top, Sinks)', 'Unit'),
            ('(15) PROVISIONAL', 'Pantry & Dressing Cabinets', 'Unit'),
            ('(15) PROVISIONAL', 'Aluminium Works (W1-W9, D1, D5)', 'Unit'),
            ('(15) PROVISIONAL', 'Sanitary Ware (RAK): WCs, Basins', 'Unit'),
            ('(15) PROVISIONAL', 'Bath Room Mirrors', 'Unit'),
            ('(15) PROVISIONAL', 'Toilet Cabinets', 'Unit'),
            ('(15) PROVISIONAL', 'Light Fittings Supply', 'Unit'),
            ('(15) PROVISIONAL', 'Boundary Wall Lights', 'Unit'),
            ('(15) PROVISIONAL', 'Handrail On Terrace', 'Unit'),
            ('(15) PROVISIONAL', 'Car parking Shed', 'Unit'),
            ('(15) PROVISIONAL', 'Automatic Electrical Main Gate', 'Unit'),
            ('(15) PROVISIONAL', 'Small Gate with Electrical Lock', 'Unit'),
            ('(15) PROVISIONAL', 'Spiral ladder With Safety Lock', 'Unit'),
            ('(15) PROVISIONAL', 'Roof Tiles / Shower Partition / Pergolas', 'Unit'),
            ('(15) PROVISIONAL', 'Planters With Water Proofing', 'Unit'),
            ('(15) PROVISIONAL', 'Exterior Tiles for Elevation', 'Unit'),
            ('(15) PROVISIONAL', 'Interior Work Additional', 'Unit'),
        ]
        
        lines = []
        for section, name, uom in default_items:
            lines.append((0, 0, {
                'section_name': section,
                'item_description': name,
                'uom_id': uom,
                'quantity': 0.0, # الكمية صفر ليبدأ الموظف بتعبئتها
            }))
        
        self.write({'boq_plan_ids': lines})
    # --- Computes & Helpers ---
    def _compute_boq_submission_count(self):
        for project in self:
            project.boq_submission_count = self.env['kh.boq.submission'].search_count([
                ('project_id', '=', project.id)
            ])

    def action_view_boq_submissions(self):
        self.ensure_one()
        return {
            'name': 'BOQ Submissions',
            'type': 'ir.actions.act_window',
            'res_model': 'kh.boq.submission',
            'view_mode': 'list,form',
            'domain': [('project_id', '=', self.id)],
            'context': {'default_project_id': self.id},
        }

    def action_open_boq_website(self):
        self.ensure_one()
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        return {
            'type': 'ir.actions.act_url',
            'url': f"{base_url}/boq/fill/{self.id}",
            'target': 'new',
        }
    
    @api.depends('user_id')
    def _compute_is_manager(self):
        for rec in self:
            rec.is_manager = (rec.user_id == self.env.user)


# --- NEW MODEL: INTERNAL BOQ PLAN ---
class ProjectBoqPlan(models.Model):
    _name = 'kh.project.boq.plan'
    _description = 'Internal BOQ Items'
    _order = 'id asc'

    project_id = fields.Many2one('project.project', ondelete='cascade')
    section_name = fields.Char(string="Section", required=True)
    item_description = fields.Char(string="Description", required=True)
    quantity = fields.Float(string="Planned Qty", required=True)
    uom_id = fields.Char(string="Unit", default="Unit")