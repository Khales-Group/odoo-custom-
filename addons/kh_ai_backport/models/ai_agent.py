from odoo import models, fields, api, _
import base64
import pickle
import numpy as np
import requests


class AiAgent(models.Model):
    _name = 'ai.agent'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'AI Agent'

    name = fields.Char(string="Agent Name", required=True)

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
        # ميزة الـ Feedback: إشعار المستخدم بالمراحل
        self._send_ai_status_log(_("Step 1/2: Analyzing sources and attached documents..."))

        file_context = ""
        if attachment_ids:
            attachments = self.env['ir.attachment'].browse(attachment_ids)
            for attach in attachments:
                # أودو 19.0 يقوم بالفهرسة تلقائياً للملفات المدعومة
                text = attach.index_content or ""
                if text:
                    file_context += f"\n[File: {attach.name}]\n{text}\n"

        # دمج محتوى الملفات لتمكين الـ AI من "رؤيتها"
        enhanced_query = f"Context from uploaded files:\n{file_context}\n\nQuestion: {query}" if file_context else query

        self._send_ai_status_log(_("Step 2/2: Generating the final answer..."))
        # Call internal RAG method instead of super() since we are now standalone
        return self._answer_with_rag(enhanced_query)

    def _send_ai_status_log(self, message):
        for record in self:
            record.message_post(body=message, message_type='notification')

    def action_reprocess_sources(self):
        self.status = 'processing'

        self.chunk_ids.unlink()

        attachments = self.env['ir.attachment'].search([
            ('res_model', '=', 'ai.agent'),
            ('res_id', '=', self.id)
        ])

        full_text = ""
        for att in attachments:
            full_text += self._extract_text(att)

        chunks = self._chunk_text(full_text)

        for chunk in chunks:
            embedding = self._generate_embedding(chunk)

            self.env['ai.document.chunk'].create({
                'agent_id': self.id,
                'content': chunk,
                'embedding': pickle.dumps(embedding),
            })

        self.status = 'ready'
        return True

    def _extract_text(self, attachment):
        data = base64.b64decode(attachment.datas)

        if attachment.mimetype == 'text/plain':
            return data.decode('utf-8', errors='ignore')

        # Add PDF / DOCX logic here
        return ""

    def _chunk_text(self, text, size=800):
        words = text.split()
        return [
            " ".join(words[i:i+size])
            for i in range(0, len(words), size)
        ]

    def _generate_embedding(self, text):
        api_key = self.env['ir.config_parameter'].sudo().get_param('gemini.api.key')

        url = f"https://generativelanguage.googleapis.com/v1beta/models/embedding-001:embedContent?key={api_key}"

        response = requests.post(url, json={
            "content": {
                "parts": [{"text": text}]
            }
        })

        return response.json()['embedding']['values']

    def _answer_with_rag(self, question):
        question_embedding = self._generate_embedding(question)

        scored = []

        for chunk in self.chunk_ids:
            emb = pickle.loads(chunk.embedding)

            similarity = np.dot(question_embedding, emb) / (
                np.linalg.norm(question_embedding) * np.linalg.norm(emb)
            )

            scored.append((similarity, chunk.content))

        scored.sort(reverse=True)

        top_chunks = [c[1] for c in scored[:5]]

        context = "\n\n".join(top_chunks)

        prompt = f"""
Use ONLY the context below to answer:

{context}

Question:
{question}
"""

        answer = self._ask_gemini(prompt)

        self.env['ai.agent.message'].create({
            'agent_id': self.id,
            'role': 'assistant',
            'body': answer
        })

    def _ask_gemini(self, prompt):
        api_key = self.env['ir.config_parameter'].sudo().get_param('gemini.api.key')

        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={api_key}"

        response = requests.post(url, json={
            "contents": [{
                "parts": [{"text": prompt}]
            }]
        })

        return response.json()['candidates'][0]['content']['parts'][0]['text']
