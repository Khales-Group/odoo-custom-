from odoo import models, fields, api, _
import base64
import pickle
import numpy as np
import requests

class AiAgent(models.Model):
    _inherit = 'ai.agent'   # <- important: inherit existing ai.agent
    _description = 'AI Agent (extended for RAG)'

    status = fields.Selection([
        ('idle','Idle'),
        ('processing','Processing'),
        ('ready','Ready'),
        ('error','Error')
    ], default='idle')

    chunk_ids = fields.One2many(
        comodel_name='ai.document.chunk',
        inverse_name='agent_id',
        string='Document Chunks'
    )

    knowledge_source_ids = fields.One2many(
        comodel_name='ai.agent.source',
        inverse_name='agent_id',
        string="Knowledge Sources"
    )

    partner_id = fields.Many2one('res.partner', string="Partner")

    def _process_query(self, query, history=None, attachment_ids=None):
        # Status feedback to the chatter
        self._send_ai_status_log(_("Step 1/2: Analyzing sources and attached documents..."))

        file_context = ""
        if attachment_ids:
            attachments = self.env['ir.attachment'].browse(attachment_ids)
            for attach in attachments:
                # use index_content if available, otherwise decode datas
                text = attach.index_content or ""
                if not text and attach.datas:
                    try:
                        data = base64.b64decode(attach.datas)
                        text = data.decode('utf-8', errors='ignore')
                    except Exception:
                        text = ""
                if text:
                    file_context += f"\n[File: {attach.name}]\n{text}\n"

        enhanced_query = f"Context from uploaded files:\n{file_context}\n\nQuestion: {query}" if file_context else query

        self._send_ai_status_log(_("Step 2/2: Generating the final answer..."))
        return self._answer_with_rag(enhanced_query)

    def _send_ai_status_log(self, message):
        for record in self:
            # post a notification in chatter so user sees progress
            record.message_post(body=message, message_type='notification')

    def action_reprocess_sources(self):
        for agent in self:
            agent.status = 'processing'
            # remove existing chunks for this agent
            agent.chunk_ids.unlink()

            attachments = self.env['ir.attachment'].search([
                ('res_model', '=', 'ai.agent'),
                ('res_id', '=', agent.id)
            ])

            full_text = ""
            for att in attachments:
                full_text += agent._extract_text(att) or ""

            chunks = agent._chunk_text(full_text)

            for chunk in chunks:
                embedding = agent._generate_embedding(chunk)
                self.env['ai.document.chunk'].create({
                    'agent_id': agent.id,
                    'content': chunk,
                    'embedding': pickle.dumps(embedding),
                })

            agent.status = 'ready'
        return True

    def _extract_text(self, attachment):
        if not attachment:
            return ""
        # Prefer indexed text if available (Odoo may have indexed it)
        if attachment.index_content:
            return attachment.index_content

        # Fallback to raw datas for plain text
        if attachment.datas and attachment.mimetype == 'text/plain':
            try:
                return base64.b64decode(attachment.datas).decode('utf-8', errors='ignore')
            except Exception:
                return ""
        # Extend here: pdfplumber, python-docx, openpyxl, pytesseract for images, etc.
        return ""

    def _chunk_text(self, text, size=800):
        if not text:
            return []
        words = text.split()
        return [
            " ".join(words[i:i+size])
            for i in range(0, len(words), size)
        ]

    def _generate_embedding(self, text):
        api_key = self.env['ir.config_parameter'].sudo().get_param('gemini.api.key')
        if not api_key or not text:
            return []

        url = f"https://generativelanguage.googleapis.com/v1beta/models/embedding-001:embedContent?key={api_key}"
        try:
            response = requests.post(url, json={
                "content": {
                    "parts": [{"text": text}]
                }
            }, timeout=30)
            response.raise_for_status()
            data = response.json()
            # adapt to the actual Gemini response structure you get in your env
            values = data.get('embedding', {}).get('values') or data.get('data', [{}])[0].get('embedding') or data
            return values
        except Exception as e:
            _logger = self.env['ir.logging']
            # log to odoo logger
            self.env.cr.commit()
            self.message_post(body=f"Embedding error: {e}", message_type='notification')
            return []

    def _answer_with_rag(self, question):
        # generate embedding for question
        question_emb = self._generate_embedding(question) or []
        if not question_emb:
            self.message_post(body="Failed to compute question embedding.", message_type='notification')
            return

        scored = []
        for chunk in self.chunk_ids:
            try:
                stored_emb = pickle.loads(chunk.embedding) if chunk.embedding else []
                # compute similarity if both are present
                if stored_emb and question_emb:
                    sim = float(np.dot(question_emb, stored_emb) / (np.linalg.norm(question_emb) * np.linalg.norm(stored_emb)))
                else:
                    sim = 0.0
                scored.append((sim, chunk.content))
            except Exception:
                continue

        scored.sort(key=lambda x: x[0], reverse=True)
        top_chunks = [c[1] for c in scored[:5] if c[0] > 0.0]

        context = "\n\n".join(top_chunks) if top_chunks else ""
        prompt = f"Use ONLY the context below to answer:\n\n{context}\n\nQuestion:\n{question}"

        answer = self._ask_gemini(prompt) or "Sorry, I couldn't produce an answer."

        # post as chatter message on the agent record (safe)
        self.message_post(body=answer, message_type='comment')
        return answer

    def _ask_gemini(self, prompt):
        api_key = self.env['ir.config_parameter'].sudo().get_param('gemini.api.key')
        if not api_key:
            return "Gemini API key not configured."
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={api_key}"
        try:
            response = requests.post(url, json={
                "contents": [{
                    "parts": [{"text": prompt}]
                }]
            }, timeout=60)
            response.raise_for_status()
            data = response.json()
            # adapt based on actual Gemini response shape
            return data.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', '')
        except Exception as e:
            return f"Gemini call failed: {e}"
