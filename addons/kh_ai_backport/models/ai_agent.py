from odoo import models, fields, api, _
import base64
import pickle
import numpy as np
import requests
import logging
import io

_logger = logging.getLogger(__name__)

# Try to import Gemini SDK
try:
    from google import genai
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

# Try to import PDF support
try:
    import PyPDF2
    HAS_PDF = True
except ImportError:
    HAS_PDF = False

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
        """
        Intercept the 'Ask AI' query before it goes to Odoo's native engine.
        If there are attachments, send them to Gemini bridge for processing.
        """
        # 1. Check if there are attachments to process with Gemini
        if attachment_ids and HAS_GENAI:
            _logger.info(f"AI Agent Bridge: Intercepting query with {len(attachment_ids)} attachment(s)")
            
            # 2. Fetch and extract text from attachments
            attachments = self.env['ir.attachment'].browse(attachment_ids)
            combined_text = ""
            
            for attach in attachments:
                _logger.info(f"AI Agent Bridge: Processing attachment {attach.name}")
                
                # Try PDF extraction first if available
                extracted_text = ""
                if HAS_PDF and attach.mimetype == 'application/pdf':
                    extracted_text = self._extract_pdf_text(attach)
                
                # Fallback to plain text extraction
                if not extracted_text:
                    extracted_text = self._extract_text(attach)
                
                if extracted_text:
                    combined_text += f"\n[File: {attach.name}]\n{extracted_text}\n"
                    _logger.info(f"AI Agent Bridge: Extracted {len(extracted_text)} characters from {attach.name}")
            
            # 3. If we found text, bypass native AI and go straight to Gemini
            if combined_text:
                _logger.info("AI Agent Bridge: Activating Gemini for document processing")
                self._send_ai_status_log(_("🤖 Bridge Active: Processing document with Gemini..."))
                
                # Combine document context with user question
                full_prompt = f"Document Context:\n{combined_text}\n\nUser Question: {query}"
                answer = self._ask_gemini(full_prompt)
                
                # Post answer as a comment
                if answer:
                    self.message_post(body=answer, message_type='comment')
                    return answer

        # 4. Status feedback for file analysis
        self._send_ai_status_log(_("Step 1/2: Analyzing sources and attached documents..."))

        # 5. If no attachments or Gemini not available, use native RAG
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

    def _extract_pdf_text(self, attachment):
        """Extract text from a PDF attachment using PyPDF2."""
        if not HAS_PDF or attachment.mimetype != 'application/pdf':
            return ""
        
        try:
            pdf_data = base64.b64decode(attachment.datas)
            pdf_file = io.BytesIO(pdf_data)
            reader = PyPDF2.PdfReader(pdf_file)
            extracted_text = ""
            
            for page_num, page in enumerate(reader.pages, 1):
                page_text = page.extract_text() or ""
                extracted_text += page_text
                _logger.debug(f"AI Agent Bridge: Extracted {len(page_text)} chars from page {page_num}")
            
            _logger.info(f"AI Agent Bridge: PDF extraction complete ({len(extracted_text)} total chars)")
            return extracted_text
        except Exception as e:
            _logger.error(f"AI Agent Bridge: Error extracting PDF text: {str(e)}")
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
        """Call Gemini API with the new google-genai SDK."""
        api_key = self.env['ir.config_parameter'].sudo().get_param('gemini.api.key')
        if not api_key:
            _logger.warning("AI Agent Bridge: Gemini API key not configured")
            return "Gemini API key not configured."
        
        try:
            _logger.info("AI Agent Bridge: Initializing Gemini client")
            client = genai.Client(api_key=api_key)
            
            _logger.info("AI Agent Bridge: Sending request to Gemini API")
            response = client.models.generate_content(
                model='gemini-2.0-flash',
                contents=prompt
            )
            
            result = response.text
            _logger.info(f"AI Agent Bridge: Received Gemini response ({len(result)} chars)")
            return result
            
        except Exception as e:
            _logger.error(f"AI Agent Bridge: Gemini API error: {str(e)}", exc_info=True)
            return f"Gemini call failed: {e}"
