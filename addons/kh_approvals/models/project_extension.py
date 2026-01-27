from odoo import models, fields, api
from odoo.exceptions import UserError

class ProjectProject(models.Model):
    _inherit = 'project.project'

    contractor_email = fields.Char(string="Contractor Email")

    is_manager = fields.Boolean(compute='_compute_is_manager')

    @api.depends('user_id')
    def _compute_is_manager(self):
        for rec in self:
            rec.is_manager = (rec.user_id == self.env.user)

    # === BOQ FIELDS ===
    boq_plan_ids = fields.One2many('kh.project.boq.plan', 'project_id', string="Master BOQ Plan")
    boq_state = fields.Selection([('draft', 'Draft'), ('published', 'Published')], default='draft', string="BOQ Status")
    
    # Link to see received bids directly in the project
    boq_submission_ids = fields.One2many('kh.boq.submission', 'project_id', string="Received Bids")
    boq_submission_count = fields.Integer(compute='_compute_boq_submission_count', string="Bids Count")
    
    # Helper to easily copy the link
    boq_public_url = fields.Char(compute='_compute_boq_public_url', string="Public BOQ Link")

    @api.depends('boq_submission_ids')
    def _compute_boq_submission_count(self):
        for rec in self:
            rec.boq_submission_count = len(rec.boq_submission_ids)

    def _compute_boq_public_url(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        for rec in self:
            rec.boq_public_url = f"{base_url}/boq/fill/{rec.id}"

    def action_publish_boq(self):
        self.boq_state = 'published'
        
    def action_reset_boq(self):
        self.boq_state = 'draft'

    def action_load_default_boq_template(self):
        self.ensure_one()
        if self.boq_plan_ids: return

        # DATA FROM EXCEL (15 SECTIONS)
        default_items = [
            ('(1) PRELIMINARIES', 'Site Preparation, Temp Fencing, Site Sign Board', 'Unit'),
            ('(1) PRELIMINARIES', 'Site Administration Facilities & Engg Supervision', 'Unit'),
            ('(1) PRELIMINARIES', 'Arrangement Of Temporary Electricity & Water', 'Unit'),
            ('(1) PRELIMINARIES', 'Others (Please specify)', 'Unit'),
            ('(2) SITE WORKS', 'Excavation works up to required level', 'Unit'),
            ('(2) SITE WORKS', 'Leveling & Compaction', 'Unit'),
            ('(2) SITE WORKS', 'Backfilling works', 'Unit'),
            ('(2) SITE WORKS', 'Disposal of debris or others', 'Unit'),
            ('(2) SITE WORKS', 'Anti-Termite treatment (20 year guarantee)', 'Unit'),
            ('(2) SITE WORKS', 'Others (Please specify)', 'Unit'),
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
            ('(5) BLOCK WORKS', '20cm insulated / Thermal blocks', 'Unit'),
            ('(5) BLOCK WORKS', '20cm Hollow Blocks', 'Unit'),
            ('(5) BLOCK WORKS', '10cm Hollow Blocks', 'Unit'),
            ('(5) BLOCK WORKS', '10cm Solid Blocks', 'Unit'),
            ('(5) BLOCK WORKS', '20cm Parapet', 'Unit'),
            ('(6) PLASTER WORKS', 'INTERNAL: 20 mm thk smooth plaster for walls', 'Unit'),
            ('(6) PLASTER WORKS', 'EXTERNAL: Smooth plaster for elevation', 'Unit'),
            ('(6) PLASTER WORKS', 'EXTERNAL: Smooth plaster for compound wall', 'Unit'),
            ('(6) PLASTER WORKS', 'CEILING: Smooth plaster for roof (If Required)', 'Unit'),
            ('(6) PLASTER WORKS', 'Others (Please specify)', 'Unit'),
            ('(7) RCC WATER PROOFING', 'FOUNDATION: Bitumen membrane', 'Unit'),
            ('(7) RCC WATER PROOFING', 'Bitumen membrane sheets (if required)', 'Unit'),
            ('(7) RCC WATER PROOFING', '1 inch thick protection board (if required)', 'Unit'),
            ('(7) RCC WATER PROOFING', 'Others (Please specify)', 'Unit'),
            ('(8) WET AREA PROOFING', 'Wet area waterproofing work (10 Year Warranty)', 'Unit'),
            ('(8) WET AREA PROOFING', 'ROOF: Combo roof waterproofing (25 Year Warranty)', 'Unit'),
            ('(8) WET AREA PROOFING', 'Others (Please specify)', 'Unit'),
            ('(9) PAINTING WORKS', 'INTERNAL: PVA Primer + Stucco + Fenomastic Washable', 'Unit'),
            ('(9) PAINTING WORKS', 'EXTERNAL: Acrylic Primer + Texo Compound + Jotunshield', 'Unit'),
            ('(9) PAINTING WORKS', 'Others (Please specify)', 'Unit'),
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
            ('(11) ELECTRICAL', 'Shop Drawings & As Built Drawings', 'Unit'),
            ('(11) ELECTRICAL', 'Meter Cabinets, MDB, DBs (DEWA Standards)', 'Unit'),
            ('(11) ELECTRICAL', 'Cables For Power Distribution', 'Unit'),
            ('(11) ELECTRICAL', 'Conduits, Wires, Low Current, Fire Alarm', 'Unit'),
            ('(11) ELECTRICAL', 'Earth Pits (Grounding)', 'Unit'),
            ('(11) ELECTRICAL', 'Light Fittings, Sockets, Isolators', 'Unit'),
            ('(11) ELECTRICAL', 'Testing & Commissioning (Electrical)', 'Unit'),
            ('(11) ELECTRICAL', 'Electrical Manholes', 'Unit'),
            ('(11) ELECTRICAL', 'Power Point For Car Charger', 'Unit'),
            ('(12) MECHANICAL', 'AC System: Carrier Saudi Arabia DX ducted', 'Unit'),
            ('(12) MECHANICAL', 'Grill, Diffuser, Refrigerant pipes', 'Unit'),
            ('(12) MECHANICAL', 'Inline Exhaust fan', 'Unit'),
            ('(13) CCTV', 'CCTV System (Supply, Install, Program, Test)', 'Unit'),
            ('(13) CCTV', 'IP Security Cameras (6 Cameras)', 'Unit'),
            ('(13) CCTV', '25mm UPVC conduit with CAT6', 'Unit'),
            ('(13) CCTV', 'Network video recorder', 'Unit'),
            ('(13) CCTV', 'Calling bell screen with speaker', 'Unit'),
            ('(13) CCTV', 'Intercom system panel at main entrance', 'Unit'),
            ('(14) COMPOUND WALLS', 'Compound wall with Decoration', 'Unit'),
            ('(14) COMPOUND WALLS', 'Compound wall (750/RM)', 'Unit'),
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

        lines = [(0, 0, {'section_name': s, 'item_description': n, 'uom_id': u, 'quantity': 0.0}) for s, n, u in default_items]
        self.write({'boq_plan_ids': lines})

    def write(self, vals):
        # قائمة بالحقول التي نريد حمايتها
        protected_fields = ['contractor_email', 'partner_id', 'date_start']

        for project in self:
            # التحقق: هل المستخدم الحالي هو المدير؟
            is_manager = project.user_id == self.env.user
            
            # التحقق: هل المستخدم يحاول تعديل أحد الحقول المحمية؟
            # نقوم بفحص ما إذا كان أي من الحقول المحمية موجوداً في القيم المرسلة للتعديل (vals)
            trying_to_edit_protected = any(field in vals for field in protected_fields)

            # إذا لم يكن المدير + ويحاول تعديل حقول محمية => اظهر خطأ
            if not is_manager and trying_to_edit_protected:
                raise UserError("عذراً! لا يمكنك تعديل هذه البيانات لأنك لست مدير المشروع.")

        return super(ProjectProject, self).write(vals)

class ProjectBoqPlan(models.Model):
    _name = 'kh.project.boq.plan'
    _description = 'Internal BOQ Items'
    _order = 'id'

    project_id = fields.Many2one('project.project')
    section_name = fields.Char(required=True)
    item_description = fields.Char(required=True)
    quantity = fields.Float(string="Planned Qty", required=True)
    uom_id = fields.Char(string="Unit", default="Unit")